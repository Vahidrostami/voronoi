"""Investigation Queue — SQLite-backed queue for investigation lifecycle.

Tracks investigations from queued → running → complete/failed,
with concurrency limits and follow-up detection.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional


@dataclass
class Investigation:
    """An investigation in the queue."""
    id: int = 0
    chat_id: str = ""
    status: str = "queued"            # queued | running | complete | failed | cancelled
    investigation_type: str = "lab"   # repo | lab
    repo: Optional[str] = None        # owner/repo if repo-bound
    question: str = ""
    slug: str = ""
    mode: str = "investigate"         # investigate | explore | build | experiment
    rigor: str = "scientific"
    codename: str = ""               # brain-themed codename (e.g. "Dopamine")
    workspace_path: Optional[str] = None
    sandbox_id: Optional[str] = None
    github_url: Optional[str] = None
    parent_id: Optional[int] = None   # for follow-ups
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id           TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'queued'
                      CHECK(status IN ('queued', 'running', 'complete', 'failed', 'cancelled')),
    investigation_type TEXT NOT NULL DEFAULT 'lab'
                      CHECK(investigation_type IN ('repo', 'lab')),
    repo              TEXT,
    question          TEXT NOT NULL,
    slug              TEXT NOT NULL,
    mode              TEXT NOT NULL DEFAULT 'investigate',
    rigor             TEXT NOT NULL DEFAULT 'scientific',
    codename          TEXT NOT NULL DEFAULT '',
    workspace_path    TEXT,
    sandbox_id        TEXT,
    github_url        TEXT,
    parent_id         INTEGER REFERENCES investigations(id),
    created_at        REAL NOT NULL,
    started_at        REAL,
    completed_at      REAL,
    error             TEXT
);

CREATE INDEX IF NOT EXISTS idx_inv_status ON investigations(status);
CREATE INDEX IF NOT EXISTS idx_inv_chat ON investigations(chat_id);
CREATE INDEX IF NOT EXISTS idx_inv_repo ON investigations(repo);
"""

_MIGRATION_ADD_CODENAME = """
ALTER TABLE investigations ADD COLUMN codename TEXT NOT NULL DEFAULT '';
"""


class InvestigationQueue:
    """SQLite-backed investigation queue with concurrency control."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(_SCHEMA)
            # Migrate existing databases that lack the codename column
            try:
                conn.execute("SELECT codename FROM investigations LIMIT 1")
            except sqlite3.OperationalError:
                conn.executescript(_MIGRATION_ADD_CODENAME)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def enqueue(self, inv: Investigation) -> int:
        """Add an investigation to the queue. Returns the investigation ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO investigations "
                "(chat_id, status, investigation_type, repo, question, slug, "
                " mode, rigor, codename, parent_id, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (inv.chat_id, "queued", inv.investigation_type, inv.repo,
                 inv.question, inv.slug, inv.mode, inv.rigor,
                 inv.codename, inv.parent_id, inv.created_at),
            )
            inv_id: int = cursor.lastrowid  # type: ignore[assignment]
            # Assign a deterministic codename if none was provided
            if not inv.codename:
                from voronoi.gateway.codename import codename_for_id
                codename = codename_for_id(inv_id)
                conn.execute(
                    "UPDATE investigations SET codename=? WHERE id=?",
                    (codename, inv_id),
                )
            return inv_id

    def next_ready(self, max_concurrent: int = 2) -> Optional[Investigation]:
        """Get the next queued investigation if under concurrency limit."""
        with self._connect() as conn:
            running = conn.execute(
                "SELECT COUNT(*) as cnt FROM investigations WHERE status = 'running'",
            ).fetchone()["cnt"]

            if running >= max_concurrent:
                return None

            row = conn.execute(
                "SELECT * FROM investigations WHERE status = 'queued' "
                "ORDER BY created_at ASC LIMIT 1",
            ).fetchone()

            if row is None:
                return None

            return self._row_to_investigation(row)

    def start(self, investigation_id: int, workspace_path: str, sandbox_id: Optional[str] = None) -> None:
        """Mark an investigation as running."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE investigations SET status='running', started_at=?, "
                "workspace_path=?, sandbox_id=? WHERE id=? AND status='queued'",
                (time.time(), workspace_path, sandbox_id, investigation_id),
            )

    def complete(self, investigation_id: int, github_url: Optional[str] = None) -> None:
        """Mark an investigation as complete."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE investigations SET status='complete', completed_at=?, "
                "github_url=? WHERE id=? AND status='running'",
                (time.time(), github_url, investigation_id),
            )

    def fail(self, investigation_id: int, error: str) -> None:
        """Mark an investigation as failed."""
        with self._connect() as conn:
            conn.execute(
                "UPDATE investigations SET status='failed', completed_at=?, "
                "error=? WHERE id=? AND status='running'",
                (time.time(), error, investigation_id),
            )

    def cancel(self, investigation_id: int) -> bool:
        """Cancel a queued investigation. Returns True if cancelled."""
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE investigations SET status='cancelled', completed_at=? "
                "WHERE id=? AND status='queued'",
                (time.time(), investigation_id),
            )
            return cursor.rowcount > 0

    def get(self, investigation_id: int) -> Optional[Investigation]:
        """Get an investigation by ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM investigations WHERE id=?",
                (investigation_id,),
            ).fetchone()
            if row is None:
                return None
            return self._row_to_investigation(row)

    def get_by_chat(self, chat_id: str, limit: int = 10) -> list[Investigation]:
        """Get recent investigations for a chat."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigations WHERE chat_id=? "
                "ORDER BY created_at DESC LIMIT ?",
                (chat_id, limit),
            ).fetchall()
            return [self._row_to_investigation(r) for r in rows]

    def get_recent(self, limit: int = 10) -> list[Investigation]:
        """Get the most recent investigations across all chats."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigations "
                "ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [self._row_to_investigation(r) for r in rows]

    def get_running(self) -> list[Investigation]:
        """Get all running investigations."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigations WHERE status='running' "
                "ORDER BY started_at ASC",
            ).fetchall()
            return [self._row_to_investigation(r) for r in rows]

    def get_queued(self) -> list[Investigation]:
        """Get all queued investigations."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigations WHERE status='queued' "
                "ORDER BY created_at ASC",
            ).fetchall()
            return [self._row_to_investigation(r) for r in rows]

    def queue_position(self, investigation_id: int) -> int:
        """Get the position in the queue (0-based). -1 if not queued."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id FROM investigations WHERE status='queued' "
                "ORDER BY created_at ASC",
            ).fetchall()
            for i, row in enumerate(rows):
                if row["id"] == investigation_id:
                    return i
            return -1

    def find_by_repo(self, repo: str, status: Optional[str] = None) -> list[Investigation]:
        """Find investigations for a specific repo."""
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM investigations WHERE repo=? AND status=? "
                    "ORDER BY created_at DESC",
                    (repo, status),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM investigations WHERE repo=? "
                    "ORDER BY created_at DESC",
                    (repo,),
                ).fetchall()
            return [self._row_to_investigation(r) for r in rows]

    def format_status(self) -> str:
        """Format queue status for Telegram."""
        running = self.get_running()
        queued = self.get_queued()

        lines = ["📊 *Investigation Queue*\n"]

        if running:
            lines.append("*Running:*")
            for inv in running:
                elapsed = (time.time() - (inv.started_at or inv.created_at)) / 60
                label = inv.repo or inv.slug
                name = inv.codename or f"#{inv.id}"
                lines.append(f"  ⚡ {name} {label} ({elapsed:.0f}min)")

        if queued:
            lines.append("\n*Queued:*")
            for i, inv in enumerate(queued):
                label = inv.repo or inv.slug
                name = inv.codename or f"#{inv.id}"
                lines.append(f"  ⏳ {name} {label} (position {i+1})")

        if not running and not queued:
            lines.append("No active investigations.")

        return "\n".join(lines)

    def _row_to_investigation(self, row: sqlite3.Row) -> Investigation:
        return Investigation(
            id=row["id"],
            chat_id=row["chat_id"],
            status=row["status"],
            investigation_type=row["investigation_type"],
            repo=row["repo"],
            question=row["question"],
            slug=row["slug"],
            mode=row["mode"],
            rigor=row["rigor"],
            codename=row["codename"],
            workspace_path=row["workspace_path"],
            sandbox_id=row["sandbox_id"],
            github_url=row["github_url"],
            parent_id=row["parent_id"],
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error=row["error"],
        )
