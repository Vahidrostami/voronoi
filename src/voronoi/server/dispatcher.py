"""Investigation Dispatcher — provisions workspaces, launches agents, monitors progress.

The router enqueues investigations directly into the SQLite queue.
The dispatcher's job is to:
  1. dispatch_next() — launch queued investigations
  2. poll_progress() — monitor running investigations, send updates
  3. Generate teaser + PDF on completion and deliver via Telegram
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("voronoi.dispatcher")


@dataclass
class DispatcherConfig:
    """Configuration for the dispatcher."""
    base_dir: Path = field(default_factory=lambda: Path.home() / ".voronoi")
    max_concurrent: int = 2
    max_agents: int = 4
    agent_command: str = "copilot"
    agent_flags: str = "--allow-all"
    progress_interval: int = 30  # seconds between progress updates


@dataclass
class RunningInvestigation:
    """Tracks a running investigation for progress monitoring."""
    investigation_id: int
    workspace_path: Path
    tmux_session: str
    question: str
    mode: str
    started_at: float = field(default_factory=time.time)
    last_update_at: float = 0
    task_snapshot: dict = field(default_factory=dict)
    notified_findings: set = field(default_factory=set)
    phase: str = "starting"


class InvestigationDispatcher:
    """Launches queued investigations and monitors their progress.

    Integrates with the Telegram bridge via two callbacks:
      send_message(text)  — send a chat message
      send_document(chat_id, path, caption)  — send a file
    """

    def __init__(
        self,
        config: DispatcherConfig,
        send_message: Callable[[str], None],
        send_document: Callable[[str, Path, str], None] | None = None,
    ):
        self.config = config
        self.send_message = send_message
        self.send_document = send_document or (lambda *a: None)
        self.running: dict[int, RunningInvestigation] = {}
        self._queue = None
        self._workspace_mgr = None

    @property
    def queue(self):
        if self._queue is None:
            from voronoi.server.queue import InvestigationQueue
            self._queue = InvestigationQueue(self.config.base_dir / "queue.db")
        return self._queue

    @property
    def workspace_mgr(self):
        if self._workspace_mgr is None:
            from voronoi.server.workspace import WorkspaceManager
            self._workspace_mgr = WorkspaceManager(self.config.base_dir)
        return self._workspace_mgr

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    def dispatch_next(self) -> None:
        """Launch the next queued investigation if capacity allows."""
        inv = self.queue.next_ready(self.config.max_concurrent)
        if inv is None:
            logger.debug("dispatch_next: nothing ready (db=%s)", self.queue.db_path)
            return
        logger.info("Dispatching investigation #%d: %.60s", inv.id, inv.question)
        try:
            self._launch_investigation(inv)
        except Exception as e:
            logger.error("Failed to launch investigation #%d: %s", inv.id, e, exc_info=True)
            self.queue.fail(inv.id, str(e))
            self.send_message(
                f"💀 *Investigation #{inv.id} failed to launch*\n\nError: `{e}`"
            )

    def _launch_investigation(self, inv) -> None:
        from voronoi.server.repo_url import extract_repo_url

        repo_ref = extract_repo_url(inv.question) if inv.investigation_type == "repo" else None
        if repo_ref:
            ws = self.workspace_mgr.provision_repo(inv.id, repo_ref, inv.slug)
        else:
            ws = self.workspace_mgr.provision_lab(inv.id, inv.slug, inv.question)

        workspace_path = Path(ws.path)
        self.queue.start(inv.id, ws.path)

        self.send_message(
            f"🧫 *Lab workspace ready* — Investigation #{inv.id}\n\n"
            f"📂 `{workspace_path.name}`\n"
            f"🔬 Launching orchestrator..."
        )

        prompt = self._build_prompt(inv, workspace_path)
        prompt_file = workspace_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt)

        tmux_session = f"voronoi-inv-{inv.id}"
        self._launch_in_tmux(tmux_session, workspace_path)

        self.running[inv.id] = RunningInvestigation(
            investigation_id=inv.id,
            workspace_path=workspace_path,
            tmux_session=tmux_session,
            question=inv.question,
            mode=inv.mode,
        )

        logger.info("Investigation #%d LIVE in tmux=%s workspace=%s",
                    inv.id, tmux_session, workspace_path)

        self.send_message(
            f"⚡ *Investigation #{inv.id} is LIVE*\n\n"
            f"_{inv.question}_\n\n"
            f"🤖 Orchestrator dispatched — planning tasks, generating hypotheses...\n"
            f"I'll send updates as agents make progress. 🔥"
        )

    def _build_prompt(self, inv, workspace_path: Path) -> str:
        return (
            "You are the Voronoi swarm orchestrator. Your job: read the investigation question, "
            "plan tasks, spawn parallel worker agents, monitor their progress, merge "
            "completed work, and repeat until the investigation is complete.\n\n"
            f"## Investigation\n\n"
            f"**Question:** {inv.question}\n"
            f"**Mode:** {inv.mode}\n"
            f"**Rigor:** {inv.rigor}\n"
            f"**Workspace:** {workspace_path}\n\n"
            "## Personality — IMPORTANT\n\n"
            "Your Telegram notifications should be EXCITED, high-energy, and fun — like a hype crew "
            "that genuinely loves watching agents crush it. Use fire emojis, exclamation marks, "
            "celebrate wins, make science feel epic. But always stay INFORMATIVE — every message "
            "must include real numbers (task counts, progress, findings). Never fluff without facts.\n\n"
            "## Workflow\n\n"
            "1. Read PROMPT.md — understand the question fully\n"
            "2. Run `bd prime`, create an epic + tasks with dependencies\n"
            "3. OODA loop:\n"
            "   - Observe: `bd ready --json` for dispatchable tasks\n"
            "   - Orient: Check agent status, process results\n"
            "   - Decide: What to spawn, merge, retry, or analyze\n"
            "   - Act: Spawn agents, merge work, diagnose failures\n"
            "4. When converged, write `.swarm/deliverable.md` and push results\n\n"
            "## Tools\n\n"
            "Task tracking:\n"
            "  bd prime / bd create / bd ready --json / bd close\n\n"
            "Spawn agents:\n"
            "  ./scripts/spawn-agent.sh <task-id> <branch-name> /tmp/prompt-<branch>.txt\n\n"
            "Merge completed work:\n"
            "  ./scripts/merge-agent.sh <branch-name> <task-id>\n\n"
            "Telegram notifications:\n"
            "  source ./scripts/notify-telegram.sh\n"
            '  notify_telegram "event_type" "message"\n\n'
            "## Rules\n"
            "- Write detailed worker prompts with full context\n"
            "- No overlapping file scopes between agents\n"
            "- Push all completed work to remote when done\n"
            f"- Max concurrent agents: {self.config.max_agents}\n"
        )

    def _launch_in_tmux(self, session: str, workspace_path: Path) -> None:
        agent_cmd = self.config.agent_command
        agent_flags = self.config.agent_flags
        agent_bin = agent_cmd.split()[0]
        if not shutil.which(agent_bin):
            raise RuntimeError(f"Agent CLI not found: {agent_bin}")

        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(workspace_path)],
            capture_output=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", session,
             f'cd "{workspace_path}" && {agent_cmd} {agent_flags} '
             f'-p "$(cat .swarm/orchestrator-prompt.txt)"',
             "Enter"],
            capture_output=True,
        )

    # ------------------------------------------------------------------
    # Progress monitoring
    # ------------------------------------------------------------------

    def poll_progress(self) -> None:
        """Check progress of running investigations and send updates."""
        completed_ids = []

        for inv_id, run in self.running.items():
            now = time.time()
            if now - run.last_update_at < self.config.progress_interval:
                continue
            run.last_update_at = now

            result = subprocess.run(
                ["tmux", "has-session", "-t", run.tmux_session],
                capture_output=True,
            )
            session_alive = result.returncode == 0

            events = self._check_progress(run)
            if events:
                logger.info("Investigation #%d: %d events (phase=%s)",
                            inv_id, len(events), run.phase)
                self._send_progress_batch(run, events)

            if not session_alive or self._is_complete(run):
                reason = "tmux ended" if not session_alive else "complete"
                logger.info("Investigation #%d finished (%s)", inv_id, reason)
                self._handle_completion(run)
                completed_ids.append(inv_id)

        for inv_id in completed_ids:
            del self.running[inv_id]

    def _check_progress(self, run: RunningInvestigation) -> list[dict]:
        events: list[dict] = []
        try:
            result = subprocess.run(
                ["bd", "list", "--json"],
                capture_output=True, text=True, timeout=15,
                cwd=str(run.workspace_path),
            )
            if result.returncode == 0:
                tasks = json.loads(result.stdout)
                events.extend(self._diff_tasks(run, tasks))
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass
        events.extend(self._check_findings(run))
        events.extend(self._detect_phase(run))
        return events

    def _diff_tasks(self, run: RunningInvestigation, tasks: list[dict]) -> list[dict]:
        events: list[dict] = []
        current: dict = {}
        for t in tasks:
            tid = t.get("id", "")
            status = t.get("status", "")
            title = t.get("title", "")
            current[tid] = {"status": status, "title": title}

            old = run.task_snapshot.get(tid)
            if old is None and run.task_snapshot:
                events.append({"type": "task_new", "msg": f"📋 New: *{title}*"})
            elif old and old["status"] != status:
                if status == "closed":
                    events.append({"type": "task_done", "msg": f"✅ Done: *{title}*"})
                elif status == "in_progress" and old["status"] != "in_progress":
                    events.append({"type": "task_started", "msg": f"⚡ Working: *{title}*"})

        run.task_snapshot = current

        total = len(current)
        closed = sum(1 for t in current.values() if t["status"] == "closed")
        if total > 0 and events:
            pct = int(closed / total * 100)
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            events.append({"type": "progress", "msg": f"📊 `[{bar}]` {closed}/{total} tasks ({pct}%)"})
        return events

    def _check_findings(self, run: RunningInvestigation) -> list[dict]:
        events: list[dict] = []
        try:
            result = subprocess.run(
                ["bd", "list", "--json"],
                capture_output=True, text=True, timeout=15,
                cwd=str(run.workspace_path),
            )
            if result.returncode != 0:
                return events
            tasks = json.loads(result.stdout)
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            return events

        for task in tasks:
            tid = task.get("id", "")
            title = task.get("title", "")
            if "FINDING" in title.upper() and tid not in run.notified_findings:
                run.notified_findings.add(tid)
                notes = task.get("notes", "")
                effect = ""
                for line in notes.split("\n"):
                    if any(k in line.upper() for k in ("EFFECT_SIZE", "CI_95", "VALENCE")):
                        effect += f"\n  {line.strip()}"
                msg = f"🧪 *FINDING!*\n{title}"
                if effect:
                    msg += f"\n{effect}"
                events.append({"type": "finding", "msg": msg})
        return events

    def _detect_phase(self, run: RunningInvestigation) -> list[dict]:
        events: list[dict] = []
        ws = run.workspace_path
        old_phase = run.phase

        if (ws / ".swarm" / "deliverable.md").exists():
            run.phase = "complete"
        elif (ws / ".swarm" / "belief-map.json").exists():
            run.phase = "synthesizing"
        elif run.task_snapshot:
            in_progress = sum(1 for t in run.task_snapshot.values() if t["status"] == "in_progress")
            closed = sum(1 for t in run.task_snapshot.values() if t["status"] == "closed")
            if in_progress > 0 or closed > 0:
                run.phase = "investigating"
            elif len(run.task_snapshot) > 0:
                run.phase = "planning"

        if run.phase != old_phase:
            phase_msg = {
                "planning": "🗺️ *Planning phase* — Orchestrator is decomposing tasks...",
                "investigating": "🔬 *Investigation phase* — Agents running in parallel!",
                "synthesizing": "🧩 *Synthesis phase* — Integrating findings...",
                "complete": "📄 *Wrapping up* — Writing deliverable...",
            }.get(run.phase, f"Phase: {run.phase}")
            events.append({"type": "phase", "msg": phase_msg})
        return events

    def _send_progress_batch(self, run: RunningInvestigation, events: list[dict]) -> None:
        elapsed = (time.time() - run.started_at) / 60
        findings = [e for e in events if e["type"] == "finding"]
        phases = [e for e in events if e["type"] == "phase"]
        progress = [e for e in events if e["type"] == "progress"]
        tasks = [e for e in events if e["type"] in ("task_done", "task_started", "task_new")]

        lines = [f"📡 *Investigation #{run.investigation_id}* ({elapsed:.0f}min)\n"]
        for e in phases:
            lines.append(e["msg"])
        for e in findings:
            lines.append("")
            lines.append(e["msg"])
        if len(tasks) <= 5:
            for e in tasks:
                lines.append(e["msg"])
        elif tasks:
            done = sum(1 for e in tasks if e["type"] == "task_done")
            started = sum(1 for e in tasks if e["type"] == "task_started")
            new = sum(1 for e in tasks if e["type"] == "task_new")
            parts = []
            if done:
                parts.append(f"{done} completed")
            if started:
                parts.append(f"{started} started")
            if new:
                parts.append(f"{new} new")
            lines.append(f"📋 Tasks: {', '.join(parts)}")
        for e in progress:
            lines.append(e["msg"])

        self.send_message("\n".join(lines))

    def _is_complete(self, run: RunningInvestigation) -> bool:
        if (run.workspace_path / ".swarm" / "deliverable.md").exists():
            return True
        conv = run.workspace_path / ".swarm" / "convergence.json"
        if conv.exists():
            try:
                data = json.loads(conv.read_text())
                return data.get("status") in ("converged", "exhausted", "diminishing_returns")
            except (json.JSONDecodeError, OSError):
                pass
        return False

    # ------------------------------------------------------------------
    # Completion — teaser + PDF + publish
    # ------------------------------------------------------------------

    def _handle_completion(self, run: RunningInvestigation) -> None:
        elapsed = (time.time() - run.started_at) / 60
        total_tasks = len(run.task_snapshot)
        closed = sum(1 for t in run.task_snapshot.values() if t["status"] == "closed")

        logger.info("Investigation #%d complete: %d/%d tasks in %.1fmin",
                    run.investigation_id, closed, total_tasks, elapsed)
        self.queue.complete(run.investigation_id)

        # Build teaser + report
        from voronoi.gateway.report import ReportGenerator
        rg = ReportGenerator(run.workspace_path)
        teaser = rg.build_teaser(
            run.investigation_id, run.question,
            total_tasks, closed, elapsed,
        )
        self.send_message(teaser)

        # Generate PDF/MD and send as document
        report_path = rg.build_pdf()
        if report_path and report_path.exists():
            from voronoi.gateway.config import get_chat_id
            chat_id = get_chat_id(str(run.workspace_path.parent.parent))
            doc_type = "Manuscript" if rg.is_manuscript_format() else "Report"
            if chat_id:
                self.send_document(
                    chat_id, report_path,
                    f"Investigation #{run.investigation_id} — Full {doc_type}",
                )

        self._try_publish(run)

    def _try_publish(self, run: RunningInvestigation) -> None:
        try:
            from voronoi.server.publisher import GitHubPublisher
            publisher = GitHubPublisher()
            if not publisher.is_gh_available():
                return
            slug = run.workspace_path.name
            ok, url = publisher.publish(str(run.workspace_path), slug)
            if ok:
                self.send_message(f"📦 Published: [{slug}]({url})")
        except Exception:
            pass

    def _handle_abort(self) -> None:
        for inv_id, run in list(self.running.items()):
            subprocess.run(
                ["tmux", "kill-session", "-t", run.tmux_session],
                capture_output=True,
            )
            self.queue.fail(inv_id, "Aborted by operator")
            self.send_message(f"🛑 Investigation #{inv_id} aborted")
        self.running.clear()