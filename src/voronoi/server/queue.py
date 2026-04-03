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
    status: str = "queued"            # queued | running | paused | review | complete | failed | cancelled
    investigation_type: str = "lab"   # repo | lab
    repo: Optional[str] = None        # owner/repo if repo-bound
    question: str = ""
    slug: str = ""
    mode: str = "discover"         # discover | prove
    rigor: str = "scientific"
    codename: str = ""               # brain-themed codename (e.g. "Dopamine")
    workspace_path: Optional[str] = None
    sandbox_id: Optional[str] = None
    github_url: Optional[str] = None
    parent_id: Optional[int] = None   # for follow-ups
    demo_source: Optional[str] = None  # demo name:path for demo-originated investigations
    lineage_id: Optional[int] = None   # root investigation ID for claim ledger scoping
    cycle_number: int = 1              # iteration round within a lineage
    pi_feedback: str = ""               # PI feedback for continuation rounds
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    error: Optional[str] = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS investigations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id           TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'queued'
                      CHECK(status IN ('queued', 'running', 'paused', 'complete', 'failed', 'cancelled')),
    investigation_type TEXT NOT NULL DEFAULT 'lab'
                      CHECK(investigation_type IN ('repo', 'lab')),
    repo              TEXT,
    question          TEXT NOT NULL,
    slug              TEXT NOT NULL,
    mode              TEXT NOT NULL DEFAULT 'discover',
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

_MIGRATION_ADD_DEMO_SOURCE = """
ALTER TABLE investigations ADD COLUMN demo_source TEXT;
"""

_MIGRATION_ADD_PAUSED_STATUS = """
-- Widen CHECK constraint to accept 'paused' and 'review' statuses.
-- SQLite doesn't support ALTER CHECK, so we recreate the table.
CREATE TABLE IF NOT EXISTS investigations_new (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id           TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'queued'
                      CHECK(status IN ('queued', 'running', 'paused', 'review', 'complete', 'failed', 'cancelled')),
    investigation_type TEXT NOT NULL DEFAULT 'lab'
                      CHECK(investigation_type IN ('repo', 'lab')),
    repo              TEXT,
    question          TEXT NOT NULL,
    slug              TEXT NOT NULL,
    mode              TEXT NOT NULL DEFAULT 'discover',
    rigor             TEXT NOT NULL DEFAULT 'scientific',
    codename          TEXT NOT NULL DEFAULT '',
    workspace_path    TEXT,
    sandbox_id        TEXT,
    github_url        TEXT,
    parent_id         INTEGER REFERENCES investigations_new(id),
    demo_source       TEXT,
    created_at        REAL NOT NULL,
    started_at        REAL,
    completed_at      REAL,
    error             TEXT
);
INSERT OR IGNORE INTO investigations_new SELECT * FROM investigations;
DROP TABLE investigations;
ALTER TABLE investigations_new RENAME TO investigations;
CREATE INDEX IF NOT EXISTS idx_inv_status ON investigations(status);
CREATE INDEX IF NOT EXISTS idx_inv_chat ON investigations(chat_id);
CREATE INDEX IF NOT EXISTS idx_inv_repo ON investigations(repo);
"""

_MIGRATION_ADD_LINEAGE = """
ALTER TABLE investigations ADD COLUMN lineage_id INTEGER;
ALTER TABLE investigations ADD COLUMN cycle_number INTEGER NOT NULL DEFAULT 1;
"""

_MIGRATION_ADD_PI_FEEDBACK = """
ALTER TABLE investigations ADD COLUMN pi_feedback TEXT NOT NULL DEFAULT '';
"""

_MIGRATION_ADD_REVIEW_STATUS = """
-- Widen CHECK constraint to accept 'review' status (for DBs already migrated to paused).
CREATE TABLE IF NOT EXISTS investigations_v3 (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id           TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'queued'
                      CHECK(status IN ('queued', 'running', 'paused', 'review', 'complete', 'failed', 'cancelled')),
    investigation_type TEXT NOT NULL DEFAULT 'lab'
                      CHECK(investigation_type IN ('repo', 'lab')),
    repo              TEXT,
    question          TEXT NOT NULL,
    slug              TEXT NOT NULL,
    mode              TEXT NOT NULL DEFAULT 'discover',
    rigor             TEXT NOT NULL DEFAULT 'scientific',
    codename          TEXT NOT NULL DEFAULT '',
    workspace_path    TEXT,
    sandbox_id        TEXT,
    github_url        TEXT,
    parent_id         INTEGER REFERENCES investigations_v3(id),
    demo_source       TEXT,
    lineage_id        INTEGER,
    cycle_number      INTEGER NOT NULL DEFAULT 1,
    created_at        REAL NOT NULL,
    started_at        REAL,
    completed_at      REAL,
    error             TEXT
);
INSERT OR IGNORE INTO investigations_v3 (
    id, chat_id, status, investigation_type, repo, question, slug,
    mode, rigor, codename, workspace_path, sandbox_id, github_url,
    parent_id, demo_source, lineage_id, cycle_number,
    created_at, started_at, completed_at, error
)
SELECT id, chat_id, status, investigation_type, repo, question, slug,
       mode, rigor, codename, workspace_path, sandbox_id, github_url,
       parent_id, demo_source, lineage_id, cycle_number,
       created_at, started_at, completed_at, error
FROM investigations;
DROP TABLE investigations;
ALTER TABLE investigations_v3 RENAME TO investigations;
CREATE INDEX IF NOT EXISTS idx_inv_status ON investigations(status);
CREATE INDEX IF NOT EXISTS idx_inv_chat ON investigations(chat_id);
CREATE INDEX IF NOT EXISTS idx_inv_repo ON investigations(repo);
"""


class InvestigationQueue:
    """SQLite-backed investigation queue with concurrency control."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        # Use a raw connection for schema init because executescript()
        # implicitly commits and manages its own transactions.
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        try:
            try:
                conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass
            conn.executescript(_SCHEMA)
            # Migrate existing databases that lack the codename column
            try:
                conn.execute("SELECT codename FROM investigations LIMIT 1")
            except sqlite3.OperationalError:
                conn.executescript(_MIGRATION_ADD_CODENAME)
            # Migrate existing databases that lack the demo_source column
            try:
                conn.execute("SELECT demo_source FROM investigations LIMIT 1")
            except sqlite3.OperationalError:
                conn.executescript(_MIGRATION_ADD_DEMO_SOURCE)
            # Migrate existing databases that have the old CHECK constraint
            # without 'paused' status.  Detect by trying an insert+rollback.
            try:
                conn.execute(
                    "INSERT INTO investigations "
                    "(chat_id, status, question, slug, created_at) "
                    "VALUES ('__migration_test', 'paused', '__test', '__test', 0)"
                )
                conn.execute(
                    "DELETE FROM investigations WHERE chat_id='__migration_test'"
                )
            except sqlite3.IntegrityError:
                conn.executescript(_MIGRATION_ADD_PAUSED_STATUS)
            # Migrate existing databases that lack lineage_id/cycle_number
            try:
                conn.execute("SELECT lineage_id FROM investigations LIMIT 1")
            except sqlite3.OperationalError:
                conn.executescript(_MIGRATION_ADD_LINEAGE)
            # Migrate existing databases that lack 'review' status support.
            try:
                conn.execute(
                    "INSERT INTO investigations "
                    "(chat_id, status, question, slug, created_at) "
                    "VALUES ('__migration_test_review', 'review', '__test', '__test', 0)"
                )
                conn.execute(
                    "DELETE FROM investigations WHERE chat_id='__migration_test_review'"
                )
            except sqlite3.IntegrityError:
                conn.executescript(_MIGRATION_ADD_REVIEW_STATUS)
            # Migrate existing databases that lack pi_feedback column
            try:
                conn.execute("SELECT pi_feedback FROM investigations LIMIT 1")
            except sqlite3.OperationalError:
                conn.executescript(_MIGRATION_ADD_PI_FEEDBACK)
        finally:
            conn.close()

    @contextmanager
    def _connect(self, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        # isolation_level=None disables Python's implicit transactions,
        # letting us control BEGIN/COMMIT explicitly (needed for
        # BEGIN IMMEDIATE in next_ready).
        conn = sqlite3.connect(str(self.db_path), timeout=10,
                               isolation_level=None)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:
            # WAL requires POSIX shared-memory locking; falls back to
            # DELETE journal mode on filesystems that lack it (e.g. NFS).
            pass
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield conn
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
        finally:
            conn.close()

    def enqueue(self, inv: Investigation) -> int:
        """Add an investigation to the queue. Returns the investigation ID."""
        with self._connect(immediate=True) as conn:
            cursor = conn.execute(
                "INSERT INTO investigations "
                "(chat_id, status, investigation_type, repo, question, slug, "
                " mode, rigor, codename, parent_id, lineage_id, cycle_number, "
                " pi_feedback, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (inv.chat_id, "queued", inv.investigation_type, inv.repo,
                 inv.question, inv.slug, inv.mode, inv.rigor,
                 inv.codename, inv.parent_id, inv.lineage_id,
                 inv.cycle_number, inv.pi_feedback, inv.created_at),
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
            # Set lineage_id to self if this is a root investigation
            if inv.lineage_id is None and inv.parent_id is None:
                conn.execute(
                    "UPDATE investigations SET lineage_id=? WHERE id=?",
                    (inv_id, inv_id),
                )
            return inv_id

    def next_ready(self, max_concurrent: int = 2) -> Optional[Investigation]:
        """Get and claim the next queued investigation if under concurrency limit.

        This is atomic: uses BEGIN IMMEDIATE to acquire a write lock
        before reading, preventing TOCTOU races with concurrent callers.
        The returned investigation is already marked as 'running'.
        """
        with self._connect(immediate=True) as conn:
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

            now = time.time()
            conn.execute(
                "UPDATE investigations SET status='running', started_at=? "
                "WHERE id=? AND status='queued'",
                (now, row["id"]),
            )

            # Re-read after update to return accurate state
            updated_row = conn.execute(
                "SELECT * FROM investigations WHERE id=?",
                (row["id"],),
            ).fetchone()

            return self._row_to_investigation(updated_row)

    def start(self, investigation_id: int, workspace_path: str, sandbox_id: Optional[str] = None) -> None:
        """Set workspace path for a running investigation.

        The investigation may already be in 'running' state (set by
        ``next_ready``).  This attaches the workspace metadata.
        For backward compat it also accepts 'queued' status.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE investigations SET status='running', started_at=COALESCE(started_at, ?), "
                "workspace_path=?, sandbox_id=? WHERE id=? AND status IN ('queued', 'running')",
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

    def pause(self, investigation_id: int, reason: str) -> None:
        """Pause a running investigation (e.g. auth expiry).

        Transitions running → paused.  Sets completed_at to the current
        time so _check_paused_timeouts can measure time-in-paused-state.
        resume() clears completed_at when the investigation restarts.
        """
        with self._connect() as conn:
            conn.execute(
                "UPDATE investigations SET status='paused', error=?, completed_at=? "
                "WHERE id=? AND status='running'",
                (reason, time.time(), investigation_id),
            )

    def resume(self, investigation_id: int) -> bool:
        """Resume a paused or failed investigation.

        Transitions paused|failed → running, clears the error field,
        and resets started_at so elapsed-time tracking is accurate.
        Returns True if the status was actually changed.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE investigations SET status='running', error=NULL, "
                "started_at=?, completed_at=NULL "
                "WHERE id=? AND status IN ('paused', 'failed')",
                (time.time(), investigation_id),
            )
            return cursor.rowcount > 0

    def review(self, investigation_id: int) -> bool:
        """Transition a running investigation to review status.

        The investigation is paused for human feedback before final completion.
        Returns True if the status was changed.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE investigations SET status='review', completed_at=? "
                "WHERE id=? AND status='running'",
                (time.time(), investigation_id),
            )
            return cursor.rowcount > 0

    def accept(self, investigation_id: int) -> bool:
        """Accept a reviewed investigation — transition review → complete.

        Returns True if the status was changed.
        """
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE investigations SET status='complete', completed_at=? "
                "WHERE id=? AND status='review'",
                (time.time(), investigation_id),
            )
            return cursor.rowcount > 0

    def continue_investigation(self, investigation_id: int,
                               feedback: str = "") -> Optional[int]:
        """Create a continuation investigation from a completed or reviewed one.

        Creates a new investigation with:
        - Same question (original, never mutated)
        - pi_feedback stores the PI's feedback for this round
        - parent_id set to the current investigation
        - Same lineage_id (for claim ledger scoping)
        - Incremented cycle_number
        - Same workspace_path (workspace reuse)

        Returns the new investigation ID, or None if the source is invalid.
        """
        inv = self.get(investigation_id)
        if inv is None:
            return None
        if inv.status not in ("review", "complete"):
            return None

        # Use the original question — feedback goes in pi_feedback, not
        # appended to the question.  Strip any prior-round feedback that
        # was appended by older code.
        question = inv.question.split("\n\n## PI Feedback")[0]

        lineage = inv.lineage_id or investigation_id

        from voronoi.server.runner import make_slug
        new_inv = Investigation(
            chat_id=inv.chat_id,
            investigation_type=inv.investigation_type,
            repo=inv.repo,
            question=question,
            slug=make_slug(question),
            mode=inv.mode,
            rigor=inv.rigor,
            codename=inv.codename,  # keep same codename across rounds
            parent_id=investigation_id,
            lineage_id=lineage,
            cycle_number=inv.cycle_number + 1,
            pi_feedback=feedback,
        )
        new_id = self.enqueue(new_inv)

        # Transfer workspace path so continuation reuses the workspace
        if inv.workspace_path:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE investigations SET workspace_path=? WHERE id=?",
                    (inv.workspace_path, new_id),
                )

        # Mark the source as complete if it was in review
        if inv.status == "review":
            with self._connect() as conn:
                conn.execute(
                    "UPDATE investigations SET status='complete' WHERE id=? AND status='review'",
                    (investigation_id,),
                )

        return new_id

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

    def get_paused(self) -> list[Investigation]:
        """Get all paused investigations."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM investigations WHERE status='paused' "
                "ORDER BY started_at ASC",
            ).fetchall()
            return [self._row_to_investigation(r) for r in rows]

    def format_status(self) -> str:
        """Format queue status for Telegram."""
        running = self.get_running()
        queued = self.get_queued()
        paused = self.get_paused()

        lines = ["📊 *Investigation Queue*\n"]

        if running:
            lines.append("*Running:*")
            for inv in running:
                elapsed = (time.time() - (inv.started_at or inv.created_at)) / 60
                label = inv.repo or inv.slug
                name = inv.codename or f"#{inv.id}"
                lines.append(f"  ⚡ {name} {label} ({elapsed:.0f}min)")

        if paused:
            lines.append("\n*Paused:*")
            for inv in paused:
                label = inv.repo or inv.slug
                name = inv.codename or f"#{inv.id}"
                reason = (inv.error or "unknown")[:60]
                lines.append(f"  ⏸ {name} {label} — {reason}")

        if queued:
            lines.append("\n*Queued:*")
            for i, inv in enumerate(queued):
                label = inv.repo or inv.slug
                name = inv.codename or f"#{inv.id}"
                lines.append(f"  ⏳ {name} {label} (position {i+1})")

        if not running and not queued and not paused:
            lines.append("No active investigations.")

        return "\n".join(lines)

    def _row_to_investigation(self, row: sqlite3.Row) -> Investigation:
        demo_source = None
        try:
            demo_source = row["demo_source"]
        except (IndexError, KeyError):
            pass
        lineage_id = None
        try:
            lineage_id = row["lineage_id"]
        except (IndexError, KeyError):
            pass
        cycle_number = 1
        try:
            cycle_number = row["cycle_number"] or 1
        except (IndexError, KeyError):
            pass
        pi_feedback = ""
        try:
            pi_feedback = row["pi_feedback"] or ""
        except (IndexError, KeyError):
            pass
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
            demo_source=demo_source,
            lineage_id=lineage_id,
            cycle_number=cycle_number,
            pi_feedback=pi_feedback,
            created_at=row["created_at"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            error=row["error"],
        )

    def set_demo_source(self, investigation_id: int, demo_name: str, demo_path: str) -> None:
        """Store the demo origin so the dispatcher can copy demo files."""
        value = f"{demo_name}:{demo_path}"
        with self._connect() as conn:
            conn.execute(
                "UPDATE investigations SET demo_source=? WHERE id=?",
                (value, investigation_id),
            )

    def get_demo_source(self, investigation_id: int) -> Optional[tuple[str, str]]:
        """Return (demo_name, demo_path) if this investigation originated from a demo."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT demo_source FROM investigations WHERE id=?",
                (investigation_id,),
            ).fetchone()
            if row is None or row["demo_source"] is None:
                return None
            parts = row["demo_source"].split(":", 1)
            if len(parts) != 2:
                return None
            return parts[0], parts[1]
