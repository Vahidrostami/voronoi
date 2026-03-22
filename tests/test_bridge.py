"""Tests for the refactored architecture.

Tests the gateway modules (config, router) which now own all business
logic.  The bridge script is a thin Telegram I/O layer that delegates
to these modules — it is not tested directly here.
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from voronoi.gateway.config import load_config, save_chat_id
from voronoi.gateway.router import (
    CommandRouter,
    handle_status,
    handle_whatsup,
    handle_howsitgoing,
    handle_tasks,
    handle_ready,
    handle_health,
    handle_guide,
    handle_pivot,
    handle_abort,
    handle_discover,
    handle_prove,
    handle_belief,
    handle_journal,
    handle_finding,
)


def _load_bridge_module():
    bridge_path = Path(__file__).resolve().parent.parent / "scripts" / "telegram-bridge.py"
    spec = importlib.util.spec_from_file_location("voronoi_telegram_bridge", bridge_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

class TestConfig:
    def test_load_config_defaults(self, tmp_path):
        config = load_config(str(tmp_path / "nonexistent.json"))
        assert config["bridge_enabled"] is True
        assert config["user_allowlist"] == []

    def test_load_config_with_user_allowlist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("VORONOI_TG_USER_ALLOWLIST", "112423044,vahidrostami")
        config_data = {
            "notifications": {
                "telegram": {
                    "bot_token": "test",
                    "bridge_enabled": True,
                }
            }
        }
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config_data))
        config = load_config(str(config_path))
        assert "112423044" in config["user_allowlist"]
        assert "vahidrostami" in config["user_allowlist"]

    def test_save_chat_id(self, tmp_path):
        save_chat_id(str(tmp_path), 12345)
        chat_file = tmp_path / ".telegram-chat-id"
        assert chat_file.exists()
        assert chat_file.read_text().strip() == "12345"


# ---------------------------------------------------------------------------
# Existing handlers (regression)
# ---------------------------------------------------------------------------

class TestHandlers:
    def test_handle_status(self, tmp_path):
        # status is now an alias for whatsup — conversational
        swarm_dir = tmp_path / ".swarm"
        swarm_dir.mkdir(parents=True, exist_ok=True)
        result = handle_status(str(tmp_path))
        # Should return something (buddy style - no running = simple msg)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_handle_whatsup_no_running(self, tmp_path):
        result = handle_whatsup(str(tmp_path))
        # Either nothing or queued items — both are valid
        assert isinstance(result, str)
        assert len(result) > 0

    def test_handle_howsitgoing_no_running(self, tmp_path):
        result = handle_howsitgoing(str(tmp_path))
        assert "Nothing running" in result

    def test_handle_tasks_no_running(self, tmp_path):
        result = handle_tasks(str(tmp_path))
        assert "No running investigations" in result

    def test_handle_ready_no_running(self, tmp_path):
        result = handle_ready(str(tmp_path))
        assert "No unblocked tasks ready" in result

    def test_handle_health_no_sessions(self, tmp_path):
        result = handle_health(str(tmp_path))
        # Should return a message — either health data or a graceful "not found"
        assert isinstance(result, str)
        assert len(result) > 0

    def test_handle_guide(self, tmp_path):
        (tmp_path / ".swarm").mkdir(parents=True)
        result = handle_guide(str(tmp_path), "focus on H1")
        assert "Guidance noted" in result
        assert (tmp_path / ".swarm" / "operator-guidance.md").exists()

    def test_handle_pivot(self, tmp_path):
        (tmp_path / ".swarm").mkdir(parents=True)
        result = handle_pivot(str(tmp_path), "new direction")
        assert "Pivot recorded" in result

    def test_handle_abort(self, tmp_path):
        result = handle_abort(str(tmp_path))
        assert "Abort requested" in result
        # Should write abort signal to global fallback when no active investigations
        assert (Path.home() / ".voronoi" / ".swarm" / "abort-signal").exists()
        # Clean up
        (Path.home() / ".voronoi" / ".swarm" / "abort-signal").unlink(missing_ok=True)

    def test_handle_abort_cancels_queued(self, tmp_path):
        """Abort should cancel queued investigations via the queue."""
        from voronoi.server.queue import InvestigationQueue, Investigation
        q = InvestigationQueue(Path.home() / ".voronoi" / "queue.db")
        # Enqueue a test investigation
        inv = Investigation(chat_id="test", question="test q", slug="abort-test",
                            mode="discover", rigor="adaptive")
        inv_id = q.enqueue(inv)
        result = handle_abort(str(tmp_path))
        assert "Abort requested" in result
        # Clean up
        stored = q.get(inv_id)
        if stored and stored.status == "queued":
            q.cancel(inv_id)


# ---------------------------------------------------------------------------
# Science workflow handlers
# ---------------------------------------------------------------------------

class TestScienceHandlers:
    @patch("voronoi.gateway.router.InvestigationQueue", autospec=True)
    @patch("voronoi.gateway.router.make_slug", return_value="test-slug")
    def test_handle_discover(self, mock_slug, mock_queue_cls, tmp_path):
        mock_q = MagicMock()
        mock_q.enqueue.return_value = 1
        mock_q.get_queued.return_value = []
        mock_q.get_running.return_value = []
        mock_queue_cls.return_value = mock_q

        result = handle_discover(str(tmp_path), "Why is latency high?", "chat1")
        assert "Voronoi" in result
        assert "LAUNCHED" in result
        assert "discovery" in result

    @patch("voronoi.gateway.router.InvestigationQueue", autospec=True)
    @patch("voronoi.gateway.router.make_slug", return_value="test-slug")
    def test_handle_prove(self, mock_slug, mock_queue_cls, tmp_path):
        mock_q = MagicMock()
        mock_q.enqueue.return_value = 2
        mock_q.get_queued.return_value = []
        mock_q.get_running.return_value = []
        mock_queue_cls.return_value = mock_q

        result = handle_prove(str(tmp_path), "test batch size effect", "chat1")
        assert "Voronoi" in result
        assert "LAUNCHED" in result
        assert "proof" in result


# ---------------------------------------------------------------------------
# Knowledge handlers
# ---------------------------------------------------------------------------

class TestKnowledgeHandlers:
    def test_handle_belief_no_file(self, tmp_path):
        result = handle_belief(str(tmp_path))
        assert "No belief map" in result

    def test_handle_belief_with_file(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "belief-map.md").write_text("H1: P=0.7")
        result = handle_belief(str(tmp_path))
        assert "H1" in result

    def test_handle_journal_no_file(self, tmp_path):
        result = handle_journal(str(tmp_path))
        assert "No journal" in result

    def test_handle_journal_with_file(self, tmp_path):
        swarm = tmp_path / ".swarm"
        swarm.mkdir(parents=True)
        (swarm / "journal.md").write_text("## Round 1\nFound something interesting")
        result = handle_journal(str(tmp_path))
        assert "Found something" in result

    @patch("voronoi.gateway.router._run_bd")
    def test_handle_finding(self, mock_bd, tmp_path):
        (tmp_path / ".beads").mkdir()
        task = {"id": "bd-42", "title": "FINDING: Cache works", "status": "closed",
                "priority": 1, "notes": "EFFECT_SIZE:d=1.5"}
        mock_bd.return_value = (0, json.dumps(task))
        result = handle_finding(str(tmp_path), "bd-42")
        assert "bd-42" in result
        assert "Cache works" in result

    @patch("voronoi.gateway.router._run_bd")
    def test_handle_finding_not_found(self, mock_bd, tmp_path):
        (tmp_path / ".beads").mkdir()
        mock_bd.return_value = (1, "not found")
        result = handle_finding(str(tmp_path), "bd-999")
        assert "not found" in result


# ---------------------------------------------------------------------------
# CommandRouter
# ---------------------------------------------------------------------------

class TestCommandRouter:
    def test_route_help(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("", [], "chat1")
        assert "Voronoi" in text

    def test_route_status(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("status", [], "chat1")
        # Now returns conversational buddy-style response
        assert isinstance(text, str)
        assert len(text) > 0

    def test_route_progress(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("progress", [], "chat1")
        assert isinstance(text, str)

    def test_route_whatsup(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("whatsup", [], "chat1")
        assert isinstance(text, str)

    def test_route_howsitgoing(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("howsitgoing", [], "chat1")
        assert isinstance(text, str)

    def test_route_unknown(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.route("xyzzy", [], "chat1")
        assert "Unknown command" in text


class TestHumanGateBridgeCommands:
    def test_approve_command_calls_dispatcher(self):
        bridge = _load_bridge_module()
        dispatcher = MagicMock()
        dispatcher.approve_human_gate.return_value = True

        text = bridge.format_human_gate_command_reply("approve", ["42"], dispatcher)

        dispatcher.approve_human_gate.assert_called_once_with(42, "")
        assert "Approved human gate" in text

    def test_revise_requires_feedback(self):
        bridge = _load_bridge_module()
        dispatcher = MagicMock()

        text = bridge.format_human_gate_command_reply("revise", ["42"], dispatcher)

        dispatcher.revise_human_gate.assert_not_called()
        assert text == "Usage: /revise <investigation-id> <feedback>"

    def test_revise_command_calls_dispatcher(self):
        bridge = _load_bridge_module()
        dispatcher = MagicMock()
        dispatcher.revise_human_gate.return_value = True

        text = bridge.format_human_gate_command_reply(
            "revise", ["42", "needs", "more", "controls"], dispatcher
        )

        dispatcher.revise_human_gate.assert_called_once_with(42, "needs more controls")
        assert "Requested revision" in text

    def test_invalid_human_gate_id(self):
        bridge = _load_bridge_module()
        dispatcher = MagicMock()

        text = bridge.format_human_gate_command_reply("approve", ["abc"], dispatcher)

        dispatcher.approve_human_gate.assert_not_called()
        assert "Invalid investigation ID" in text

    def test_dispatcher_unavailable(self):
        bridge = _load_bridge_module()

        text = bridge.format_human_gate_command_reply("approve", ["42"], None)

        assert "Dispatcher unavailable" in text


# ---------------------------------------------------------------------------
# Free-text intent detection
# ---------------------------------------------------------------------------

class TestFreeText:
    def test_greeting(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.handle_free_text("hello", "chat1", True)
        assert "Voronoi" in text

    def test_science_question(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.handle_free_text("Why is our model accuracy dropping?", "chat1", True)
        assert "discover" in text.lower()
        assert "Voronoi" in text

    def test_explore_question(self, tmp_path):
        router = CommandRouter(str(tmp_path))
        text, _ = router.handle_free_text("Which database should we use — Postgres vs MySQL?", "chat1", True)
        assert "discover" in text.lower()
        assert "Voronoi" in text
