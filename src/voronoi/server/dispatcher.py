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
    progress_interval: int = 30  # seconds between progress updates
    timeout_hours: int = 8       # max hours before marking investigation exhausted


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

    @property
    def label(self) -> str:
        return self.codename or f"#{self.investigation_id}"


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

        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(workspace_path)],
            capture_output=True,
        )
        # Launch agent via shell; when it exits the shell exits too,
        # letting poll_progress detect the session is gone.
        subprocess.run(
            ["tmux", "send-keys", "-t", session,
             f'cd "{workspace_path}" && {agent_cmd} {agent_flags} '
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
                score = float(data.get("score", 0.0))
                if score > 0:
                    run.eval_score = score
                    run.improvement_rounds = int(data.get("rounds", run.improvement_rounds))
            except (json.JSONDecodeError, OSError, ValueError):
                pass

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
                msg = f"� *NEW FINDING*\n{title}"
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
        """Attempt to run a convergence check and write convergence.json."""
        try:
            from voronoi.science import check_convergence, write_convergence
            result = check_convergence(
                run.workspace_path, run.rigor,
                eval_score=run.eval_score,
                improvement_rounds=run.improvement_rounds,
            )
            if result.converged or result.status in ("exhausted", "diminishing_returns"):
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
            self.send_message(
                f"💀 *Voronoi · {run.label}* FAILED\n\n"
                f"Reason: {failure_reason}\n"
                f"Tasks: {closed}/{total_tasks} completed in {elapsed:.0f}min"
            )
            return

        logger.info("Voronoi %s (#%d) complete: %d/%d tasks in %.1fmin",
                    run.label, run.investigation_id, closed, total_tasks, elapsed)
        self.queue.complete(run.investigation_id)

        # Build teaser + report
        from voronoi.gateway.report import ReportGenerator
        rg = ReportGenerator(run.workspace_path)
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
            doc_type = "Manuscript" if rg.is_manuscript_format() else "Report"
            # Use the per-investigation chat_id stored at enqueue time
            chat_id = run.chat_id
            if chat_id:
                self.send_document(
                    chat_id, report_path,
                    f"Voronoi · {run.label} — {doc_type}",
                )

        self._try_publish(run)

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