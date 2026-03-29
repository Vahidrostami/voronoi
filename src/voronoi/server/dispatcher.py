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
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from voronoi.gateway.progress import (
    MODE_EMOJI, MODE_VERB,
    MSG_TYPE_MILESTONE, MSG_TYPE_STATUS,
    format_launch, format_complete, format_failure, format_alert,
    format_restart, format_pause, format_duration, phase_description,
    build_digest,
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
    timeout_hours: int = 48      # max hours before marking investigation exhausted
    max_retries: int = 2         # max times to restart a dead agent
    stall_minutes: int = 45      # warn/restart if 0 tasks after this long
    pause_timeout_hours: int = 24  # auto-fail paused investigations after this
    context_advisory_hours: int = 6    # "prioritize convergence" directive
    context_warning_hours: int = 10    # "delegate remaining work" directive
    context_critical_hours: int = 14   # "dispatch Scribe NOW" directive
    compact_interval_hours: int = 6    # workspace state compaction interval


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
    rigor: str = "adaptive"
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
    notified_design_invalid: set = field(default_factory=set)
    last_event_ts: float = 0  # For event log polling
    last_event_ts_by_path: dict[str, float] = field(default_factory=dict)
    last_digest_events: list[dict] = field(default_factory=list)  # For detail retrieval
    last_compact_at: float = 0  # Last workspace compaction timestamp
    context_directive_level: str = ""  # Last directive level sent
    status_message_id: int | None = None  # Telegram message ID for edit-in-place

    @property
    def label(self) -> str:
        return self.codename or f"#{self.investigation_id}"

    @property
    def log_path(self) -> Path:
        return self.workspace_path / ".swarm" / "agent.log"


# Module-level weak reference to the active dispatcher, used by
# handle_resume_investigation in the router to reach the dispatcher's
# resume_investigation() method without circular imports.
_active_dispatcher_ref: Optional["InvestigationDispatcher"] = None


def _active_dispatcher() -> Optional["InvestigationDispatcher"]:
    """Return the active dispatcher instance, or None."""
    return _active_dispatcher_ref


class InvestigationDispatcher:
    """Launches queued investigations and monitors their progress.

    Integrates with the Telegram bridge via two callbacks:
      send_message(text)  — send a chat message
      send_document(chat_id, path, caption)  — send a file
    """

    def __init__(
        self,
        config: DispatcherConfig,
        send_message: Callable[[str], Optional[int]],
        send_document: Callable[[str, Path, str], None] | None = None,
        edit_message: Callable[[str, int], None] | None = None,
    ):
        self.config = config
        self.send_message = send_message
        self.send_document = send_document or (lambda *a: None)
        self.edit_message = edit_message
        self.running: dict[int, RunningInvestigation] = {}
        self._queue = None
        self._workspace_mgr = None

        # Register as the active dispatcher so the router can reach us
        global _active_dispatcher_ref
        _active_dispatcher_ref = self

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

        # Auto-fail paused investigations that exceeded the timeout
        self._check_paused_timeouts()

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
                capture_output=True, timeout=10,
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
                rigor=inv.rigor or "adaptive",
                started_at=inv.started_at or time.time(),
            )

            # Restore task_snapshot from Beads so progress reporting is accurate
            self._restore_task_snapshot(run)

            if not session_alive:
                # Check if a human gate is pending — do NOT crash-retry
                if self._has_pending_human_gate(run):
                    self.running[inv.id] = run
                    logger.info("Recovered gate-paused investigation #%d (%s)",
                                inv.id, inv.codename)
                    continue
                # Check if it finished while we were down
                if self._is_complete(run):
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

        # Patch .swarm-config.json with rigor-mapped effort level
        rigor = getattr(inv, 'rigor', 'scientific') or 'scientific'
        self._patch_swarm_config(workspace_path, rigor)

        prompt = self._build_prompt(inv, workspace_path)
        prompt_file = workspace_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt)

        tmux_session = f"voronoi-inv-{inv.id}"
        rigor = getattr(inv, 'rigor', 'scientific') or 'scientific'
        self._launch_in_tmux(tmux_session, workspace_path, rigor=rigor)

        self.running[inv.id] = RunningInvestigation(
            investigation_id=inv.id,
            workspace_path=workspace_path,
            tmux_session=tmux_session,
            question=inv.question,
            mode=inv.mode,
            codename=inv.codename,
            chat_id=inv.chat_id,
            rigor=getattr(inv, 'rigor', 'scientific') or 'scientific',
        )

        logger.info("Investigation %s (#%d) LIVE in tmux=%s workspace=%s",
                    inv.codename, inv.id, tmux_session, workspace_path)

        label = inv.codename or f"#{inv.id}"
        rigor = getattr(inv, 'rigor', 'scientific') or 'scientific'
        self.send_message(format_launch(
            codename=label,
            mode=inv.mode,
            rigor=rigor,
            question=inv.question,
        ))

    def _build_prompt(self, inv, workspace_path: Path) -> str:
        from voronoi.server.prompt import build_orchestrator_prompt

        rigor = getattr(inv, 'rigor', 'scientific') or 'scientific'
        label = inv.codename or f"#{inv.id}"

        return build_orchestrator_prompt(
            question=inv.question,
            mode=inv.mode,
            rigor=rigor,
            workspace_path=str(workspace_path),
            codename=label,
            max_agents=self.config.max_agents,
        )

    def _patch_swarm_config(self, workspace_path: Path, rigor: str) -> None:
        """Patch .swarm-config.json with rigor-derived effort and role permissions."""
        config_path = workspace_path / ".swarm-config.json"
        try:
            if config_path.exists():
                data = json.loads(config_path.read_text())
            else:
                data = {}
            effort = self._EFFORT_BY_RIGOR.get(rigor, "medium")
            data["effort"] = effort
            data.setdefault("role_permissions", {
                "scout": "--allow-all --deny-tool=write",
                "review_critic": "--allow-all --deny-tool=write",
                "review_stats": "--allow-all --deny-tool=write",
                "review_method": "--allow-all --deny-tool=write",
            })
            if self.config.worker_model:
                data["worker_model"] = self.config.worker_model
            config_path.write_text(json.dumps(data, indent=2))

            # Write .github/mcp-config.json for Copilot CLI MCP auto-discovery
            mcp_config_path = workspace_path / ".github" / "mcp-config.json"
            mcp_config_path.parent.mkdir(parents=True, exist_ok=True)
            mcp_config = {
                "mcpServers": {
                    "voronoi": {
                        "command": sys.executable or shutil.which("python3") or "python3",
                        "args": ["-m", "voronoi.mcp"],
                        "env": {"VORONOI_WORKSPACE": "."},
                    }
                }
            }
            mcp_config_path.write_text(json.dumps(mcp_config, indent=2))
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to patch .swarm-config.json: %s", e)

    def _ensure_copilot_auth(self) -> None:
        """Verify Copilot/GitHub auth is valid before launching an agent.

        Copilot CLI authenticates via an interactive OAuth device flow
        (/login command) which produces tokens that expire.  On a
        long-running server we cannot re-authenticate interactively, so
        this method detects expiry early and raises immediately instead
        of wasting retry attempts on the same expired token.

        Raises RuntimeError if authentication is missing or expired.
        """
        # If an explicit token env var is set, trust it (PATs don't expire mid-session)
        for var in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"):
            if os.environ.get(var):
                logger.debug("Auth: using %s environment variable", var)
                return

        # Check gh CLI auth status (Copilot CLI can piggyback on gh's stored token)
        if shutil.which("gh"):
            result = subprocess.run(
                ["gh", "auth", "status"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                return

        raise RuntimeError(
            "GitHub/Copilot authentication expired. "
            "Re-authenticate on the server with 'copilot' → /login or 'gh auth login', "
            "or set GITHUB_TOKEN / COPILOT_GITHUB_TOKEN env var with a PAT for unattended use."
        )

    # Rigor → Copilot CLI --effort mapping
    _EFFORT_BY_RIGOR: dict[str, str] = {
        "adaptive": "high",
        "scientific": "high",
        "experimental": "xhigh",
    }

    def _launch_in_tmux(self, session: str, workspace_path: Path,
                        prompt_file: Path | None = None,
                        rigor: str = "") -> None:
        agent_cmd = self.config.agent_command
        agent_flags = self.config.agent_flags
        parts = agent_cmd.split()
        if not parts:
            raise RuntimeError(f"agent_command is empty: '{agent_cmd}'")
        agent_bin = parts[0]
        if not shutil.which(agent_bin):
            raise RuntimeError(f"Agent CLI not found: {agent_bin}")
        if agent_bin == "copilot":
            self._ensure_copilot_auth()

        # Orchestrator gets its own model; workers use worker_model via spawn-agent.sh
        model_flag = ""
        if self.config.orchestrator_model:
            model_flag = f" --model {shlex.quote(self.config.orchestrator_model)}"

        # --effort scaled by rigor level
        effort = self._EFFORT_BY_RIGOR.get(rigor, "medium")
        effort_flag = f" --effort {effort}"

        # --share for clean audit trail
        share_path = workspace_path / ".swarm" / "session.md"
        share_flag = f" --share {shlex.quote(str(share_path))}"

        log_path = workspace_path / ".swarm" / "agent.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)

        # Use the provided prompt file, or fall back to the default
        if prompt_file is None:
            prompt_file = workspace_path / ".swarm" / "orchestrator-prompt.txt"

        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session, "-c", str(workspace_path)],
            capture_output=True,
        )
        # Enable tmux pane logging so we can inspect crashes after the fact.
        subprocess.run(
            ["tmux", "pipe-pane", "-t", session,
             f"cat >> {shlex.quote(str(log_path))}"],
            capture_output=True, timeout=10,
        )
        # Launch the agent.  The prompt is read from a file via shell
        # redirection to avoid ARG_MAX / tmux send-keys buffer issues
        # with large prompts.  shlex.quote prevents command injection.
        safe_ws = shlex.quote(str(workspace_path))
        safe_cmd = agent_cmd
        safe_flags = agent_flags
        safe_prompt = shlex.quote(str(prompt_file))

        # Inject auth/state env vars into the tmux shell.
        #
        # tmux set-environment only affects *new* windows/panes, NOT the
        # shell already running in the initial pane created by new-session.
        # This meant env vars like GH_TOKEN never reached the copilot
        # process, causing auth failures on long-running servers.
        #
        # Fix: write vars to a temporary env file inside .swarm/ and
        # source it in the command line.  The file path (not contents)
        # appears in pipe-pane logs, keeping secrets out of logs (INV-31).
        # COPILOT_HOME and GH_HOST matter for long-running servers because
        # restarted tmux sessions must resolve the same stored Copilot state
        # directory and GitHub host as the parent process.
        env_file = workspace_path / ".swarm" / ".tmux-env"
        env_lines: list[str] = []
        for var in (
            "GH_TOKEN",
            "GITHUB_TOKEN",
            "COPILOT_GITHUB_TOKEN",
            "COPILOT_HOME",
            "GH_HOST",
        ):
            val = os.environ.get(var)
            if val:
                env_lines.append(f"export {var}={shlex.quote(val)}")
                # Also set in session env for any future panes/windows
                subprocess.run(
                    ["tmux", "set-environment", "-t", session, var, val],
                    capture_output=True, timeout=10,
                )
        if env_lines:
            env_file.write_text("\n".join(env_lines) + "\n")
            env_file.chmod(0o600)
            source_cmd = f"source {shlex.quote(str(env_file))} && "
        else:
            source_cmd = ""

        subprocess.run(
            ["tmux", "send-keys", "-t", session,
             f'cd {safe_ws} && {source_cmd}{safe_cmd} {safe_flags}{model_flag}'
             f'{effort_flag}{share_flag} '
             f'-p "$(cat {safe_prompt})" ; exit',
             "Enter"],
            capture_output=True, timeout=10,
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

        # Check for pending human gates (Scientific+ rigor)
        self.check_human_gates()

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
                capture_output=True, timeout=10,
            )
            session_alive = result.returncode == 0

            events = self._check_progress(run)
            events.extend(self._check_event_log(run))
            if events:
                logger.info("Investigation #%d: %d events (phase=%s)",
                            inv_id, len(events), run.phase)
                self._send_progress_batch(run, events)

            # Check for timeout (per-investigation override via .swarm/timeout_hours)
            elapsed_hours = (now - run.started_at) / 3600
            effective_timeout = self._effective_timeout(run)
            timed_out = elapsed_hours >= effective_timeout

            # Stall detection: use checkpoint + event log + branches, not just task_snapshot
            if (session_alive and not run.stall_warned
                    and elapsed_hours * 60 >= self.config.stall_minutes):
                if not self._has_workspace_activity(run):
                    run.stall_warned = True
                    logger.warning("Investigation #%d stalled — no activity after %.0fmin",
                                   inv_id, elapsed_hours * 60)
                    self.send_message(format_alert(
                        run.label,
                        f"No tasks created after {int(elapsed_hours * 60)}min. "
                        f"The orchestrator may be stuck. Will auto-restart if the agent exits."
                    ))

            # Criteria progress monitoring: alert if zero criteria met after 4+ hours
            if session_alive and elapsed_hours >= 4.0:
                self._check_criteria_progress(run, elapsed_hours)

            # Context pressure monitoring (Changes 3 + 6)
            if session_alive:
                self._check_context_pressure(run, elapsed_hours)

            # Workspace state compaction (Change 5)
            if session_alive:
                self._maybe_compact_workspace(run)

            if not session_alive or self._is_complete(run) or timed_out:
                if timed_out and not self._is_complete(run):
                    reason = f"timeout ({effective_timeout}h)"
                    logger.warning("Investigation #%d timed out after %.1fh",
                                   inv_id, elapsed_hours)
                    # Kill tmux session if still alive
                    if session_alive:
                        subprocess.run(
                            ["tmux", "kill-session", "-t", run.tmux_session],
                            capture_output=True, timeout=10,
                        )
                    # Write exhaustion convergence
                    self._write_timeout_convergence(run)
                    self._handle_completion(run, failed=True,
                                            failure_reason="Timed out")
                elif not session_alive and not self._is_complete(run):
                    # Check if a human gate is pending — do NOT crash-retry
                    if self._has_pending_human_gate(run):
                        logger.info("Investigation #%d paused at human gate",
                                    inv_id)
                        continue  # don't add to completed_ids
                    # Check for auth failure — pause instead of burning retries
                    log_tail = self._read_log_tail(run)
                    if self._looks_like_auth_failure(log_tail):
                        logger.warning("Investigation #%d paused — auth failure detected",
                                       inv_id)
                        self._pause_investigation(run, "Copilot/GitHub auth expired")
                        continue  # don't add to completed_ids
                    # Classify the exit before deciding to retry
                    is_clean = self._looks_like_clean_agent_exit(log_tail)
                    # Try to restart the agent instead of giving up
                    if self._try_restart(run):
                        reason = "restarted"
                        logger.info("Investigation #%d restarted (attempt %d)",
                                    inv_id, run.retry_count)
                        continue  # don't add to completed_ids
                    reason = self._classify_incomplete_exit(run)
                    logger.warning("Investigation #%d agent exited without completing: %s",
                                   inv_id, reason)
                    self._handle_completion(run, failed=True,
                                            failure_reason=reason)
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

    def _effective_timeout(self, run: RunningInvestigation) -> int:
        """Return the effective timeout for an investigation.

        Checks for a per-investigation override file at
        ``<workspace>/.swarm/timeout_hours``.  The file should contain a
        single integer (the new total timeout in hours).  If the file is
        missing or unreadable, falls back to ``self.config.timeout_hours``.
        """
        override_path = run.workspace_path / ".swarm" / "timeout_hours"
        if override_path.exists():
            try:
                value = int(override_path.read_text().strip())
                if value > 0:
                    return value
            except (ValueError, OSError):
                pass
        return self.config.timeout_hours

    def _write_timeout_convergence(self, run: RunningInvestigation) -> None:
        """Write convergence.json indicating timeout exhaustion."""
        conv_path = run.workspace_path / ".swarm" / "convergence.json"
        conv_path.parent.mkdir(parents=True, exist_ok=True)
        effective = self._effective_timeout(run)
        data = {
            "status": "exhausted",
            "converged": False,
            "reason": f"Timed out after {effective}h",
            "score": run.eval_score,
            "blockers": ["timeout"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        conv_path.write_text(json.dumps(data, indent=2))

    def _restore_task_snapshot(self, run: RunningInvestigation) -> None:
        """Restore task_snapshot from Beads so progress reporting is accurate after recovery."""
        from voronoi.beads import run_bd_json
        code, tasks = run_bd_json("list", "--json", cwd=str(run.workspace_path))
        if code == 0 and isinstance(tasks, list):
            for t in tasks:
                if not isinstance(t, dict):
                    continue
                tid = t.get("id", "")
                run.task_snapshot[tid] = {
                    "status": t.get("status", ""),
                    "title": t.get("title", ""),
                    "notes": t.get("notes", ""),
                }
            logger.info("Restored %d tasks for #%d", len(run.task_snapshot),
                        run.investigation_id)

    def _check_criteria_progress(self, run: RunningInvestigation,
                                  elapsed_hours: float) -> None:
        """Alert if success criteria show zero progress after significant time."""
        sc_path = run.workspace_path / ".swarm" / "success-criteria.json"
        if not sc_path.exists():
            return
        try:
            data = json.loads(sc_path.read_text())
            if not isinstance(data, list) or not data:
                return
            criteria = [c for c in data if isinstance(c, dict)]
            met = sum(1 for c in criteria if c.get("met"))
            total = len(criteria)
            # Alert at 4h if zero met, again at 8h
            if met == 0 and total > 0:
                hours_mark = 4 if elapsed_hours < 6 else 8
                alert_key = f"criteria_zero_{hours_mark}h"
                if not hasattr(run, '_criteria_alerts'):
                    run._criteria_alerts = set()
                if alert_key not in run._criteria_alerts:
                    run._criteria_alerts.add(alert_key)
                    self.send_message(format_alert(
                        run.label,
                        f"0/{total} success criteria met after {int(elapsed_hours)}h. "
                        f"The investigation may need intervention."
                    ))
        except (json.JSONDecodeError, OSError):
            pass

    def _has_pending_human_gate(self, run: RunningInvestigation) -> bool:
        """Check if a human gate is pending (status pending or notified)."""
        gate_path = run.workspace_path / ".swarm" / "human-gate.json"
        if not gate_path.exists():
            return False
        try:
            data = json.loads(gate_path.read_text())
            return isinstance(data, dict) and data.get("status") in ("pending", "notified")
        except (json.JSONDecodeError, OSError):
            return False

    # ------------------------------------------------------------------
    # Context pressure, stall detection, and workspace compaction
    # ------------------------------------------------------------------

    def _has_workspace_activity(self, run: RunningInvestigation) -> bool:
        """Check if the workspace shows signs of orchestrator activity.

        Uses checkpoint, event log, and git branches instead of relying
        solely on ``bd list --json`` (which may fail if bd is not on the
        dispatcher's PATH).
        """
        swarm = run.workspace_path / ".swarm"

        # Check checkpoint — if cycle > 0, orchestrator wrote state
        cp_path = swarm / "orchestrator-checkpoint.json"
        if cp_path.exists():
            try:
                cp = json.loads(cp_path.read_text())
                if isinstance(cp, dict) and (cp.get("cycle", 0) > 0
                                             or cp.get("total_tasks", 0) > 0):
                    return True
            except (json.JSONDecodeError, OSError):
                pass

        # Check experiments.tsv — if rows exist, experiments are running
        tsv = swarm / "experiments.tsv"
        if tsv.exists():
            try:
                lines = tsv.read_text().strip().splitlines()
                if len(lines) > 1:  # more than just header
                    return True
            except OSError:
                pass

        # Check event log
        events_file = swarm / "events.jsonl"
        if events_file.exists():
            try:
                if events_file.stat().st_size > 0:
                    return True
            except OSError:
                pass

        # Check git branches — if agent-* branches exist, workers were spawned
        try:
            result = subprocess.run(
                ["git", "branch", "--list", "agent-*"],
                capture_output=True, text=True, timeout=10,
                cwd=str(run.workspace_path),
            )
            if result.returncode == 0 and result.stdout.strip():
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        # Fall back to task_snapshot (bd may have worked)
        if run.task_snapshot:
            return True

        return False

    def _write_directive(self, run: RunningInvestigation,
                         level: str, message: str) -> None:
        """Write a dispatcher directive file for the orchestrator to poll."""
        directive_path = run.workspace_path / ".swarm" / "dispatcher-directive.json"
        directive_path.parent.mkdir(parents=True, exist_ok=True)
        elapsed_hours = (time.time() - run.started_at) / 3600
        data = {
            "directive": level,
            "hours_elapsed": round(elapsed_hours, 1),
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            directive_path.write_text(json.dumps(data, indent=2))
            logger.info("Wrote %s directive for %s", level, run.label)
        except OSError as e:
            logger.warning("Failed to write directive for %s: %s", run.label, e)

    def _check_context_pressure(self, run: RunningInvestigation,
                                elapsed_hours: float) -> None:
        """Check time-based and self-reported context pressure."""
        # Time-based thresholds (escalating)
        if (elapsed_hours >= self.config.context_critical_hours
                and run.context_directive_level != "context_critical"):
            run.context_directive_level = "context_critical"
            self._write_directive(run, "context_critical",
                f"{int(elapsed_hours)}h elapsed. Run /compact NOW to recover context budget, "
                f"write checkpoint, and dispatch Scribe immediately or risk session loss.")
            self.send_message(format_alert(
                run.label,
                f"Context critical — {int(elapsed_hours)}h elapsed. "
                f"Directive sent to dispatch Scribe immediately."
            ))
        elif (elapsed_hours >= self.config.context_warning_hours
              and run.context_directive_level not in ("context_warning", "context_critical")):
            run.context_directive_level = "context_warning"
            self._write_directive(run, "context_warning",
                f"{int(elapsed_hours)}h elapsed. Run /compact NOW to recover context budget, "
                f"then delegate ALL remaining work to fresh agents.")
            self.send_message(format_alert(
                run.label,
                f"Context warning — {int(elapsed_hours)}h elapsed. "
                f"Directive sent to delegate remaining work."
            ))
        elif (elapsed_hours >= self.config.context_advisory_hours
              and not run.context_directive_level):
            run.context_directive_level = "context_advisory"
            self._write_directive(run, "context_advisory",
                f"{int(elapsed_hours)}h elapsed. Prioritize convergence.")

        # Self-reported context pressure from checkpoint (Change 6)
        self._check_token_budget(run)

    def _check_token_budget(self, run: RunningInvestigation) -> None:
        """Read checkpoint and enforce self-reported context pressure."""
        cp_path = run.workspace_path / ".swarm" / "orchestrator-checkpoint.json"
        if not cp_path.exists():
            return
        try:
            cp = json.loads(cp_path.read_text())
            if not isinstance(cp, dict):
                return
            remaining = cp.get("context_window_remaining_pct", 0)
            if not remaining or remaining <= 0:
                return  # orchestrator didn't report

            if (remaining <= 0.15
                    and run.context_directive_level != "context_critical"):
                run.context_directive_level = "context_critical"
                self._write_directive(run, "context_critical",
                    "Context window nearly exhausted (self-reported). "
                    "Run /compact NOW, dispatch Scribe, and write checkpoint.")
                self.send_message(format_alert(
                    run.label,
                    f"Context critical — orchestrator reports {remaining:.0%} "
                    f"window remaining. Directive sent."
                ))
            elif (remaining <= 0.30
                  and run.context_directive_level not in ("context_warning", "context_critical")):
                run.context_directive_level = "context_warning"
                self._write_directive(run, "context_warning",
                    "Context window below 30% (self-reported). "
                    "Run /compact NOW, then delegate remaining work to fresh agents.")
        except (json.JSONDecodeError, OSError):
            pass

    def _maybe_compact_workspace(self, run: RunningInvestigation) -> None:
        """Periodically compact workspace state files."""
        now = time.time()
        interval = self.config.compact_interval_hours * 3600
        if now - run.last_compact_at < interval:
            return
        run.last_compact_at = now
        try:
            from voronoi.server.compact import compact_workspace_state
            if compact_workspace_state(run.workspace_path):
                logger.info("Compacted workspace state for %s", run.label)
        except Exception as e:
            logger.debug("Workspace compaction failed for %s: %s", run.label, e)

    def _check_progress(self, run: RunningInvestigation) -> list[dict]:
        events: list[dict] = []
        tasks: list[dict] | None = None
        from voronoi.beads import run_bd_json
        code, parsed = run_bd_json("list", "--json", cwd=str(run.workspace_path))
        if code == 0 and parsed is not None:
            if isinstance(parsed, list):
                tasks = parsed
                events.extend(self._diff_tasks(run, tasks))
            else:
                logger.warning("bd list --json returned non-list for #%d: %s",
                               run.investigation_id, type(parsed).__name__)
        elif code != 0:
            logger.debug("bd list --json failed for #%d (exit=%d)",
                         run.investigation_id, code)
        events.extend(self._check_findings(run, tasks))
        events.extend(self._check_design_invalid(run, tasks))
        events.extend(self._detect_phase(run))

        # Sync findings to cross-run Claim Ledger
        if tasks:
            try:
                self._sync_findings_to_ledger(run, tasks)
            except Exception as e:
                logger.debug("Claim ledger sync failed for #%d: %s",
                             run.investigation_id, e)

        return events

    def _diff_tasks(self, run: RunningInvestigation, tasks: list[dict]) -> list[dict]:
        events: list[dict] = []
        current: dict = {}
        for t in tasks:
            tid = t.get("id", "")
            status = t.get("status", "")
            title = t.get("title", "")
            notes = t.get("notes", "")
            current[tid] = {"status": status, "title": title, "notes": notes}

            old = run.task_snapshot.get(tid)
            if old is None and run.task_snapshot:
                events.append({"type": "task_new", "msg": f"📋 Queued: *{title}*"})
            elif old and old["status"] != status:
                if status == "closed":
                    events.append({"type": "task_done", "msg": f"✅ Wrapped up: *{title}*"})
                elif status == "in_progress" and old["status"] != "in_progress":
                    events.append({"type": "task_started", "msg": f"⚡ Picked up: *{title}*"})

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
            from voronoi.beads import run_bd_json
            code, parsed = run_bd_json("list", "--json", cwd=str(run.workspace_path))
            if code != 0 or not isinstance(parsed, list):
                return events
            tasks = parsed

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
                msg = f"🔬 *NEW FINDING*\n{title}"
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
                    and tid not in run.notified_design_invalid):
                run.notified_design_invalid.add(tid)
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
        checkpoint = self._latest_checkpoint(run)

        if checkpoint:
            phase = checkpoint.get("phase", "")
            if isinstance(phase, str) and phase:
                run.phase = phase
            try:
                score = float(checkpoint.get("eval_score", 0.0))
                if 0.0 <= score <= 1.0:
                    run.eval_score = max(run.eval_score, score)
            except (TypeError, ValueError):
                pass
            try:
                run.improvement_rounds = max(
                    run.improvement_rounds,
                    int(checkpoint.get("improvement_rounds", 0)),
                )
            except (TypeError, ValueError):
                pass

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
            phase_msg = phase_description(run.mode, run.phase)
            events.append({"type": "phase", "msg": phase_msg})

        # Check for paradigm stress (Scientific+ only)
        if run.rigor in ("scientific", "experimental") and not run.notified_paradigm_stress:
            events.extend(self._check_paradigm_stress(run))

        return events

    def _latest_checkpoint(self, run: RunningInvestigation) -> dict | None:
        """Return the newest orchestrator checkpoint from the workspace or worktrees."""
        candidates = [run.workspace_path / ".swarm" / "orchestrator-checkpoint.json"]
        swarm_dir = self._swarm_dir(run.workspace_path)
        if swarm_dir:
            candidates.extend(
                path / ".swarm" / "orchestrator-checkpoint.json"
                for path in sorted(swarm_dir.glob("agent-*"))
                if path.is_dir()
            )

        latest: dict | None = None
        latest_ts = float("-inf")
        for path in candidates:
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, dict):
                continue

            ts = path.stat().st_mtime
            last_updated = data.get("last_updated", "")
            if isinstance(last_updated, str) and last_updated:
                try:
                    ts = datetime.fromisoformat(last_updated).timestamp()
                except ValueError:
                    pass
            if ts > latest_ts:
                latest = data
                latest_ts = ts
        return latest

    def _swarm_dir(self, workspace_path: Path) -> Path | None:
        config_path = workspace_path / ".swarm-config.json"
        if config_path.exists():
            try:
                data = json.loads(config_path.read_text())
            except (json.JSONDecodeError, OSError):
                data = None
            if isinstance(data, dict):
                swarm_dir = data.get("swarm_dir")
                if isinstance(swarm_dir, str) and swarm_dir:
                    path = Path(swarm_dir)
                    if path.exists():
                        return path
        fallback = workspace_path.parent / f"{workspace_path.name}-swarm"
        return fallback if fallback.exists() else None

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
                    "msg": f"⚠️ *Paradigm stress* — {result.contradiction_count} "
                           f"contradictions found. The working model might need a rethink.",
                })
        except Exception as e:
            logger.debug("Paradigm stress check failed: %s", e)
        return events

    def _check_heartbeat_stalls(self, run: RunningInvestigation) -> list[dict]:
        """Check agent heartbeats for stalled workers.

        This helper is kept for environments that emit heartbeat files, but it
        is not part of the default dispatcher polling path because the current
        runtime does not write them consistently.
        """
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

    def _check_event_log(self, run: RunningInvestigation) -> list[dict]:
        """Check the structured event log for notable activity."""
        events: list[dict] = []
        try:
            from voronoi.server.events import summarize_events
            total_count = 0
            total_tokens = 0
            total_failures = 0
            latest_ts = run.last_event_ts

            roots = [run.workspace_path]
            swarm_dir = self._swarm_dir(run.workspace_path)
            if swarm_dir:
                roots.extend(
                    path for path in sorted(swarm_dir.glob("agent-*"))
                    if path.is_dir()
                )

            for root in roots:
                key = str(root.resolve())
                since = run.last_event_ts_by_path.get(key, run.last_event_ts)
                summary = summarize_events(root, since=since)
                if summary["count"] == 0:
                    continue
                total_count += summary["count"]
                total_tokens += summary["total_tokens"]
                total_failures += summary["failures"]
                latest_ts = max(latest_ts, summary["last_event_ts"])
                run.last_event_ts_by_path[key] = summary["last_event_ts"]

            if total_count == 0:
                return events
            run.last_event_ts = latest_ts

            # Report failures
            if total_failures > 0:
                events.append({
                    "type": "event_log",
                    "msg": f"📝 {total_count} events since last poll "
                           f"({total_failures} failures, "
                           f"{total_tokens:,} tokens)",
                })
            # Log token accumulation periodically (every 50K tokens)
            elif total_tokens > 50000:
                events.append({
                    "type": "event_log",
                    "msg": f"📝 {total_count} events, "
                           f"{total_tokens:,} tokens since last poll",
                })
        except Exception as e:
            logger.debug("Event log check failed: %s", e)
        return events

    def _send_progress_batch(self, run: RunningInvestigation, events: list[dict]) -> None:
        run.last_digest_events = events  # store for detail retrieval
        msg, msg_type = build_digest(
            codename=run.label,
            mode=run.mode,
            phase=run.phase,
            elapsed_sec=time.time() - run.started_at,
            task_snapshot=run.task_snapshot,
            workspace=run.workspace_path,
            events_since_last=events,
            eval_score=run.eval_score,
            compact=True,
        )
        if msg_type == MSG_TYPE_MILESTONE:
            # Milestone: finding, design_invalid — send new message (triggers notification)
            run.status_message_id = None  # next status will be a fresh message
            self.send_message(msg)
        elif self.edit_message and run.status_message_id is not None:
            # Status update: edit existing message (silent, no notification)
            self.edit_message(msg, run.status_message_id)
        else:
            # First status or no edit support: send new message, capture ID
            msg_id = self.send_message(msg)
            if msg_id is not None:
                run.status_message_id = msg_id

    def get_detail(self, inv_id: int | None = None) -> str:
        """Return a detailed (non-compact) digest for a running investigation."""
        if inv_id is not None:
            run = self.running.get(inv_id)
        elif self.running:
            run = next(iter(self.running.values()))
        else:
            return "No investigation is running right now."
        if run is None:
            return f"Investigation #{inv_id} is not currently running."
        text, _ = build_digest(
            codename=run.label,
            mode=run.mode,
            phase=run.phase,
            elapsed_sec=time.time() - run.started_at,
            task_snapshot=run.task_snapshot,
            workspace=run.workspace_path,
            events_since_last=run.last_digest_events,
            eval_score=run.eval_score,
            compact=False,
        )
        return text

    def _has_open_design_invalid(self, run: RunningInvestigation) -> bool:
        """Check if any open tasks have DESIGN_INVALID flag.

        Uses the cached task_snapshot from the last progress poll to avoid
        extra subprocess calls.
        """
        for t in run.task_snapshot.values():
            if t["status"] != "closed" and "DESIGN_INVALID" in t.get("notes", ""):
                return True
        return False

    def _is_complete(self, run: RunningInvestigation) -> bool:
        # HARD GATE: never complete while DESIGN_INVALID tasks are open
        if self._has_open_design_invalid(run):
            return False

        if (run.workspace_path / ".swarm" / "deliverable.md").exists():
            # For standard rigor, deliverable is sufficient
            if run.rigor == "adaptive":
                return True
            # For higher rigor, also need convergence signal
            conv = run.workspace_path / ".swarm" / "convergence.json"
            if conv.exists():
                try:
                    data = json.loads(conv.read_text())
                    if isinstance(data, dict):
                        return data.get("converged", False) or \
                            data.get("status") in ("converged", "exhausted", "diminishing_returns", "negative_result")
                except (json.JSONDecodeError, OSError):
                    pass
            # Deliverable exists but no convergence signal — attempt to
            # generate one and re-check immediately (so we don't need to
            # wait for the next poll cycle, which may never come if the
            # agent already exited normally).
            self._try_convergence_check(run)
            if conv.exists():
                try:
                    data = json.loads(conv.read_text())
                    if isinstance(data, dict):
                        return data.get("converged", False) or \
                            data.get("status") in ("converged", "exhausted", "diminishing_returns", "negative_result")
                except (json.JSONDecodeError, OSError):
                    pass
            return False
        conv = run.workspace_path / ".swarm" / "convergence.json"
        if conv.exists():
            try:
                data = json.loads(conv.read_text())
                if isinstance(data, dict):
                    return data.get("status") in ("converged", "exhausted", "diminishing_returns", "negative_result")
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
            if result.converged or result.status in ("exhausted", "diminishing_returns", "negative_result"):
                # Run convergence-gate.sh for additional validation
                gate_script = run.workspace_path / "scripts" / "convergence-gate.sh"
                if not gate_script.exists():
                    # Try package data directory
                    gate_script = Path(__file__).resolve().parent.parent / "data" / "scripts" / "convergence-gate.sh"
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
        # HARD GATE: refuse to declare success while DESIGN_INVALID is open
        if not failed and self._has_open_design_invalid(run):
            logger.warning("Completion blocked for %s: DESIGN_INVALID tasks still open",
                           run.label)
            self.send_message(format_alert(
                run.label,
                "Completion blocked — experiments flagged as DESIGN_INVALID are still open. "
                "Fix the design and re-run."
            ))
            return

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

            msg = format_failure(
                codename=run.label,
                reason=failure_reason,
                elapsed_sec=time.time() - run.started_at,
                closed=closed,
                total=total_tasks,
                log_tail=log_tail,
                retry_count=run.retry_count,
                max_retries=self.config.max_retries,
            )
            self.send_message(msg)
            return

        logger.info("Voronoi %s (#%d) complete: %d/%d tasks in %.1fmin",
                    run.label, run.investigation_id, closed, total_tasks, elapsed)

        # Science investigations go to review for PI feedback;
        # build-mode investigations complete immediately.
        is_science = run.mode in ("discover", "prove")
        if is_science:
            self._transition_to_review(run)
        else:
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

    def _read_log_tail(self, run: RunningInvestigation, *, lines: int = 20) -> str:
        """Return the last N log lines for diagnostics."""
        if not run.log_path.exists():
            return ""
        try:
            raw = run.log_path.read_text(errors="replace")
        except OSError:
            return ""
        return "\n".join(raw.strip().splitlines()[-lines:])

    def _normalize_log_tail(self, log_tail: str) -> str:
        """Normalize tmux/copilot log output for heuristic matching."""
        if not log_tail:
            return ""

        normalized = log_tail.lower().replace("\r", "\n")
        normalized = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", " ", normalized)
        normalized = re.sub(r"\x1b\][^\x07]*(?:\x07|\x1b\\)", " ", normalized)
        normalized = re.sub(r"\[\?[0-9;]*[a-z]", " ", normalized)
        normalized = re.sub(r"\[<[^\s]+", " ", normalized)
        normalized = "".join(
            ch if ch.isprintable() or ch.isspace() else " "
            for ch in normalized
        )
        normalized = re.sub(r"[^a-z0-9/_:+.-]+", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        return normalized.strip()

    def _looks_like_clean_agent_exit(self, log_tail: str) -> bool:
        """Heuristically detect a normal Copilot CLI shutdown."""
        lowered = self._normalize_log_tail(log_tail)
        if not lowered:
            return False
        markers = (
            "logout",
            "total session time",
            "total usage est",
            "breakdown by ai model",
        )
        return sum(marker in lowered for marker in markers) >= 2

    def _looks_like_auth_failure(self, log_tail: str) -> bool:
        """Detect auth-related failures in agent log output."""
        lowered = self._normalize_log_tail(log_tail)
        if not lowered:
            return False
        auth_markers = (
            "authenticate",
            "copilot login",
            "gh auth login",
            "copilot_github_token",
            "gh_token",
            "github_token",
            "oauth token",
            "fine-grained personal access token",
            "authentication required",
            "credentials",
            "/login",
        )
        return sum(marker in lowered for marker in auth_markers) >= 2

    def _classify_incomplete_exit(self, run: RunningInvestigation) -> str:
        """Describe why a dead agent session is incomplete."""
        log_tail = self._read_log_tail(run)
        if not self._looks_like_clean_agent_exit(log_tail):
            return "Agent exited unexpectedly"

        blockers: list[str] = []
        deliverable = run.workspace_path / ".swarm" / "deliverable.md"
        if not deliverable.exists():
            blockers.append("no deliverable produced")

        try:
            from voronoi.science import check_convergence

            result = check_convergence(
                run.workspace_path,
                run.rigor,
                eval_score=run.eval_score,
                improvement_rounds=run.improvement_rounds,
            )
            if result.reason:
                blockers.append(result.reason)
        except Exception as e:
            logger.debug("Failed to classify incomplete exit for %s: %s",
                         run.label, e)

        unique_blockers: list[str] = []
        seen: set[str] = set()
        for blocker in blockers:
            normalized = blocker.strip().rstrip(".")
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            unique_blockers.append(normalized)

        if unique_blockers:
            return "Agent exited cleanly before convergence: " + "; ".join(unique_blockers)
        return "Agent exited cleanly before completion"

    def _try_restart(self, run: RunningInvestigation) -> bool:
        """Attempt to restart a dead agent session.

        Returns True if the agent was successfully restarted, False if
        retries are exhausted or the workspace is in an unrecoverable state.

        On restart, writes a NEW minimal resume prompt instead of appending
        to the original (which would keep growing with each restart).
        """
        if run.retry_count >= self.config.max_retries:
            logger.warning("Investigation #%d exhausted %d retries — giving up",
                           run.investigation_id, run.retry_count)
            return False

        run.retry_count += 1

        # Extract the last lines from the agent log for diagnostics
        tail = self._read_log_tail(run)
        is_clean = self._looks_like_clean_agent_exit(tail)

        logger.info("Restarting investigation #%d (attempt %d/%d)",
                    run.investigation_id, run.retry_count, self.config.max_retries)

        self.send_message(format_restart(
            run.label,
            attempt=run.retry_count,
            max_retries=self.config.max_retries,
            log_tail=tail,
            clean_exit=is_clean,
        ))

        # Ensure original orchestrator prompt exists (needed as reference)
        prompt_file = run.workspace_path / ".swarm" / "orchestrator-prompt.txt"
        if not prompt_file.exists():
            logger.error("Prompt file missing for #%d — cannot restart",
                         run.investigation_id)
            return False

        # Write a NEW minimal resume prompt (don't append to the old one)
        resume_file = self._build_resume_prompt(run)

        # Rotate the log file so the new session starts clean
        if run.log_path.exists():
            rotated = run.log_path.with_suffix(f".{run.retry_count}.log")
            try:
                run.log_path.rename(rotated)
            except OSError:
                pass

        try:
            self._launch_in_tmux(run.tmux_session, run.workspace_path,
                                 prompt_file=resume_file, rigor=run.rigor)
            run.stall_warned = False
            run.context_directive_level = ""
            return True
        except RuntimeError as e:
            if "authentication" in str(e).lower():
                logger.error("Auth expired for #%d — pausing: %s",
                             run.investigation_id, e)
                # Don't burn retries — pause so operator can fix and /resume
                run.retry_count -= 1  # undo the increment at top of method
                self._pause_investigation(run, "Copilot/GitHub auth expired")
            else:
                logger.error("Failed to restart #%d: %s", run.investigation_id, e)
            return False
        except Exception as e:
            logger.error("Failed to restart #%d: %s", run.investigation_id, e)
            return False

    # ------------------------------------------------------------------
    # Pause / Resume
    # ------------------------------------------------------------------

    def _pause_investigation(self, run: RunningInvestigation, reason: str) -> None:
        """Pause a running investigation due to a recoverable error.

        Transitions the queue status to 'paused', cleans up tmux,
        removes from self.running, and notifies via Telegram.
        """
        self._cleanup_tmux(run)
        self.queue.pause(run.investigation_id, reason)

        total_tasks = len(run.task_snapshot)
        closed = sum(1 for t in run.task_snapshot.values() if t["status"] == "closed")
        elapsed_sec = time.time() - run.started_at

        self.send_message(format_pause(
            codename=run.label,
            reason=reason,
            elapsed_sec=elapsed_sec,
            closed=closed,
            total=total_tasks,
        ))

        # Remove from running so poll_progress skips it
        self.running.pop(run.investigation_id, None)
        logger.info("Investigation #%d (%s) paused: %s",
                     run.investigation_id, run.label, reason)

    def resume_investigation(self, investigation_id: int) -> str:
        """Resume a paused or failed investigation.

        Validates workspace, rebuilds resume prompt, relaunches agent.
        Returns a status message for the user.
        """
        inv = self.queue.get(investigation_id)
        if inv is None:
            return f"❌ Investigation #{investigation_id} not found."
        if inv.status not in ("paused", "failed"):
            return f"❌ Investigation #{investigation_id} is {inv.status} — can only resume paused or failed."

        if not inv.workspace_path or not Path(inv.workspace_path).exists():
            return f"❌ Workspace for #{investigation_id} no longer exists."

        workspace_path = Path(inv.workspace_path)
        prompt_file = workspace_path / ".swarm" / "orchestrator-prompt.txt"
        if not prompt_file.exists():
            return f"❌ Orchestrator prompt missing for #{investigation_id} — cannot resume."

        # Transition queue status
        if not self.queue.resume(investigation_id):
            return f"❌ Failed to resume #{investigation_id} — status may have changed."

        # Build tracker
        tmux_session = f"voronoi-inv-{inv.id}"
        run = RunningInvestigation(
            investigation_id=inv.id,
            workspace_path=workspace_path,
            tmux_session=tmux_session,
            question=inv.question,
            mode=inv.mode,
            codename=inv.codename,
            chat_id=inv.chat_id,
            rigor=inv.rigor or "adaptive",
            started_at=time.time(),
            retry_count=0,
        )

        # Restore task snapshot for accurate progress
        self._restore_task_snapshot(run)

        # Build resume prompt and launch
        resume_file = self._build_resume_prompt(run)
        try:
            self._launch_in_tmux(run.tmux_session, run.workspace_path,
                                 prompt_file=resume_file, rigor=run.rigor)
        except Exception as e:
            logger.error("Failed to resume #%d: %s", inv.id, e)
            self.queue.fail(inv.id, f"Resume launch failed: {e}")
            return f"❌ Failed to launch #{investigation_id}: {e}"

        self.running[inv.id] = run
        label = inv.codename or f"#{inv.id}"
        self.send_message(f"▶️ *{label}* resumed — agent relaunched.")
        logger.info("Investigation #%d (%s) resumed", inv.id, label)
        return f"▶️ *{label}* resumed."

    def _check_paused_timeouts(self) -> None:
        """Auto-fail paused investigations that exceeded pause_timeout_hours."""
        try:
            paused = self.queue.get_paused()
        except Exception:
            return
        for inv in paused:
            if not inv.started_at:
                continue
            paused_hours = (time.time() - inv.started_at) / 3600
            if paused_hours >= self.config.pause_timeout_hours:
                logger.warning("Paused investigation #%d timed out after %.1fh",
                               inv.id, paused_hours)
                # Transition paused → running → failed (resume clears error first)
                self.queue.resume(inv.id)
                self.queue.fail(inv.id,
                                f"Paused for {int(paused_hours)}h without resume — auto-failed")
                label = inv.codename or f"#{inv.id}"
                self.send_message(format_alert(
                    label,
                    f"Was paused for {int(paused_hours)}h with no /resume — auto-failed."
                ))

    def _build_resume_prompt(self, run: RunningInvestigation) -> Path:
        """Build a resume prompt for a restarted session.

        Includes the original question, essential protocol references,
        checkpoint state, remaining tasks, and clear next actions.
        The restarted agent starts with a clean context window.
        """
        lines: list[str] = [
            "You are the Voronoi swarm orchestrator. This is a RESTART "
            f"(attempt {run.retry_count}/{self.config.max_retries}).\n",
            f"**Codename:** {run.label}",
            f"**Mode:** {run.mode} | **Rigor:** {run.rigor}\n",
        ]

        # Include the original investigation question
        lines.append("## Investigation Question\n")
        lines.append(run.question[:2000])
        lines.append("")

        # Essential protocol reference
        lines.append("## Your Full Protocol\n")
        lines.append(
            "Read `.github/agents/swarm-orchestrator.agent.md` NOW — it contains your "
            "complete role definition including OODA workflow, role selection tables, "
            "convergence criteria, and the macro retry loop. Follow it precisely.\n"
        )

        lines.append("## Critical Rules for This Restart\n")
        lines.append(
            "- All previous experimental work is preserved in the workspace.\n"
            "- Do NOT re-run experiments that already produced results.\n"
            "- Read `.swarm/brief-digest.md` instead of re-reading full PROMPT.md.\n"
            "- Work from the checkpoint and state digest below.\n"
            "- Poll `.swarm/dispatcher-directive.json` each OODA cycle.\n"
            "- ALWAYS delegate manuscript writing to a Scribe worker.\n"
            "- Use `bd query` for targeted task lookups, never `bd list --json`.\n"
            "- Dispatch workers via `./scripts/spawn-agent.sh`.\n"
            "- Merge completed work via `./scripts/merge-agent.sh`.\n"
            "- Before convergence, run: `./scripts/convergence-gate.sh . " + run.rigor + "`\n"
        )

        # Human gate status
        gate_path = run.workspace_path / ".swarm" / "human-gate.json"
        if gate_path.exists():
            try:
                gate_data = json.loads(gate_path.read_text())
                if isinstance(gate_data, dict):
                    gate_status = gate_data.get("status", "")
                    gate_feedback = gate_data.get("feedback", "")
                    lines.append(f"## Human Gate Status: {gate_status}\n")
                    if gate_feedback:
                        lines.append(f"Feedback: {gate_feedback}\n")
            except (json.JSONDecodeError, OSError):
                pass

        # Checkpoint summary
        cp_path = run.workspace_path / ".swarm" / "orchestrator-checkpoint.json"
        if cp_path.exists():
            try:
                from voronoi.science.convergence import (
                    load_checkpoint, format_checkpoint_for_prompt,
                )
                cp = load_checkpoint(run.workspace_path)
                lines.append("## Last Checkpoint\n")
                lines.append(format_checkpoint_for_prompt(cp))
                lines.append("")
            except Exception:
                pass

        # Brief digest (if compaction has run)
        digest_path = run.workspace_path / ".swarm" / "state-digest.md"
        if digest_path.exists():
            try:
                lines.append("## State Digest\n")
                lines.append(digest_path.read_text().strip())
                lines.append("")
            except OSError:
                pass

        # Success criteria status
        sc_path = run.workspace_path / ".swarm" / "success-criteria.json"
        if sc_path.exists():
            try:
                criteria = json.loads(sc_path.read_text())
                if isinstance(criteria, list) and criteria:
                    dicts = [c for c in criteria if isinstance(c, dict)]
                    met = sum(1 for c in dicts if c.get("met"))
                    lines.append(f"## Success Criteria: {met}/{len(dicts)} met\n")
                    for c in dicts:
                        status = "✅" if c.get("met") else "❌"
                        lines.append(f"- {status} {c.get('id', '?')}: {c.get('description', '')}")
                    lines.append("")
            except (json.JSONDecodeError, OSError):
                pass

        # Task summary from snapshot
        if run.task_snapshot:
            total = len(run.task_snapshot)
            closed = sum(1 for t in run.task_snapshot.values() if t["status"] == "closed")
            open_tasks = [t["title"] for t in run.task_snapshot.values() if t["status"] != "closed"]
            lines.append(f"## Tasks: {closed}/{total} complete\n")
            if open_tasks:
                lines.append("**Remaining:**")
                for title in open_tasks[:10]:
                    lines.append(f"- {title}")
            lines.append("")

        # Eval score
        if run.eval_score > 0:
            lines.append(f"## Quality Score: {run.eval_score:.2f}\n")

        # Brief digest (if written by orchestrator at startup)
        brief_path = run.workspace_path / ".swarm" / "brief-digest.md"
        if brief_path.exists():
            try:
                lines.append("## Project Brief Digest\n")
                lines.append(brief_path.read_text().strip())
                lines.append("")
            except OSError:
                pass

        # Directive
        lines.append("## What To Do Now\n")
        lines.append(
            "1. Read `.swarm/orchestrator-checkpoint.json` for full state\n"
            "2. Run `bd ready --json` to see remaining tasks\n"
            "3. If all experiments are done, **dispatch a Scribe worker** for the manuscript\n"
            "4. If `.swarm/brief-digest.md` exists, read it for critical constraints\n"
            "5. **Conserve context** — delegate writing to workers, keep your session lean\n"
        )

        resume_file = run.workspace_path / ".swarm" / "orchestrator-prompt-resume.txt"
        resume_file.write_text("\n".join(lines))
        logger.info("Wrote minimal resume prompt for #%d (%d lines)",
                    run.investigation_id, len(lines))
        return resume_file

    def _cleanup_tmux(self, run: RunningInvestigation) -> None:
        """Kill all tmux sessions associated with this investigation."""
        # Kill the main orchestrator session
        subprocess.run(
            ["tmux", "kill-session", "-t", run.tmux_session],
            capture_output=True, timeout=10,
        )
        # Kill the swarm worker session (convention: <workspace-name>-swarm)
        ws_name = run.workspace_path.name
        for suffix in ["-swarm", "-workers"]:
            subprocess.run(
                ["tmux", "kill-session", "-t", f"{ws_name}{suffix}"],
                capture_output=True, timeout=10,
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
            logger.debug("Failed to publish %s", run.label, exc_info=True)

    def _handle_abort(self) -> None:
        for inv_id, run in list(self.running.items()):
            subprocess.run(
                ["tmux", "kill-session", "-t", run.tmux_session],
                capture_output=True, timeout=10,
            )
            self.queue.fail(inv_id, "Aborted by operator")
            self.send_message(f"*{run.label}* aborted.")
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

    # ------------------------------------------------------------------
    # Human gate — pause for human approval at key decision points
    # ------------------------------------------------------------------

    def check_human_gates(self) -> None:
        """Check for pending human gates across running investigations.

        For Scientific+ rigor, the orchestrator writes a
        ``.swarm/human-gate.json`` file at key decision points:
        - After pre-registration (before running experiments)
        - Before convergence (before finalizing deliverable)

        The dispatcher detects these files, pauses the investigation
        (kills the tmux session), and sends a Telegram message asking
        the human to ``/approve <id>`` or ``/revise <id> <feedback>``.
        """
        for run in self.running.values():
            if run.rigor not in ("scientific", "experimental"):
                continue
            gate_path = run.workspace_path / ".swarm" / "human-gate.json"
            if not gate_path.exists():
                continue
            try:
                data = json.loads(gate_path.read_text())
                if not isinstance(data, dict):
                    continue
                if data.get("status") == "approved":
                    continue  # Already approved, orchestrator should resume
                if data.get("status") == "pending":
                    gate_type = data.get("gate", "unknown")
                    summary = data.get("summary", "")
                    logger.info("Human gate '%s' pending for %s",
                                gate_type, run.label)
                    self.send_message(
                        f"⏸️ *{run.label} — Human Review Required*\n\n"
                        f"Gate: *{gate_type}*\n"
                        f"{summary}\n\n"
                        f"Reply `/approve {run.investigation_id}` to proceed\n"
                        f"Reply `/revise {run.investigation_id} <feedback>` to request changes"
                    )
                    # Kill tmux to truly pause execution (INV-32)
                    subprocess.run(
                        ["tmux", "kill-session", "-t", run.tmux_session],
                        capture_output=True, timeout=10,
                    )
                    logger.info("Paused investigation %s at human gate '%s'",
                                run.label, gate_type)
                    # Mark as notified so we don't spam
                    data["status"] = "notified"
                    gate_path.write_text(json.dumps(data, indent=2))
            except (json.JSONDecodeError, OSError) as e:
                logger.debug("Human gate read failed for %s: %s", run.label, e)

    def approve_human_gate(self, investigation_id: int, feedback: str = "") -> bool:
        """Approve a pending human gate, allowing the investigation to resume.

        Parameters
        ----------
        investigation_id : int
            The investigation to approve.
        feedback : str
            Optional feedback that will be written for the orchestrator to read.

        Returns True if the gate was found and approved, False otherwise.
        """
        run = self.running.get(investigation_id)
        if not run:
            return False
        gate_path = run.workspace_path / ".swarm" / "human-gate.json"
        if not gate_path.exists():
            return False
        try:
            data = json.loads(gate_path.read_text())
            data["status"] = "approved"
            if feedback:
                data["feedback"] = feedback
            gate_path.write_text(json.dumps(data, indent=2))
            self.send_message(f"✅ *{run.label}* — gate approved. Investigation resuming.")
            # Restart the agent now that the gate is approved
            self._restart_after_gate(run)
            return True
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to approve gate for %s: %s", run.label, e)
            return False

    def revise_human_gate(self, investigation_id: int, feedback: str) -> bool:
        """Reject a pending human gate with revision feedback.

        The orchestrator reads the feedback and creates revision tasks.
        """
        run = self.running.get(investigation_id)
        if not run:
            return False
        gate_path = run.workspace_path / ".swarm" / "human-gate.json"
        if not gate_path.exists():
            return False
        try:
            data = json.loads(gate_path.read_text())
            data["status"] = "revision_requested"
            data["feedback"] = feedback
            gate_path.write_text(json.dumps(data, indent=2))
            self.send_message(
                f"🔄 *{run.label}* — revision requested.\n"
                f"Feedback: _{feedback}_"
            )
            # Restart the agent so it can read the revision feedback
            self._restart_after_gate(run)
            return True
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to write revision for %s: %s", run.label, e)
            return False

    def _restart_after_gate(self, run: RunningInvestigation) -> None:
        """Restart an investigation after a human gate decision.

        Unlike _try_restart (which is for crash recovery), this does not
        count against retry limits since the pause was intentional.
        """
        resume_file = self._build_resume_prompt(run)
        # Rotate the log file so the new session starts clean
        if run.log_path.exists():
            suffix = f".gate-{int(time.time())}.log"
            try:
                run.log_path.rename(run.log_path.with_suffix(suffix))
            except OSError:
                pass
        try:
            self._launch_in_tmux(run.tmux_session, run.workspace_path,
                                 prompt_file=resume_file, rigor=run.rigor)
            run.stall_warned = False
            run.context_directive_level = ""
            logger.info("Restarted %s after human gate decision", run.label)
        except Exception as e:
            logger.error("Failed to restart %s after gate: %s", run.label, e)

    # ------------------------------------------------------------------
    # Claim Ledger — cross-run scientific state
    # ------------------------------------------------------------------

    def _sync_findings_to_ledger(self, run: RunningInvestigation,
                                 tasks: list[dict] | None = None) -> None:
        """Sync new Beads findings into the Claim Ledger for this lineage.

        Called during progress polling. Only processes findings not yet synced.
        Provenance is inferred from task type/title.
        """
        inv = self.queue.get(run.investigation_id)
        if inv is None or inv.lineage_id is None:
            return

        if tasks is None:
            from voronoi.beads import run_bd_json
            code, parsed = run_bd_json("list", "--json", cwd=str(run.workspace_path))
            if code != 0 or not isinstance(parsed, list):
                return
            tasks = parsed

        from voronoi.science.claims import (
            PROVENANCE_RETRIEVED_PRIOR,
            PROVENANCE_RUN_EVIDENCE,
            ClaimArtifact,
            load_ledger,
            save_ledger,
        )
        from voronoi.utils import extract_field

        ledger = load_ledger(inv.lineage_id, base_dir=self.config.base_dir)
        synced_ids = {f_id for c in ledger.claims for f_id in c.supporting_findings}

        new_claims = False
        for task in tasks:
            tid = task.get("id", "")
            title = task.get("title", "")
            notes = task.get("notes", "")

            if "FINDING" not in title.upper():
                continue
            if tid in synced_ids:
                continue

            # Determine provenance from task context
            title_lower = title.lower()
            if "scout" in title_lower or "literature" in title_lower or "prior" in title_lower:
                provenance = PROVENANCE_RETRIEVED_PRIOR
            else:
                provenance = PROVENANCE_RUN_EVIDENCE

            # Extract quantitative summary
            effect = extract_field(notes, "EFFECT_SIZE")
            n = extract_field(notes, "N") or extract_field(notes, "SAMPLE_SIZE")
            sample_summary = f"N={n}" if n else None

            # Extract data file as artifact
            artifacts = []
            data_file = extract_field(notes, "DATA_FILE")
            if data_file:
                sha = extract_field(notes, "SHA256") or extract_field(notes, "DATA_HASH")
                artifacts.append(ClaimArtifact(
                    path=data_file,
                    artifact_type="data",
                    sha256=sha or None,
                    git_tag=f"run-{inv.cycle_number}-complete" if inv.cycle_number > 1 else None,
                    description=f"Data for {title}",
                ))

            # Clean statement from FINDING prefix
            statement = title
            for prefix in ("FINDING:", "FINDING -", "FINDING"):
                if statement.upper().startswith(prefix):
                    statement = statement[len(prefix):].strip()
                    break

            ledger.add_claim(
                statement=statement,
                provenance=provenance,
                source_cycle=inv.cycle_number,
                supporting_findings=[tid],
                effect_summary=effect or None,
                sample_summary=sample_summary,
                artifacts=artifacts,
            )
            new_claims = True

        if new_claims:
            save_ledger(inv.lineage_id, ledger, base_dir=self.config.base_dir)

    def _transition_to_review(self, run: RunningInvestigation) -> None:
        """Transition a completed science investigation to review status.

        Generates self-critique, syncs final findings to ledger, and sends
        the review message to Telegram.
        """
        inv = self.queue.get(run.investigation_id)
        if inv is None:
            return

        # Final sync of all findings
        self._sync_findings_to_ledger(run)

        # Generate self-critique
        if inv.lineage_id is not None:
            from voronoi.science.claims import generate_self_critique, load_ledger, save_ledger
            ledger = load_ledger(inv.lineage_id, base_dir=self.config.base_dir)

            # Promote provisional claims to asserted (run converged successfully)
            for claim in ledger.claims:
                if claim.status == "provisional" and claim.source_cycle == inv.cycle_number:
                    try:
                        ledger.assert_claim(claim.id)
                    except (ValueError, KeyError):
                        pass

            critiques = generate_self_critique(ledger)
            for obj in critiques:
                ledger.objections.append(obj)

            save_ledger(inv.lineage_id, ledger, base_dir=self.config.base_dir)

            # Build review message with claims
            review_text = self._build_review_message(run, ledger)
            self.send_message(review_text)
        else:
            self.send_message(
                f"🔬 *{run.label}* converged — ready for review.\n"
                f"Reply with feedback or send `/voronoi continue {run.label}` to iterate."
            )

        self.queue.review(run.investigation_id)

    def _build_review_message(self, run: RunningInvestigation,
                              ledger) -> str:
        """Build the Telegram review message from the claim ledger."""
        lines = [
            f"🔬 *{run.label}* — Round {run.improvement_rounds or 1} complete "
            f"(eval: {run.eval_score:.2f})\n",
        ]

        # Show claims
        for claim in ledger.claims:
            if claim.status == "retired":
                continue
            badge = {"locked": "🔒", "replicated": "🔒🔒", "challenged": "⚡",
                     "asserted": "✅", "provisional": "❓"
                     }.get(claim.status, "•")
            ev = f" ({claim.effect_summary})" if claim.effect_summary else ""
            lines.append(f"{badge} {claim.id}: {claim.statement}{ev}")

        # Show self-critique warnings
        surfaced = [o for o in ledger.objections if o.status == "surfaced"]
        if surfaced:
            lines.append("\n⚠️ *Self-identified weaknesses:*")
            for obj in surfaced[:5]:
                lines.append(f"  • {obj.concern}")

        lines.append(
            "\nReply with your feedback, or:\n"
            f"`/voronoi continue {run.label}` — run another round\n"
            f"`/voronoi complete {run.label}` — accept and close"
        )
        return "\n".join(lines)

    def prepare_continuation(self, run: RunningInvestigation) -> None:
        """Prepare the workspace for a continuation run.

        Archives .swarm/ state, tags the git boundary, prunes worktrees,
        and writes immutability invariants for locked claims.
        """
        ws = run.workspace_path
        swarm = ws / ".swarm"

        inv = self.queue.get(run.investigation_id)
        cycle_num = inv.cycle_number if inv else 1

        # 1. Git tag the run boundary
        tag_name = f"run-{cycle_num}-complete"
        try:
            subprocess.run(
                ["git", "tag", "-f", tag_name],
                cwd=str(ws), capture_output=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            logger.debug("Failed to create git tag %s", tag_name)

        # 2. Archive .swarm/ state
        archive_dir = swarm / "archive" / f"run-{cycle_num}"
        archive_dir.mkdir(parents=True, exist_ok=True)
        files_to_archive = [
            "deliverable.md", "belief-map.json", "orchestrator-checkpoint.json",
            "success-criteria.json", "experiments.tsv", "eval-score.json",
            "convergence.json", "claim-evidence.json", "report.pdf",
            "state-digest.md", "scout-brief.md",
        ]
        for fname in files_to_archive:
            src = swarm / fname
            if src.exists():
                try:
                    shutil.copy2(src, archive_dir / fname)
                except OSError:
                    pass

        # 3. Clean .swarm/ for fresh orchestrator (keep reusable files)
        files_to_remove = [
            "orchestrator-checkpoint.json", "convergence.json",
            "eval-score.json", "dispatcher-directive.json",
            "human-gate.json", "state-digest.md",
        ]
        for fname in files_to_remove:
            p = swarm / fname
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

        # Keep: belief-map.json, experiments.tsv, success-criteria.json,
        #        deliverable.md (for warm-start reference), events.jsonl

        # 4. Prune git worktrees
        try:
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=str(ws), capture_output=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

        # 5. Write immutability invariants for locked claims
        if inv and inv.lineage_id is not None:
            from voronoi.science.claims import load_ledger
            ledger = load_ledger(inv.lineage_id, base_dir=self.config.base_dir)
            immutable_paths = ledger.get_immutable_paths()
            if immutable_paths:
                from voronoi.science.gates import load_invariants, save_invariants, Invariant
                existing = load_invariants(ws)
                # Add file_unchanged invariants for locked claim artifacts
                for path in immutable_paths:
                    inv_id = f"IMMUTABLE_{path.replace('/', '_').upper()}"
                    if not any(i.id == inv_id for i in existing):
                        existing.append(Invariant(
                            id=inv_id,
                            description=f"Do not modify locked claim artifact: {path}",
                            check_type="file_unchanged",
                            params={"paths": [path], "since_tag": tag_name},
                        ))
                save_invariants(ws, existing)
