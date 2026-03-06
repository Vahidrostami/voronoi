"""Investigation Dispatcher — watches inbox, provisions workspaces, launches agents.

This is the missing piece that connects Telegram → inbox → workspace → orchestrator.
Designed to be polled from the Telegram bridge's event loop.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


@dataclass
class DispatcherConfig:
    """Configuration for the dispatcher."""
    base_dir: Path = field(default_factory=lambda: Path.home() / ".voronoi")
    max_concurrent: int = 2
    max_agents: int = 4
    agent_command: str = "copilot"
    agent_flags: str = "--allow-all"
    poll_interval: int = 10  # seconds between inbox checks
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
    phase: str = "starting"  # starting, planning, investigating, synthesizing, complete


class InvestigationDispatcher:
    """Watches inbox for commands, provisions workspaces, launches orchestrators.

    Integrates with the Telegram bridge — call poll_inbox() and poll_progress()
    from the bot's job_queue.
    """

    def __init__(
        self,
        config: DispatcherConfig,
        send_message: Callable[[str], None],
    ):
        self.config = config
        self.send_message = send_message  # callback to send Telegram messages
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
    # Inbox processing
    # ------------------------------------------------------------------

    def poll_inbox(self) -> None:
        """Check for new inbox commands and dispatch investigations."""
        inbox_dir = self.config.base_dir / ".swarm" / "inbox"
        if not inbox_dir.exists():
            return

        for cmd_file in sorted(inbox_dir.glob("*.json")):
            try:
                cmd = json.loads(cmd_file.read_text())
                self._process_command(cmd)
                # Move to processed
                processed_dir = inbox_dir / "processed"
                processed_dir.mkdir(exist_ok=True)
                cmd_file.rename(processed_dir / cmd_file.name)
            except Exception as e:
                self.send_message(f"❌ Failed to process command: {e}")
                # Move to failed
                failed_dir = inbox_dir / "failed"
                failed_dir.mkdir(exist_ok=True)
                cmd_file.rename(failed_dir / cmd_file.name)

        # Also check queue for ready investigations
        self._dispatch_next()

    def _process_command(self, cmd: dict) -> None:
        """Process an inbox command."""
        action = cmd.get("action", "")
        params = cmd.get("params", {})

        if action in ("investigate", "explore", "build", "experiment"):
            self._enqueue_investigation(cmd)
        elif action == "abort":
            self._handle_abort()
        # guide, pivot, etc. are handled directly by the bridge

    def _enqueue_investigation(self, cmd: dict) -> None:
        """Add an investigation to the queue."""
        from voronoi.server.queue import Investigation
        from voronoi.server.runner import create_investigation_from_text, make_slug

        params = cmd.get("params", {})
        question = params.get("question", params.get("description", params.get("hypothesis", "")))
        mode = params.get("mode", "investigate")
        rigor = params.get("rigor", "scientific")
        chat_id = cmd.get("chat_id", "telegram")

        inv = Investigation(
            chat_id=chat_id,
            question=question,
            slug=make_slug(question[:40]),
            mode=mode,
            rigor=rigor,
            investigation_type="lab",
        )

        inv_id = self.queue.enqueue(inv)

        queued_count = len(self.queue.get_queued())
        running_count = len(self.queue.get_running())

        mode_emoji = {"investigate": "🔬", "explore": "🧭", "build": "🔨", "experiment": "🧪"}.get(mode, "🔷")

        self.send_message(
            f"{mode_emoji} *Investigation #{inv_id} queued*\n\n"
            f"_{question}_\n\n"
            f"Mode: {mode} · Rigor: {rigor}\n"
            f"Queue: {queued_count} waiting · {running_count} running\n\n"
            f"Setting up lab workspace... 🧫"
        )

    def _dispatch_next(self) -> None:
        """Launch the next queued investigation if capacity allows."""
        inv = self.queue.next_ready(self.config.max_concurrent)
        if inv is None:
            return

        try:
            self._launch_investigation(inv)
        except Exception as e:
            self.queue.fail(inv.id, str(e))
            self.send_message(
                f"💀 *Investigation #{inv.id} failed to launch*\n\n"
                f"Error: `{e}`"
            )

    def _launch_investigation(self, inv) -> None:
        """Provision workspace and launch orchestrator for an investigation."""
        from voronoi.server.repo_url import extract_repo_url

        # 1. Provision workspace
        repo_ref = extract_repo_url(inv.question) if inv.investigation_type == "repo" else None

        if repo_ref:
            ws = self.workspace_mgr.provision_repo(inv.id, repo_ref, inv.slug)
        else:
            ws = self.workspace_mgr.provision_lab(inv.id, inv.slug, inv.question)

        workspace_path = Path(ws.path)

        # 2. Mark as running
        self.queue.start(inv.id, ws.path)

        self.send_message(
            f"🧫 *Lab workspace ready* — Investigation #{inv.id}\n\n"
            f"📂 `{workspace_path.name}`\n"
            f"🔬 Launching orchestrator..."
        )

        # 3. Build orchestrator prompt
        prompt = self._build_server_orchestrator_prompt(inv, workspace_path)

        # Write prompt to file
        prompt_file = workspace_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt)

        # 4. Launch orchestrator in tmux
        tmux_session = f"voronoi-inv-{inv.id}"
        self._launch_in_tmux(tmux_session, workspace_path, prompt)

        # 5. Track for progress monitoring
        self.running[inv.id] = RunningInvestigation(
            investigation_id=inv.id,
            workspace_path=workspace_path,
            tmux_session=tmux_session,
            question=inv.question,
            mode=inv.mode,
        )

        self.send_message(
            f"⚡ *Investigation #{inv.id} is LIVE*\n\n"
            f"_{inv.question}_\n\n"
            f"🤖 Orchestrator dispatched — planning tasks, generating hypotheses...\n"
            f"I'll send updates as agents make progress. 🔥"
        )

    def _build_server_orchestrator_prompt(self, inv, workspace_path: Path) -> str:
        """Build the orchestrator prompt for a server-mode investigation."""
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

    def _launch_in_tmux(self, session: str, workspace_path: Path, prompt: str) -> None:
        """Launch the orchestrator agent in a tmux session."""
        agent_cmd = self.config.agent_command
        agent_flags = self.config.agent_flags

        # Verify agent exists
        agent_bin = agent_cmd.split()[0]
        if not shutil.which(agent_bin):
            raise RuntimeError(f"Agent CLI not found: {agent_bin}")

        # Write prompt to a temp file the agent can read
        prompt_path = workspace_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_path.write_text(prompt)

        # Create tmux session and launch
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(workspace_path)],
            capture_output=True,
        )
        subprocess.run(
            ["tmux", "send-keys", "-t", session,
             f'cd "{workspace_path}" && {agent_cmd} {agent_flags} -p "$(cat .swarm/orchestrator-prompt.txt)"',
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

            # Rate-limit updates
            if now - run.last_update_at < self.config.progress_interval:
                continue
            run.last_update_at = now

            # Check if tmux session still exists
            result = subprocess.run(
                ["tmux", "has-session", "-t", run.tmux_session],
                capture_output=True,
            )
            session_alive = result.returncode == 0

            # Check task progress
            events = self._check_progress(run)

            if events:
                self._send_progress_batch(run, events)

            # Check for completion
            if not session_alive or self._is_complete(run):
                self._handle_completion(run)
                completed_ids.append(inv_id)

        for inv_id in completed_ids:
            del self.running[inv_id]

    def _check_progress(self, run: RunningInvestigation) -> list[dict]:
        """Check for progress changes in a running investigation."""
        events = []
        ws = run.workspace_path

        # Check Beads task status
        try:
            result = subprocess.run(
                ["bd", "list", "--json"],
                capture_output=True, text=True, timeout=15,
                cwd=str(ws),
            )
            if result.returncode == 0:
                tasks = json.loads(result.stdout)
                events.extend(self._diff_tasks(run, tasks))
        except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError):
            pass

        # Check for new findings
        events.extend(self._check_findings(run))

        # Check journal
        events.extend(self._check_journal(run))

        # Detect phase changes
        events.extend(self._detect_phase(run))

        return events

    def _diff_tasks(self, run: RunningInvestigation, tasks: list[dict]) -> list[dict]:
        """Detect task changes since last check."""
        events = []
        current = {}
        for t in tasks:
            tid = t.get("id", "")
            status = t.get("status", "")
            title = t.get("title", "")
            current[tid] = {"status": status, "title": title}

            old = run.task_snapshot.get(tid)
            if old is None and run.task_snapshot:
                events.append({
                    "type": "task_new",
                    "msg": f"📋 New: *{title}*",
                })
            elif old and old["status"] != status:
                if status == "closed":
                    events.append({
                        "type": "task_done",
                        "msg": f"✅ Done: *{title}*",
                    })
                elif status == "in_progress" and old["status"] != "in_progress":
                    events.append({
                        "type": "task_started",
                        "msg": f"⚡ Working: *{title}*",
                    })

        run.task_snapshot = current

        # Progress bar
        total = len(current)
        closed = sum(1 for t in current.values() if t["status"] == "closed")
        if total > 0 and events:
            pct = int(closed / total * 100)
            bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
            events.append({
                "type": "progress",
                "msg": f"📊 `[{bar}]` {closed}/{total} tasks ({pct}%)",
            })

        return events

    def _check_findings(self, run: RunningInvestigation) -> list[dict]:
        """Check for new findings."""
        events = []
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
                # Extract effect size if present
                effect = ""
                for line in notes.split("\n"):
                    if any(k in line.upper() for k in ("EFFECT_SIZE", "CI_95", "VALENCE")):
                        effect += f"\n  {line.strip()}"
                msg = f"🧪 *FINDING!*\n{title}"
                if effect:
                    msg += f"\n{effect}"
                events.append({"type": "finding", "msg": msg})

        return events

    def _check_journal(self, run: RunningInvestigation) -> list[dict]:
        """Check for journal updates."""
        journal = run.workspace_path / ".swarm" / "journal.md"
        if not journal.exists():
            return []
        # We don't send journal updates every poll — too noisy
        return []

    def _detect_phase(self, run: RunningInvestigation) -> list[dict]:
        """Detect investigation phase changes."""
        events = []
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
                "planning": "🗺️ *Planning phase* — Orchestrator is decomposing tasks and generating hypotheses...",
                "investigating": "🔬 *Investigation phase* — Agents are running experiments in parallel!",
                "synthesizing": "🧩 *Synthesis phase* — Integrating findings, updating belief map...",
                "complete": "📄 *Wrapping up* — Writing deliverable...",
            }.get(run.phase, f"Phase: {run.phase}")
            events.append({"type": "phase", "msg": phase_msg})

        return events

    def _send_progress_batch(self, run: RunningInvestigation, events: list[dict]) -> None:
        """Bundle progress events into a single message."""
        elapsed = (time.time() - run.started_at) / 60

        # Group events by priority
        findings = [e for e in events if e["type"] == "finding"]
        phases = [e for e in events if e["type"] == "phase"]
        progress = [e for e in events if e["type"] == "progress"]
        tasks = [e for e in events if e["type"] in ("task_done", "task_started", "task_new")]

        lines = [f"📡 *Investigation #{run.investigation_id}* ({elapsed:.0f}min)\n"]

        # Phase changes first
        for e in phases:
            lines.append(e["msg"])

        # Findings (most important!)
        for e in findings:
            lines.append("")
            lines.append(e["msg"])

        # Task updates (limit to avoid spam)
        if len(tasks) <= 5:
            for e in tasks:
                lines.append(e["msg"])
        elif tasks:
            done_count = sum(1 for e in tasks if e["type"] == "task_done")
            started_count = sum(1 for e in tasks if e["type"] == "task_started")
            new_count = sum(1 for e in tasks if e["type"] == "task_new")
            parts = []
            if done_count:
                parts.append(f"{done_count} completed")
            if started_count:
                parts.append(f"{started_count} started")
            if new_count:
                parts.append(f"{new_count} new")
            lines.append(f"📋 Tasks: {', '.join(parts)}")

        # Progress bar
        for e in progress:
            lines.append(e["msg"])

        self.send_message("\n".join(lines))

    def _is_complete(self, run: RunningInvestigation) -> bool:
        """Check if an investigation has completed."""
        # Check for deliverable
        if (run.workspace_path / ".swarm" / "deliverable.md").exists():
            return True
        # Check for convergence signal
        conv = run.workspace_path / ".swarm" / "convergence.json"
        if conv.exists():
            try:
                data = json.loads(conv.read_text())
                return data.get("status") in ("converged", "exhausted", "diminishing_returns")
            except (json.JSONDecodeError, OSError):
                pass
        return False

    def _handle_completion(self, run: RunningInvestigation) -> None:
        """Handle investigation completion."""
        elapsed = (time.time() - run.started_at) / 60

        # Count results
        total_tasks = len(run.task_snapshot)
        closed = sum(1 for t in run.task_snapshot.values() if t["status"] == "closed")
        findings = len(run.notified_findings)

        # Mark complete in queue
        self.queue.complete(run.investigation_id)

        # Check for deliverable
        deliverable = run.workspace_path / ".swarm" / "deliverable.md"
        has_deliverable = deliverable.exists()

        self.send_message(
            f"🏁 *Investigation #{run.investigation_id} COMPLETE!* 🎉\n\n"
            f"_{run.question}_\n\n"
            f"📊 {closed}/{total_tasks} tasks · {findings} findings · {elapsed:.0f}min\n"
            + (f"📄 Deliverable: `.swarm/deliverable.md`\n" if has_deliverable else "")
            + f"\n_Science delivered._ 🔬"
        )

        # Try to publish to GitHub
        self._try_publish(run)

    def _try_publish(self, run: RunningInvestigation) -> None:
        """Attempt to publish results to GitHub (best-effort)."""
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
            pass  # Publishing is best-effort

    def _handle_abort(self) -> None:
        """Abort all running investigations."""
        for inv_id, run in list(self.running.items()):
            subprocess.run(
                ["tmux", "kill-session", "-t", run.tmux_session],
                capture_output=True,
            )
            self.queue.fail(inv_id, "Aborted by operator")
            self.send_message(f"🛑 Investigation #{inv_id} aborted")
        self.running.clear()
