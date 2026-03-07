"""Tests for voronoi.gateway.memory — conversation memory."""

import time
import tempfile
from pathlib import Path

import pytest

from voronoi.gateway.memory import ConversationMemory, Message, ConversationContext


@pytest.fixture
def memory(tmp_path):
    """Create a fresh in-memory-like ConversationMemory for testing."""
    db_path = tmp_path / "test_conversations.db"
    return ConversationMemory(db_path)


# ---------------------------------------------------------------------------
# Basic CRUD
# ---------------------------------------------------------------------------

class TestBasicCRUD:
    def test_save_and_retrieve_message(self, memory):
        msg = Message(chat_id="chat1", role="user", content="Hello world")
        msg_id = memory.save_message(msg)
        assert isinstance(msg_id, int)
        assert msg_id > 0

    def test_get_context_empty_chat(self, memory):
        ctx = memory.get_context("nonexistent")
        assert ctx.chat_id == "nonexistent"
        assert ctx.messages == []
        assert ctx.summary is None

    def test_get_context_returns_messages(self, memory):
        memory.save_message(Message(chat_id="c1", role="user", content="msg1"))
        memory.save_message(Message(chat_id="c1", role="assistant", content="reply1"))
        memory.save_message(Message(chat_id="c1", role="user", content="msg2"))

        ctx = memory.get_context("c1")
        assert len(ctx.messages) == 3
        assert ctx.messages[0].content == "msg1"
        assert ctx.messages[1].content == "reply1"
        assert ctx.messages[2].content == "msg2"

    def test_messages_are_chat_scoped(self, memory):
        memory.save_message(Message(chat_id="c1", role="user", content="for c1"))
        memory.save_message(Message(chat_id="c2", role="user", content="for c2"))

        ctx1 = memory.get_context("c1")
        ctx2 = memory.get_context("c2")
        assert len(ctx1.messages) == 1
        assert ctx1.messages[0].content == "for c1"
        assert len(ctx2.messages) == 1
        assert ctx2.messages[0].content == "for c2"


# ---------------------------------------------------------------------------
# Context window limits
# ---------------------------------------------------------------------------

class TestContextWindow:
    def test_max_messages_limit(self, memory):
        for i in range(30):
            memory.save_message(Message(chat_id="c1", role="user", content=f"msg{i}"))

        ctx = memory.get_context("c1", max_messages=10)
        assert len(ctx.messages) == 10
        # Should be the 10 most recent
        assert ctx.messages[-1].content == "msg29"

    def test_max_age_filter(self, memory):
        # Save an old message
        old_msg = Message(chat_id="c1", role="user", content="old",
                          timestamp=time.time() - 7200)  # 2 hours ago
        memory.save_message(old_msg)

        # Save a recent message
        memory.save_message(Message(chat_id="c1", role="user", content="recent"))

        # Default 30 min window should only get the recent one
        ctx = memory.get_context("c1", max_age_seconds=1800)
        assert len(ctx.messages) == 1
        assert ctx.messages[0].content == "recent"

    def test_large_age_window_gets_all(self, memory):
        old_msg = Message(chat_id="c1", role="user", content="old",
                          timestamp=time.time() - 3600)
        memory.save_message(old_msg)
        memory.save_message(Message(chat_id="c1", role="user", content="recent"))

        ctx = memory.get_context("c1", max_age_seconds=86400)  # 24 hours
        assert len(ctx.messages) == 2


# ---------------------------------------------------------------------------
# Summary and workflow state
# ---------------------------------------------------------------------------

class TestConversationState:
    def test_set_and_get_summary(self, memory):
        memory.set_summary("c1", "We discussed caching strategies")
        ctx = memory.get_context("c1")
        assert ctx.summary == "We discussed caching strategies"

    def test_set_active_workflow(self, memory):
        memory.save_message(Message(chat_id="c1", role="user", content="test"))
        memory.set_active_workflow("c1", "wf-123")
        ctx = memory.get_context("c1")
        assert ctx.active_workflow_id == "wf-123"

    def test_clear_active_workflow(self, memory):
        memory.set_active_workflow("c1", "wf-123")
        memory.set_active_workflow("c1", None)
        ctx = memory.get_context("c1")
        assert ctx.active_workflow_id is None


# ---------------------------------------------------------------------------
# Message count and clear
# ---------------------------------------------------------------------------

class TestCountAndClear:
    def test_message_count(self, memory):
        assert memory.get_message_count("c1") == 0
        memory.save_message(Message(chat_id="c1", role="user", content="a"))
        memory.save_message(Message(chat_id="c1", role="user", content="b"))
        assert memory.get_message_count("c1") == 2

    def test_clear_chat(self, memory):
        memory.save_message(Message(chat_id="c1", role="user", content="a"))
        memory.save_message(Message(chat_id="c1", role="user", content="b"))
        deleted = memory.clear_chat("c1")
        assert deleted == 2
        assert memory.get_message_count("c1") == 0

    def test_clear_empty_chat(self, memory):
        deleted = memory.clear_chat("nonexistent")
        assert deleted == 0


# ---------------------------------------------------------------------------
# Metadata persistence
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_metadata_roundtrip(self, memory):
        msg = Message(
            chat_id="c1", role="user", content="test",
            metadata={"intent": "investigate", "confidence": 0.85},
        )
        memory.save_message(msg)
        ctx = memory.get_context("c1")
        assert ctx.messages[0].metadata["intent"] == "investigate"
        assert ctx.messages[0].metadata["confidence"] == 0.85

    def test_empty_metadata(self, memory):
        msg = Message(chat_id="c1", role="user", content="test")
        memory.save_message(msg)
        ctx = memory.get_context("c1")
        assert ctx.messages[0].metadata == {}


# ---------------------------------------------------------------------------
# Role validation
# ---------------------------------------------------------------------------

class TestRoleValidation:
    def test_valid_roles(self, memory):
        for role in ("user", "assistant", "system"):
            msg = Message(chat_id="c1", role=role, content=f"{role} msg")
            memory.save_message(msg)

        ctx = memory.get_context("c1")
        assert len(ctx.messages) == 3

    def test_invalid_role_rejected(self, memory):
        msg = Message(chat_id="c1", role="invalid_role", content="test")
        with pytest.raises(Exception):  # sqlite3 CHECK constraint
            memory.save_message(msg)


# ---------------------------------------------------------------------------
# Concurrency safety
# ---------------------------------------------------------------------------

class TestConcurrency:
    def test_multiple_db_instances_same_file(self, tmp_path):
        """Two ConversationMemory instances on the same DB file should work (WAL mode)."""
        db_path = tmp_path / "shared.db"
        mem1 = ConversationMemory(db_path)
        mem2 = ConversationMemory(db_path)

        mem1.save_message(Message(chat_id="c1", role="user", content="from mem1"))
        mem2.save_message(Message(chat_id="c1", role="assistant", content="from mem2"))

        ctx = mem1.get_context("c1")
        assert len(ctx.messages) == 2


# ---------------------------------------------------------------------------
# Message.to_dict
# ---------------------------------------------------------------------------

class TestMessageToDict:
    def test_to_dict_excludes_message_id(self):
        msg = Message(chat_id="c1", role="user", content="test", message_id=42)
        d = msg.to_dict()
        assert "message_id" not in d
        assert d["chat_id"] == "c1"
        assert d["role"] == "user"
        assert d["content"] == "test"
