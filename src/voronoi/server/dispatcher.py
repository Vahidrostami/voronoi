"""Investigation Dispatcher — provisions workspaces, launches agents, monitors progress.

The router enqueues investigations directly into the SQLite queue.
The dispatcher's job is to:
  1. dispatch_next() — launch queued investigations
  2. poll_progress() — monitor running investigations, send updates
  3. Enforce science gates (pre-registration, review, convergence)
  4. Generate teaser + PDF on completion and deliver via Telegram
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

from voronoi.gateway.progress import (
    MODE_EMOJI, MODE_VERB, progress_bar, estimate_remaining,
    voronoi_header, phase_label,
)

logger = logging.getLogger("voronoi.dispatcher")


@dataclass
class DispatcherConfig:
    """Configuration for the dispatcher."""
    base_dir: Path = field(default_factory=lambda: Path.home() / ".voronoi")
    max_concurrent: int = 2
    max_agents: int = 4
    agent_command: str = "copilot"
    agent_flags: str = "--allow-all"
    orchestrator_model: str = ""  # e.g. "claude-opus-4.6", "" = CLI default
    worker_model: str = ""        # e.g. "claude-sonnet-4.6", "" = CLI default
    progress_interval: int = 30  # seconds between progress updates
    timeout_hours: int = 8       # max hours before marking investigation exhausted
    max_retries: int = 2         # max times to restart a dead agent
    stall_minutes: int = 45      # warn/restart if 0 tasks after this long


@dataclass
class RunningInvestigation:
    """Tracks a running investigation for progress monitoring."""
    investigation_id: int
    workspace_path: Path
    tmux_session: str
    question: str
    mode: str
    codename: str = ""
    chat_id: str = ""
    rigor: str = "standard"
    started_at: float = field(default_factory=time.time)
    last_update_at: float = 0
    task_snapshot: dict = field(default_factory=dict)
    notified_findings: set = field(default_factory=set)
    notified_paradigm_stress: bool = False
    phase: str = "starting"
    improvement_rounds: int = 0
    eval_score: float = 0.0
    retry_count: int = 0
    stall_warned: bool = False

    @property
    def label(self) -> str:
        return self.codename or f"#{self.investigation_id}"

    @property
    def log_path(self) -> Path:
        return self.workspace_path / ".swarm" / "agent.log"


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
        """Launch the next queued investigation if capacity allows.

        Also recovers 'running' investigations from a previous dispatcher
        instance that died (e.g. bridge restart). If a row is marked
        'running' in the DB but not tracked in self.running, we re-adopt
        it so progress monitoring resumes.
        """
        # Recovery: re-adopt running investigations we're not tracking
        self._recover_running()

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
            label = inv.codename or f"#{inv.id}"
            self.send_message(
                f"💀 *Voronoi · {label} failed to launch*\n\nError: `{e}`"
            )

    def _recover_running(self) -> None:
        """Re-adopt running investigations from a previous dispatcher instance.

        If the bridge/dispatcher restarts, self.running is empty but the DB
        may still have investigations marked 'running' with a workspace_path.
        For each, check if the tmux session is still alive and re-adopt it.
        If tmux is dead, check if it completed (deliverable exists) or failed.
        """
        try:
            db_running = self.queue.get_running()
        except Exception:
            return

        for inv in db_running:
            if inv.id in self.running:
                continue  # already tracking

            if not inv.workspace_path:
                # No workspace — can't recover, mark failed
                self.queue.fail(inv.id, "No workspace path — cannot recover")
                continue

            workspace_path = Path(inv.workspace_path)
            tmux_session = f"voronoi-inv-{inv.id}"

            result = subprocess.run(
                ["tmux", "has-session", "-t", tmux_session],
                capture_output=True,
            )
            session_alive = result.returncode == 0

            # Re-create the RunningInvestigation tracker
            run = RunningInvestigation(
                investigation_id=inv.id,
                workspace_path=workspace_path,
                tmux_session=tmux_session,
                question=inv.question,
                mode=inv.mode,
                codename=inv.codename,
                chat_id=inv.chat_id,
                rigor=inv.rigor or "standard",
                started_at=inv.started_at or time.time(),
            )

            if not session_alive:
                # Check if it finished while we were down
                if (workspace_path / ".swarm" / "deliverable.md").exists():
                    logger.info("Recovered completed investigation #%d (%s)",
                                inv.id, inv.codename)
                    self._handle_completion(run)
                elif self._try_restart(run):
                    # Try to restart instead of marking failed
                    self.running[inv.id] = run
                    logger.info("Recovered and restarted investigation #%d (%s)",
                                inv.id, inv.codename)
                else:
                    logger.warning("Recovered dead investigation #%d (%s) — marking failed",
                                   inv.id, inv.codename)
                    self._handle_completion(run, failed=True,
                                            failure_reason="Agent exited (recovered after restart)")
            else:
                # Still alive — re-adopt for monitoring
                self.running[inv.id] = run
                logger.info("Re-adopted running investigation #%d (%s)",
                            inv.id, inv.codename)

    def _launch_investigation(self, inv) -> None:
        from voronoi.server.repo_url import extract_repo_url

        repo_ref = extract_repo_url(inv.question) if inv.investigation_type == "repo" else None
        if repo_ref:
            ws = self.workspace_mgr.provision_repo(inv.id, repo_ref, inv.slug)
        else:
            ws = self.workspace_mgr.provision_lab(inv.id, inv.slug, inv.question)

        workspace_path = Path(ws.path)

        # Copy demo files into workspace if this investigation originated from a demo
        demo_info = self.queue.get_demo_source(inv.id)
        if demo_info:
            self._copy_demo_files(demo_info, workspace_path)

        self.queue.start(inv.id, ws.path)

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
            codename=inv.codename,
            chat_id=inv.chat_id,
            rigor=getattr(inv, 'rigor', 'standard') or 'standard',
        )

        logger.info("Investigation %s (#%d) LIVE in tmux=%s workspace=%s",
                    inv.codename, inv.id, tmux_session, workspace_path)

        mode_emoji = MODE_EMOJI.get(inv.mode, "🔷")
        verb = MODE_VERB.get(inv.mode, inv.mode)
        label = inv.codename or f"#{inv.id}"
        self.send_message(
            f"🟢 *Voronoi · {label}* {mode_emoji} is LIVE\n\n"
            f"_{inv.question}_\n\n"
            f"Orchestrator is planning tasks and spawning agents.\n"
            f"First progress update in ~30s."
        )

    def _build_prompt(self, inv, workspace_path: Path) -> str:
        from voronoi.server.prompt import build_orchestrator_prompt

        rigor = getattr(inv, 'rigor', 'standard') or 'standard'
        label = inv.codename or f"#{inv.id}"

        return build_orchestrator_prompt(
            question=inv.question,
            mode=inv.mode,
            rigor=rigor,
            workspace_path=str(workspace_path),
            codename=label,
            max_agents=self.config.max_agents,
        )

    def _launch_in_tmux(self, session: str, workspace_path: Path) -> None:
        agent_cmd = self.config.agent_command
        agent_flags = self.config.agent_flags
        agent_bin = agent_cmd.split()[0]
        if not shutil.which(agent_bin):
            raise RuntimeError(f"Agent CLI not found: {agent_bin}")

        # Orchestrator gets its own model; workers use worker_model via spawn-agent.sh
        model_flag = ""
        if self.config.orchestrator_model:
            model_flag = f" --model {shlex.quote(self.config.orchestrator_model)}"

        log_path = workspace_path / ".swarm" / "agent.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(workspace_path)],
            capture_output=True,
        )
        # Enable tmux pane logging so we can inspect crashes after the fact.
        subprocess.run(
            ["tmux", "pipe-pane", "-t", session,
             f"cat >> {shlex.quote(str(log_path))}"],
            capture_output=True,
        )
        # Launch the agent.  The prompt is read from a file via shell
        # redirection to avoid ARG_MAX / tmux send-keys buffer issues
        # with large prompts.  shlex.quote prevents command injection.
        safe_ws = shlex.quote(str(workspace_path))
        safe_cmd = shlex.quote(agent_cmd)
        safe_flags = shlex.quote(agent_flags)
        subprocess.run(
            ["tmux", "send-keys", "-t", session,
             f'cd {safe_ws} && {safe_cmd} {safe_flags}{model_flag} '
             f'-p "$(cat .swarm/orchestrator-prompt.txt)" ; exit',
             "Enter"],
            capture_output=True,
        )

    def _copy_demo_files(self, demo_info: tuple[str, str], workspace_path: Path) -> None:
        """Copy demo directory contents into the workspace."""
        demo_name, demo_src_path = demo_info
        demo_src = Path(demo_src_path)
        if not demo_src.is_dir():
            logger.warning("Demo source not found: %s", demo_src)
            return
        demo_dst = workspace_path / "demos" / demo_name
        if demo_dst.exists():
            shutil.rmtree(demo_dst)
        shutil.copytree(demo_src, demo_dst)
        logger.info("Copied demo files from %s to %s", demo_src, demo_dst)

    # ------------------------------------------------------------------
    # Progress monitoring
    # ------------------------------------------------------------------

    def poll_progress(self) -> None:
        """Check progress of running investigations and send updates."""
        # Check for abort signal from the router
        self._check_abort_signal()

        completed_ids = []

        for inv_id, run in self.running.items():
            now = time.time()
            if now - run.last_update_at < self.config.progress_interval:
                continue
            run.last_update_at = now

            # Read eval_score from workspace if available
            self._refresh_eval_score(run)

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

            # Check for timeout
            elapsed_hours = (now - run.started_at) / 3600
            timed_out = elapsed_hours >= self.config.timeout_hours

            # Stall detection: warn if 0 tasks after stall_minutes
            if (session_alive and not run.stall_warned
                    and not run.task_snapshot
                    and elapsed_hours * 60 >= self.config.stall_minutes):
                run.stall_warned = True
                logger.warning("Investigation #%d stalled — 0 tasks after %.0fmin",
                               inv_id, elapsed_hours * 60)
                self.send_message(
                    f"⚠️ *Voronoi · {run.label}* — stalled\n\n"
                    f"No tasks created after {elapsed_hours * 60:.0f}min. "
                    f"The orchestrator may be stuck. "
                    f"Will auto-restart if the agent exits."
                )

            # Heartbeat-based stall detection for active agents
            if session_alive and run.task_snapshot:
                events.extend(self._check_heartbeat_stalls(run))

            if not session_alive or self._is_complete(run) or timed_out:
                if timed_out and not self._is_complete(run):
                    reason = f"timeout ({self.config.timeout_hours}h)"
                    logger.warning("Investigation #%d timed out after %.1fh",
                                   inv_id, elapsed_hours)
                    # Kill tmux session if still alive
                    if session_alive:
                        subprocess.run(
                            ["tmux", "kill-session", "-t", run.tmux_session],
                            capture_output=True,
                        )
                    # Write exhaustion convergence
                    self._write_timeout_convergence(run)
                    self._handle_completion(run, failed=True,
                                            failure_reason="Timed out")
                elif not session_alive and not self._is_complete(run):
                    # Try to restart the agent instead of giving up
                    if self._try_restart(run):
                        reason = "restarted"
                        logger.info("Investigation #%d restarted (attempt %d)",
                                    inv_id, run.retry_count)
                        continue  # don't add to completed_ids
                    reason = "agent crashed"
                    logger.warning("Investigation #%d agent exited without completing",
                                   inv_id)
                    self._handle_completion(run, failed=True,
                                            failure_reason="Agent exited unexpectedly")
                elif not session_alive:
                    reason = "agent exited (complete)"
                    self._handle_completion(run)
                else:
                    reason = "complete"
                    self._handle_completion(run)
                logger.info("Investigation #%d finished (%s)", inv_id, reason)
                completed_ids.append(inv_id)

        for inv_id in completed_ids:
            del self.running[inv_id]

    def _refresh_eval_score(self, run: RunningInvestigation) -> None:
        """Read evaluator score from workspace and update the run state."""
        eval_path = run.workspace_path / ".swarm" / "eval-score.json"
        if eval_path.exists():
            try:
                data = json.loads(eval_path.read_text())
                if not isinstance(data, dict):
                    logger.warning("eval-score.json is not a dict for #%d",
                                   run.investigation_id)
                    return
                score = float(data.get("score", 0.0))
                if score < 0 or score > 1.0:
                    logger.warning("eval-score.json score out of range [0,1] for #%d: %s",
                                   run.investigation_id, score)
                    return
                if score > 0:
                    run.eval_score = score
                    run.improvement_rounds = int(data.get("rounds", run.improvement_rounds))
            except (json.JSONDecodeError, OSError, ValueError) as e:
                logger.warning("Failed to read eval-score.json for #%d: %s",
                               run.investigation_id, e)

    def _write_timeout_convergence(self, run: RunningInvestigation) -> None:
        """Write convergence.json indicating timeout exhaustion."""
        conv_path = run.workspace_path / ".swarm" / "convergence.json"
        conv_path.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone
        data = {
            "status": "exhausted",
            "converged": False,
            "reason": f"Timed out after {self.config.timeout_hours}h",
            "score": run.eval_score,
            "blockers": ["timeout"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        conv_path.write_text(json.dumps(data, indent=2))

    def _check_progress(self, run: RunningInvestigation) -> list[dict]:
        events: list[dict] = []
        tasks: list[dict] | None = None
        try:
            result = subprocess.run(
                ["bd", "list", "--json"],
                capture_output=True, text=True, timeout=15,
                cwd=str(run.workspace_path),
            )
            if result.returncode == 0 and result.stdout.strip():
                tasks = json.loads(result.stdout)
                if isinstance(tasks, list):
                    events.extend(self._diff_tasks(run, tasks))
                else:
                    logger.warning("bd list --json returned non-list for #%d: %s",
                                   run.investigation_id, type(tasks).__name__)
                    tasks = None
            elif result.returncode != 0:
                logger.debug("bd list --json failed for #%d (exit=%d): %s",
                             run.investigation_id, result.returncode,
                             result.stderr.strip()[:200] if result.stderr else "")
        except subprocess.TimeoutExpired:
            logger.warning("bd list --json timed out for #%d", run.investigation_id)
        except FileNotFoundError:
            logger.error("bd command not found during progress check for #%d",
                         run.investigation_id)
        except json.JSONDecodeError as e:
            logger.warning("bd list --json returned invalid JSON for #%d: %s",
                           run.investigation_id, e)
        events.extend(self._check_findings(run, tasks))
        events.extend(self._check_design_invalid(run, tasks))
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

    def _check_findings(self, run: RunningInvestigation,
                         tasks: list[dict] | None = None) -> list[dict]:
        events: list[dict] = []
        if tasks is None:
            try:
                result = subprocess.run(
                    ["bd", "list", "--json"],
                    capture_output=True, text=True, timeout=15,
                    cwd=str(run.workspace_path),
                )
                if result.returncode != 0 or not result.stdout.strip():
                    return events
                parsed = json.loads(result.stdout)
                if not isinstance(parsed, list):
                    return events
                tasks = parsed
            except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError) as e:
                logger.debug("Findings check skipped for #%d: %s",
                             run.investigation_id, e)
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
                msg = f"� *NEW FINDING*\n{title}"
                if effect:
                    msg += f"\n{effect}"
                events.append({"type": "finding", "msg": msg})
        return events

    def _check_design_invalid(self, run: RunningInvestigation,
                               tasks: list[dict] | None = None) -> list[dict]:
        """Detect DESIGN_INVALID flags in task notes and alert."""
        events: list[dict] = []
        if tasks is None:
            return events
        for task in tasks:
            tid = task.get("id", "")
            notes = task.get("notes", "")
            title = task.get("title", "")
            if ("DESIGN_INVALID" in notes
                    and task.get("status") != "closed"
                    and tid not in getattr(run, "_notified_design_invalid", set())):
                if not hasattr(run, "_notified_design_invalid"):
                    run._notified_design_invalid = set()
                run._notified_design_invalid.add(tid)
                diagnosis = ""
                for line in notes.split("\n"):
                    if "DESIGN_INVALID" in line:
                        diagnosis = line.strip()[:200]
                        break
                events.append({
                    "type": "design_invalid",
                    "msg": f"🚨 *DESIGN INVALID* — {title}\n  {diagnosis}",
                })
        return events

    def _detect_phase(self, run: RunningInvestigation) -> list[dict]:
        events: list[dict] = []
        ws = run.workspace_path
        old_phase = run.phase

        if (ws / ".swarm" / "deliverable.md").exists():
            run.phase = "complete"
        elif (ws / ".swarm" / "convergence.json").exists():
            run.phase = "converging"
        elif (ws / ".swarm" / "belief-map.json").exists():
            run.phase = "synthesizing"
        elif (ws / ".swarm" / "scout-brief.md").exists() and run.phase == "scouting":
            run.phase = "planning"
        elif run.task_snapshot:
            # Detect science-specific phases
            titles = [t.get("title", "") for t in run.task_snapshot.values()]
            has_scout = any("scout" in t.lower() for t in titles)
            has_review = any(k in " ".join(titles).upper()
                            for k in ("STAT_REVIEW", "CRITIC_REVIEW", "METHODOLOGIST"))

            in_progress = sum(1 for t in run.task_snapshot.values() if t["status"] == "in_progress")
            closed = sum(1 for t in run.task_snapshot.values() if t["status"] == "closed")

            if has_scout and closed == 0 and in_progress > 0:
                run.phase = "scouting"
            elif has_review and in_progress > 0:
                run.phase = "reviewing"
            elif in_progress > 0 or closed > 0:
                run.phase = "investigating"
            elif len(run.task_snapshot) > 0:
                run.phase = "planning"

        if run.phase != old_phase:
            phase_msg = phase_label(run.mode, run.phase)
            events.append({"type": "phase", "msg": phase_msg})

        # Check for paradigm stress (Scientific+ only)
        if run.rigor in ("scientific", "experimental") and not run.notified_paradigm_stress:
            events.extend(self._check_paradigm_stress(run))

        return events

    def _check_paradigm_stress(self, run: RunningInvestigation) -> list[dict]:
        """Check for paradigm stress in scientific investigations."""
        events: list[dict] = []
        try:
            from voronoi.science import check_paradigm_stress
            result = check_paradigm_stress(run.workspace_path)
            if result.stressed:
                run.notified_paradigm_stress = True
                events.append({
                    "type": "paradigm_stress",
                    "msg": f"⚠️ *PARADIGM STRESS* — {result.contradiction_count} "
                           f"contradictions detected. Working model may need revision.",
                })
        except Exception as e:
            logger.debug("Paradigm stress check failed: %s", e)
        return events

    def _check_heartbeat_stalls(self, run: RunningInvestigation) -> list[dict]:
        """Check agent heartbeats for stalled workers."""
        events: list[dict] = []
        try:
            from voronoi.science import check_heartbeat_stall
            swarm_dir = run.workspace_path / ".swarm"
            if not swarm_dir.exists():
                return events
            for hb_file in swarm_dir.glob("heartbeat-*.jsonl"):
                branch = hb_file.stem.replace("heartbeat-", "")
                if check_heartbeat_stall(run.workspace_path, branch):
                    events.append({
                        "type": "heartbeat_stall",
                        "msg": f"⚠️ Agent `{branch}` may be stuck "
                               f"(same status for 10+ min)",
                    })
        except Exception as e:
            logger.debug("Heartbeat stall check failed: %s", e)
        return events

    def _send_progress_batch(self, run: RunningInvestigation, events: list[dict]) -> None:
        elapsed = (time.time() - run.started_at) / 60
        findings = [e for e in events if e["type"] == "finding"]
        phases = [e for e in events if e["type"] == "phase"]
        progress = [e for e in events if e["type"] == "progress"]
        tasks = [e for e in events if e["type"] in ("task_done", "task_started", "task_new")]

        mode_emoji = MODE_EMOJI.get(run.mode, "🔷")
        lines = [f"📡 *Voronoi · {run.label}* {mode_emoji} · {elapsed:.0f}min\n"]

        # Progress bar first — instant status at a glance
        total = len(run.task_snapshot)
        closed = sum(1 for t in run.task_snapshot.values() if t["status"] == "closed")
        if total > 0:
            bar = progress_bar(closed, total)
            eta = estimate_remaining(time.time() - run.started_at, closed, total)
            eta_str = f" · {eta}" if eta else ""
            lines.append(f"{bar}{eta_str}")

        for e in phases:
            lines.append(f"\n{e['msg']}")

        # Activity timeline — show what happened (up to 5 items)
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

        for e in findings:
            lines.append("")
            lines.append(e["msg"])

        for e in progress:
            lines.append(e["msg"])

        self.send_message("\n".join(lines))

    def _is_complete(self, run: RunningInvestigation) -> bool:
        if (run.workspace_path / ".swarm" / "deliverable.md").exists():
            # For standard rigor, deliverable is sufficient
            if run.rigor == "standard":
                return True
            # For higher rigor, also need convergence signal
            conv = run.workspace_path / ".swarm" / "convergence.json"
            if conv.exists():
                try:
                    data = json.loads(conv.read_text())
                    return data.get("converged", False) or \
                        data.get("status") in ("converged", "exhausted", "diminishing_returns")
                except (json.JSONDecodeError, OSError):
                    pass
            # Deliverable exists but no convergence signal — check if
            # we should generate one
            self._try_convergence_check(run)
            return False
        conv = run.workspace_path / ".swarm" / "convergence.json"
        if conv.exists():
            try:
                data = json.loads(conv.read_text())
                return data.get("status") in ("converged", "exhausted", "diminishing_returns")
            except (json.JSONDecodeError, OSError):
                pass
        return False

    def _try_convergence_check(self, run: RunningInvestigation) -> None:
        """Attempt to run a convergence check and write convergence.json.

        Also runs the convergence-gate.sh script for multi-signal validation
        when available, to prevent premature completion.
        """
        try:
            from voronoi.science import check_convergence, write_convergence
            result = check_convergence(
                run.workspace_path, run.rigor,
                eval_score=run.eval_score,
                improvement_rounds=run.improvement_rounds,
            )
            if result.converged or result.status in ("exhausted", "diminishing_returns"):
                # Run convergence-gate.sh for additional validation
                gate_script = run.workspace_path / "scripts" / "convergence-gate.sh"
                if not gate_script.exists():
                    # Try project-level scripts directory
                    gate_script = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "convergence-gate.sh"
                if gate_script.exists() and gate_script.stat().st_mode & 0o111:
                    try:
                        gate_result = subprocess.run(
                            [str(gate_script), str(run.workspace_path), run.rigor],
                            capture_output=True, text=True, timeout=30,
                            cwd=str(run.workspace_path),
                        )
                        if gate_result.returncode != 0:
                            logger.warning("Convergence gate FAILED for %s: %s",
                                           run.label, gate_result.stdout.strip()[:300])
                            # Don't write convergence — gate didn't pass
                            return
                    except (subprocess.TimeoutExpired, OSError) as e:
                        logger.debug("Convergence gate script failed: %s", e)

                write_convergence(run.workspace_path, result)
                logger.info("Convergence written for %s: %s", run.label, result.status)
        except Exception as e:
            logger.debug("Convergence check failed: %s", e)

    # ------------------------------------------------------------------
    # Completion — teaser + PDF + publish
    # ------------------------------------------------------------------

    def _handle_completion(self, run: RunningInvestigation, *,
                           failed: bool = False,
                           failure_reason: str = "") -> None:
        elapsed = (time.time() - run.started_at) / 60
        total_tasks = len(run.task_snapshot)
        closed = sum(1 for t in run.task_snapshot.values() if t["status"] == "closed")

        # Always clean up tmux sessions on completion
        self._cleanup_tmux(run)

        if failed:
            logger.warning("Voronoi %s (#%d) FAILED: %s (%d/%d tasks in %.1fmin)",
                          run.label, run.investigation_id, failure_reason,
                          closed, total_tasks, elapsed)
            self.queue.fail(run.investigation_id, failure_reason)

            # Include log tail in the failure message for diagnostics
            log_tail = ""
            if run.log_path.exists():
                try:
                    raw = run.log_path.read_text(errors="replace")
                    last_lines = raw.strip().splitlines()[-10:]
                    log_tail = "\n".join(last_lines)
                except OSError:
                    pass

            msg = (f"💀 *Voronoi · {run.label}* FAILED\n\n"
                   f"Reason: {failure_reason}\n"
                   f"Tasks: {closed}/{total_tasks} completed in {elapsed:.0f}min")
            if run.retry_count > 0:
                msg += f"\nRetries: {run.retry_count}/{self.config.max_retries}"
            if log_tail:
                msg += f"\n\nLast log:\n```\n{log_tail[-400:]}\n```"
            self.send_message(msg)
            return

        logger.info("Voronoi %s (#%d) complete: %d/%d tasks in %.1fmin",
                    run.label, run.investigation_id, closed, total_tasks, elapsed)
        self.queue.complete(run.investigation_id)

        # Build teaser + report
        from voronoi.gateway.report import ReportGenerator
        rg = ReportGenerator(run.workspace_path, mode=run.mode, rigor=run.rigor)
        teaser = rg.build_teaser(
            run.investigation_id, run.question,
            total_tasks, closed, elapsed,
            mode=run.mode,
            codename=run.codename,
        )
        self.send_message(teaser)

        # Generate PDF/MD and send as document
        report_path = rg.build_pdf()
        if report_path and report_path.exists():
            chat_id = run.chat_id
            if chat_id:
                self.send_document(
                    chat_id, report_path,
                    f"Voronoi · {run.label} — {rg.doc_type.title()}",
                )

        self._try_publish(run)

    def _try_restart(self, run: RunningInvestigation) -> bool:
        """Attempt to restart a dead agent session.

        Returns True if the agent was successfully restarted, False if
        retries are exhausted or the workspace is in an unrecoverable state.
        """
        if run.retry_count >= self.config.max_retries:
            logger.warning("Investigation #%d exhausted %d retries — giving up",
                           run.investigation_id, run.retry_count)
            return False

        run.retry_count += 1

        # Extract the last lines from the agent log for diagnostics
        tail = ""
        if run.log_path.exists():
            try:
                raw = run.log_path.read_text(errors="replace")
                tail = "\n".join(raw.strip().splitlines()[-20:])
            except OSError:
                pass

        logger.info("Restarting investigation #%d (attempt %d/%d)",
                    run.investigation_id, run.retry_count, self.config.max_retries)

        self.send_message(
            f"🔄 *Voronoi · {run.label}* — agent died, restarting "
            f"(attempt {run.retry_count}/{self.config.max_retries})\n\n"
            + (f"Last log:\n```\n{tail[-500:]}\n```" if tail else "No log captured.")
        )

        # Ensure orchestrator prompt still exists
        prompt_file = run.workspace_path / ".swarm" / "orchestrator-prompt.txt"
        if not prompt_file.exists():
            logger.error("Prompt file missing for #%d — cannot restart",
                         run.investigation_id)
            return False

        # Rotate the log file so the new session starts clean
        if run.log_path.exists():
            rotated = run.log_path.with_suffix(f".{run.retry_count}.log")
            try:
                run.log_path.rename(rotated)
            except OSError:
                pass

        try:
            self._launch_in_tmux(run.tmux_session, run.workspace_path)
            run.stall_warned = False
            return True
        except Exception as e:
            logger.error("Failed to restart #%d: %s", run.investigation_id, e)
            return False

    def _cleanup_tmux(self, run: RunningInvestigation) -> None:
        """Kill all tmux sessions associated with this investigation."""
        # Kill the main orchestrator session
        subprocess.run(
            ["tmux", "kill-session", "-t", run.tmux_session],
            capture_output=True,
        )
        # Kill the swarm worker session (convention: <workspace-name>-swarm)
        ws_name = run.workspace_path.name
        for suffix in ["-swarm", "-workers"]:
            subprocess.run(
                ["tmux", "kill-session", "-t", f"{ws_name}{suffix}"],
                capture_output=True,
            )
        logger.info("Cleaned up tmux sessions for %s", run.label)

    def _try_publish(self, run: RunningInvestigation) -> None:
        try:
            from voronoi.server.publisher import GitHubPublisher
            publisher = GitHubPublisher()
            if not publisher.is_gh_available():
                return
            slug = run.workspace_path.name
            ok, url = publisher.publish(str(run.workspace_path), slug)
            if ok:
                self.send_message(f"📦 *Published:* [{slug}]({url})")
        except Exception:
            pass

    def _handle_abort(self) -> None:
        for inv_id, run in list(self.running.items()):
            subprocess.run(
                ["tmux", "kill-session", "-t", run.tmux_session],
                capture_output=True,
            )
            self.queue.fail(inv_id, "Aborted by operator")
            self.send_message(f"🛑 Voronoi · {run.label} aborted")
        self.running.clear()

    def _check_abort_signal(self) -> None:
        """Check if the router wrote an abort signal file and act on it."""
        for run in self.running.values():
            signal_path = run.workspace_path / ".swarm" / "abort-signal"
            if signal_path.exists():
                logger.info("Abort signal detected — aborting all running investigations")
                try:
                    signal_path.unlink()
                except OSError:
                    pass
                self._handle_abort()
                return
        # Also check the global project dir (for investigations without workspaces yet)
        global_signal = self.config.base_dir / ".swarm" / "abort-signal"
        if global_signal.exists():
            logger.info("Global abort signal detected")
            try:
                global_signal.unlink()
            except OSError:
                pass
            self._handle_abort()