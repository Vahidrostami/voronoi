"""Progress streaming relay — real-time OODA updates to Telegram.

Monitors .swarm/ state and Beads task changes, relaying progress updates
back to a Telegram chat as the science engine works.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass
class ProgressEvent:
    """A progress event to relay to the user."""
    event_type: str       # ooda_cycle, finding, agent_spawn, agent_done, convergence, etc.
    message: str          # Formatted message for Telegram
    timestamp: float = field(default_factory=time.time)
    metadata: dict = field(default_factory=dict)


class ProgressRelay:
    """Monitors swarm progress and calls back with formatted events.

    Designed to be polled periodically (not a background thread) so the
    Telegram bridge can integrate it into its event loop.
    """

    def __init__(self, project_dir: str | Path):
        self.project_dir = Path(project_dir)
        self._last_task_snapshot: dict[str, str] = {}   # id -> status
        self._last_journal_size: int = 0
        self._last_inbox_files: set[str] = set()
        self._seen_findings: set[str] = set()

    def _bd_env(self) -> dict[str, str]:
        """Build env dict that sets BEADS_DIR if .beads exists in project."""
        env = os.environ.copy()
        if "BEADS_DIR" not in env:
            beads_dir = str(self.project_dir / ".beads")
            if os.path.isdir(beads_dir):
                env["BEADS_DIR"] = beads_dir
        return env

    def poll(self) -> list[ProgressEvent]:
        """Check for new progress events. Returns events since last poll."""
        events: list[ProgressEvent] = []

        events.extend(self._check_task_changes())
        events.extend(self._check_journal_updates())
        events.extend(self._check_findings())
        events.extend(self._check_convergence())

        return events

    def _check_task_changes(self) -> list[ProgressEvent]:
        """Detect task status transitions via Beads."""
        events = []
        try:
            result = subprocess.run(
                ["bd", "list", "--json"],
                capture_output=True, text=True, timeout=15,
                cwd=str(self.project_dir), env=self._bd_env(),
            )
            if result.returncode != 0:
                return events
            tasks = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            return events

        current_snapshot: dict[str, str] = {}
        for task in tasks:
            tid = task.get("id", "")
            status = task.get("status", "")
            title = task.get("title", "")
            current_snapshot[tid] = status

            old_status = self._last_task_snapshot.get(tid)
            if old_status is None:
                # New task
                if self._last_task_snapshot:  # Skip initial population
                    events.append(ProgressEvent(
                        event_type="task_created",
                        message=f"📋 New task: *{title}* (`{tid}`)",
                        metadata={"task_id": tid, "status": status},
                    ))
            elif old_status != status:
                if status == "closed":
                    events.append(ProgressEvent(
                        event_type="task_closed",
                        message=f"✅ Task done: *{title}* (`{tid}`)",
                        metadata={"task_id": tid, "old_status": old_status},
                    ))
                elif status == "in_progress" and old_status != "in_progress":
                    events.append(ProgressEvent(
                        event_type="task_started",
                        message=f"⚡ Working on: *{title}* (`{tid}`)",
                        metadata={"task_id": tid},
                    ))

        self._last_task_snapshot = current_snapshot

        # Summary stats
        total = len(current_snapshot)
        closed = sum(1 for s in current_snapshot.values() if s == "closed")
        in_progress = sum(1 for s in current_snapshot.values() if s == "in_progress")
        if events and total > 0:
            events.append(ProgressEvent(
                event_type="progress_summary",
                message=f"📊 Progress: {closed}/{total} done, {in_progress} in-flight",
                metadata={"closed": closed, "total": total, "in_progress": in_progress},
            ))

        return events

    def _check_journal_updates(self) -> list[ProgressEvent]:
        """Check for new journal entries."""
        events = []
        journal = self.project_dir / ".swarm" / "journal.md"
        if not journal.exists():
            return events

        try:
            content = journal.read_text()
        except OSError:
            return events

        current_size = len(content)
        if current_size > self._last_journal_size and self._last_journal_size > 0:
            # Extract the new content
            new_content = content[self._last_journal_size:].strip()
            if new_content:
                # Take first 200 chars as preview
                preview = new_content[:200]
                if len(new_content) > 200:
                    preview += "..."
                events.append(ProgressEvent(
                    event_type="journal_update",
                    message=f"📓 Journal update:\n_{preview}_",
                    metadata={"new_bytes": current_size - self._last_journal_size},
                ))

        self._last_journal_size = current_size
        return events

    def _check_findings(self) -> list[ProgressEvent]:
        """Check for new FINDING entries in Beads."""
        events = []
        try:
            result = subprocess.run(
                ["bd", "list", "--json"],
                capture_output=True, text=True, timeout=15,
                cwd=str(self.project_dir), env=self._bd_env(),
            )
            if result.returncode != 0:
                return events
            tasks = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            return events

        for task in tasks:
            tid = task.get("id", "")
            title = task.get("title", "")
            if "FINDING" in title.upper() and tid not in self._seen_findings:
                self._seen_findings.add(tid)
                notes = task.get("notes", "")
                # Extract key metrics from notes
                effect = ""
                for line in notes.split("\n"):
                    if "EFFECT_SIZE" in line.upper() or "CI_95" in line.upper():
                        effect = line.strip()
                        break
                msg = f"🧪 *FINDING*: {title}"
                if effect:
                    msg += f"\n  {effect}"
                events.append(ProgressEvent(
                    event_type="finding",
                    message=msg,
                    metadata={"task_id": tid},
                ))

        return events

    def _check_convergence(self) -> list[ProgressEvent]:
        """Check for convergence status."""
        events = []
        conv_file = self.project_dir / ".swarm" / "convergence.json"
        if not conv_file.exists():
            return events

        try:
            data = json.loads(conv_file.read_text())
            status = data.get("status", "")
            if status == "converged":
                events.append(ProgressEvent(
                    event_type="convergence",
                    message="🏁 *CONVERGED* — Science delivered!",
                    metadata=data,
                ))
            elif status == "exhausted":
                events.append(ProgressEvent(
                    event_type="convergence",
                    message="⚠️ *EXHAUSTED* — Max iterations reached. Delivering with honest limitations.",
                    metadata=data,
                ))
            elif status == "diminishing_returns":
                events.append(ProgressEvent(
                    event_type="convergence",
                    message="📉 *DIMINISHING RETURNS* — Last rounds improved <5%. Delivering as-is.",
                    metadata=data,
                ))
        except (json.JSONDecodeError, OSError):
            pass

        return events


def format_workflow_start(mode: str, rigor: str, summary: str) -> str:
    """Format a workflow start notification."""
    mode_emoji = {
        "investigate": "🔬",
        "explore": "🧭",
        "build": "🔨",
        "hybrid": "🔬🔨",
    }.get(mode, "🔷")

    rigor_emoji = {
        "standard": "",
        "analytical": "📊",
        "scientific": "🧪",
        "experimental": "🔬",
    }.get(rigor, "")

    return (
        f"{mode_emoji} *{mode.upper()}* mode activated {rigor_emoji}\n"
        f"Rigor: {rigor}\n\n"
        f"_{summary}_\n\n"
        f"Dispatching agents..."
    )


def format_workflow_complete(mode: str, total_tasks: int, findings: int, duration_min: float) -> str:
    """Format a workflow completion notification."""
    return (
        f"🏁 *{mode.upper()} COMPLETE*\n\n"
        f"Tasks: {total_tasks}\n"
        f"Findings: {findings}\n"
        f"Duration: {duration_min:.1f}min\n\n"
        f"Check deliverable: `.swarm/deliverable.md`"
    )
