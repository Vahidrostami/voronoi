"""Conversation memory — per-chat SQLite persistence.

Stores message history per Telegram chat, enabling multi-turn scientific
conversations and context-aware follow-up questions.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterator, Optional


@dataclass
class Message:
    """A single message in a conversation."""
    chat_id: str
    role: str                  # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)  # intent, rigor, workflow_id, etc.
    message_id: Optional[int] = None              # DB primary key

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("message_id", None)
        return d


@dataclass
class ConversationContext:
    """Context window for a conversation — recent messages + summary."""
    chat_id: str
    messages: list[Message]
    summary: Optional[str] = None  # Compressed summary of older messages
    active_workflow_id: Optional[str] = None


# SQL schema
_SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id     TEXT NOT NULL,
    role        TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content     TEXT NOT NULL,
    timestamp   REAL NOT NULL,
    metadata    TEXT NOT NULL DEFAULT '{}',
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_messages_chat_ts
    ON messages(chat_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS conversation_state (
    chat_id             TEXT PRIMARY KEY,
    summary             TEXT,
    active_workflow_id   TEXT,
    last_activity       REAL NOT NULL,
    updated_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


class ConversationMemory:
    """Per-chat conversation memory backed by SQLite.

    Thread-safe: uses WAL mode and per-call connections.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def save_message(self, msg: Message) -> int:
        """Persist a message. Returns the message ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO messages (chat_id, role, content, timestamp, metadata) "
                "VALUES (?, ?, ?, ?, ?)",
                (msg.chat_id, msg.role, msg.content, msg.timestamp, json.dumps(msg.metadata)),
            )
            # Update conversation state
            conn.execute(
                "INSERT INTO conversation_state (chat_id, last_activity, active_workflow_id) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET last_activity=excluded.last_activity",
                (msg.chat_id, msg.timestamp, msg.metadata.get("workflow_id")),
            )
            return cursor.lastrowid  # type: ignore[return-value]

    def get_context(
        self,
        chat_id: str,
        max_messages: int = 20,
        max_age_seconds: float = 1800,  # 30 minutes
    ) -> ConversationContext:
        """Load recent conversation context for a chat.

        Returns up to `max_messages` within `max_age_seconds`.
        """
        cutoff = time.time() - max_age_seconds
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, chat_id, role, content, timestamp, metadata "
                "FROM messages "
                "WHERE chat_id = ? AND timestamp > ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (chat_id, cutoff, max_messages),
            ).fetchall()

            messages = [
                Message(
                    chat_id=r["chat_id"],
                    role=r["role"],
                    content=r["content"],
                    timestamp=r["timestamp"],
                    metadata=json.loads(r["metadata"]),
                    message_id=r["id"],
                )
                for r in reversed(rows)  # chronological order
            ]

            state = conn.execute(
                "SELECT summary, active_workflow_id FROM conversation_state WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()

            return ConversationContext(
                chat_id=chat_id,
                messages=messages,
                summary=state["summary"] if state else None,
                active_workflow_id=state["active_workflow_id"] if state else None,
            )

    def set_summary(self, chat_id: str, summary: str) -> None:
        """Update the compressed summary for a chat."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversation_state (chat_id, summary, last_activity) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET summary=excluded.summary, "
                "updated_at=datetime('now')",
                (chat_id, summary, time.time()),
            )

    def set_active_workflow(self, chat_id: str, workflow_id: Optional[str]) -> None:
        """Set or clear the active workflow for a chat."""
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO conversation_state (chat_id, active_workflow_id, last_activity) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET "
                "active_workflow_id=excluded.active_workflow_id, updated_at=datetime('now')",
                (chat_id, workflow_id, time.time()),
            )

    def get_message_count(self, chat_id: str) -> int:
        """Count total messages for a chat."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as cnt FROM messages WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
            return row["cnt"] if row else 0

    def clear_chat(self, chat_id: str) -> int:
        """Remove all messages for a chat. Returns count deleted."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            conn.execute("DELETE FROM conversation_state WHERE chat_id = ?", (chat_id,))
            return cursor.rowcount
