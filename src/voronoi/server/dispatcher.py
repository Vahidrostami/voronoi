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
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from voronoi.gateway.progress import (
    MODE_EMOJI, MODE_VERB,
    MSG_TYPE_MILESTONE, MSG_TYPE_STATUS,
    format_launch, format_complete, format_failure, format_alert,
    format_negative_result, format_restart, format_wake, format_pause,
    format_duration, phase_description,
    format_learning_stalled,
    build_digest,
)
from voronoi.server.tmux import (
    ensure_copilot_auth,
    launch_in_tmux,
    cleanup_tmux,
    EFFORT_BY_RIGOR,
)

logger = logging.getLogger("voronoi.dispatcher")


def _find_checkpoint(workspace: Path) -> Path | None:
    """Find the orchestrator checkpoint file.

    Delegates to the canonical ``voronoi.utils.find_checkpoint``.
    Kept as a module-level function for backward compatibility with
    internal callers.
    """
    from voronoi.utils import find_checkpoint
    return find_checkpoint(workspace)


@dataclass
class DispatcherConfig:
    """Configuration for the dispatcher."""
    base_dir: Path = field(default_factory=lambda: Path.home() / ".voronoi")
    max_concurrent: int = 2
    max_agents: int = 6
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
    max_context_restarts: int = 2      # max proactive context refreshes
    park_timeout_hours: int = 4        # force-wake parked orchestrator after this
    learning_stall_minutes: int = 20   # alert if no new findings/claims for this long
    # Self-steer stall escalation (cumulative minutes without learning).
    # Each strike writes a richer directive + belief-snapshot into
    # .swarm/stall-signal.json which the next orchestrator prompt injects.
    # Strike 1: directive = "diagnose_and_steer" (self-steer prompt #1)
    # Strike 2: directive = "pivot_or_declare" (self-steer prompt #2)
    # Strike 3: directive = "final_steer" (last self-steer, grace before auto-park)
    # Strike 4: directive = "auto_park" (terminal, fires after strike3 + grace)
    stall_strike1_minutes: int = 30
    stall_strike2_minutes: int = 60
    stall_strike3_minutes: int = 90
    stall_final_grace_minutes: int = 20


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
    context_restarts: int = 0  # Proactive context refreshes (separate from retry_count)
    status_message_id: int | None = None  # Telegram message ID for edit-in-place
    last_rigor: str = ""  # Track rigor escalation in DISCOVER mode
    pending_events: list[dict] = field(default_factory=list)  # Events accumulated while orchestrator is parked
    orchestrator_parked: bool = False  # True when orchestrator exited intentionally with active workers
    park_entered_at: float = 0  # When the current park began (for park_timeout_hours safety net)
    last_parked_digest_at: float = 0  # Last Telegram digest while parked (throttle to 5min)
    polling_strike_count: int = 0  # Consecutive polls where orchestrator pane was sleeping (BUG-003 watchdog)
    _criteria_alerts: set = field(default_factory=set)  # Track which criteria-progress alerts have fired
    _sentinel_missing_contract_warned: bool = False  # Track sentinel missing-contract warning
    notified_reversed_hypotheses: set = field(default_factory=set)  # Track which reversed hypotheses have been alerted
    last_convergence_attempt_at: float = 0  # Throttle _try_convergence_check() calls
    last_ledger_map: dict[str, str] = field(default_factory=dict)  # claim_id → status for delta detection
    _ledger_baseline_seeded: bool = False  # First poll seeds baseline without emitting deltas
    last_learning_activity_at: float = 0  # Last time a new finding/claim transition was observed
    stall_strike_level: int = 0  # Self-steer escalation: 0/1/2/3/4 (4 = auto-parked)
    stall_extension_expires_at: float = 0  # /extend grants stall immunity until this timestamp
    # Evidence-gated scaling: belief-map snapshot for detecting moves
    _prior_belief_snapshot: dict[str, str] = field(default_factory=dict)  # hypothesis_id → confidence tier

    @property
    def label(self) -> str:
        return self.codename or f"#{self.investigation_id}"

    @property
    def log_path(self) -> Path:
        return self.workspace_path / ".swarm" / "agent.log"

    def save_notification_state(self) -> None:
        """Persist notification tracking sets so they survive dispatcher restart."""
        state_path = self.workspace_path / ".swarm" / "dispatcher-notify-state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "notified_findings": sorted(self.notified_findings),
            "notified_design_invalid": sorted(self.notified_design_invalid),
            "notified_reversed_hypotheses": sorted(self.notified_reversed_hypotheses),
            "criteria_alerts": sorted(self._criteria_alerts),
            "sentinel_missing_contract_warned": self._sentinel_missing_contract_warned,
            "notified_paradigm_stress": self.notified_paradigm_stress,
        }
        try:
            state_path.write_text(json.dumps(data, indent=2))
        except OSError:
            pass

    def restore_notification_state(self) -> None:
        """Restore notification tracking sets from disk after dispatcher restart."""
        state_path = self.workspace_path / ".swarm" / "dispatcher-notify-state.json"
        if not state_path.exists():
            return
        try:
            data = json.loads(state_path.read_text())
            if not isinstance(data, dict):
                return
            self.notified_findings = set(data.get("notified_findings", []))
            self.notified_design_invalid = set(data.get("notified_design_invalid", []))
            self.notified_reversed_hypotheses = set(data.get("notified_reversed_hypotheses", []))
            self._criteria_alerts = set(data.get("criteria_alerts", []))
            self._sentinel_missing_contract_warned = bool(data.get("sentinel_missing_contract_warned"))
            self.notified_paradigm_stress = bool(data.get("notified_paradigm_stress"))
        except (json.JSONDecodeError, OSError):
            pass


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
        self._launching: set[int] = set()  # IDs currently being provisioned
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

        Workspace provisioning (git clone, voronoi init) can take minutes
        for large repos.  To prevent blocking the 10-second scheduler
        tick, the heavy ``_launch_investigation`` call runs in a
        background thread.  A ``_launching`` set guards against
        double-claiming and lets the fast prep phase (recovery,
        paused-timeout) run unblocked on subsequent ticks.
        """
        # Recovery: re-adopt running investigations we're not tracking
        self._recover_running()

        # Auto-fail paused investigations that exceeded the timeout
        self._check_paused_timeouts()

        # Note: we do NOT bail if another launch is in flight.  ``next_ready()``
        # atomically marks each claimed row ``running`` (INV-06), so concurrent
        # launch threads cannot collide on the same investigation.  Gating on
        # ``self._launching`` being non-empty would serialize every launch and
        # defeat the operator's ``max_concurrent`` setting whenever one
        # investigation is in the middle of a slow ``git clone``.

        inv = self.queue.next_ready(self.config.max_concurrent)
        if inv is None:
            logger.debug("dispatch_next: nothing ready (db=%s)", self.queue.db_path)
            return
        logger.info("Dispatching investigation #%d: %.60s", inv.id, inv.question)
        self._launching.add(inv.id)
        t = threading.Thread(
            target=self._launch_investigation_safe,
            args=(inv,),
            name=f"voronoi-launch-{inv.id}",
            daemon=True,
        )
        t.start()

    def _launch_investigation_safe(self, inv) -> None:
        """Wrapper around _launch_investigation that cleans up _launching and
        handles errors.  Runs in a background thread so dispatch_next returns
        immediately after claiming the investigation."""
        try:
            self._launch_investigation(inv)
        except Exception as e:
            logger.error("Failed to launch investigation #%d: %s", inv.id, e, exc_info=True)
            self.queue.fail(inv.id, str(e))
            label = inv.codename or f"#{inv.id}"
            self.send_message(
                f"💀 *Voronoi · {label} failed to launch*\n\nError: `{e}`"
            )
        finally:
            self._launching.discard(inv.id)

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
            if inv.id in self._launching:
                continue  # launch thread is provisioning this one

            if not inv.workspace_path:
                # Claimed by next_ready() but workspace not yet provisioned.
                # Reset to queued so it will be picked up on the next cycle
                # instead of permanently lost.
                self._requeue_unprovisioned(inv.id)
                continue

            workspace_path = Path(inv.workspace_path)
            tmux_session = f"voronoi-inv-{inv.id}"

            try:
                result = subprocess.run(
                    ["tmux", "has-session", "-t", tmux_session],
                    capture_output=True, timeout=10,
                )
                session_alive = result.returncode == 0
            except subprocess.TimeoutExpired:
                logger.warning("tmux has-session timed out for #%d — skipping recovery",
                               inv.id)
                continue

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

            # Restore task_snapshot from Beads — but only when the agent
            # is dead.  When the session is alive, the agent's MCP server
            # holds an exclusive lock on the embedded Dolt database, so
            # `bd list --json` would always fail with a lock error.
            # poll_progress() → _check_progress() will populate the
            # snapshot on the next cycle instead.
            if not session_alive:
                self._restore_task_snapshot(run)

            # Restore notification tracking sets from disk so we don't
            # re-send alerts that were already delivered (BUG-003).
            run.restore_notification_state()

            # Restore last_rigor from checkpoint so escalation state survives restart
            cp_path = _find_checkpoint(workspace_path)
            if cp_path is not None:
                try:
                    cp_data = json.loads(cp_path.read_text())
                    if isinstance(cp_data, dict):
                        cp_rigor = cp_data.get("rigor", "")
                        if isinstance(cp_rigor, str) and cp_rigor:
                            run.last_rigor = cp_rigor
                except (json.JSONDecodeError, OSError):
                    pass

            if not session_alive:
                # Check if a human gate is pending — do NOT crash-retry
                if self._has_pending_human_gate(run):
                    self.running[inv.id] = run
                    logger.info("Recovered gate-paused investigation #%d (%s)",
                                inv.id, inv.codename)
                    continue
                # Re-adopt into self.running so poll_progress() handles
                # completion/restart on its next cycle.  This keeps
                # _recover_running() fast and avoids blocking
                # dispatch_next() with heavyweight completion logic
                # (PDF generation, GitHub publish, worktree cleanup).
                self.running[inv.id] = run
                logger.info("Re-adopted dead investigation #%d (%s) — "
                            "poll_progress will handle completion/restart",
                            inv.id, inv.codename)
            else:
                # Still alive — re-adopt for monitoring
                self.running[inv.id] = run
                logger.info("Re-adopted running investigation #%d (%s)",
                            inv.id, inv.codename)

        # Sweep for completed/reviewed investigations that lack a run manifest
        # (crash recovery for the race between status transition and manifest
        # write — see INV-44).
        self._sweep_missing_manifests()

    def _sweep_missing_manifests(self) -> None:
        """Write run manifests for completed investigations that are missing one.

        Covers the crash window between the queue status transition
        (review/complete) and ``_write_run_manifest()``.  Called once per
        ``dispatch_next()`` cycle via ``_recover_running()``.
        """
        for status in ("review", "complete"):
            try:
                with self.queue._connect() as conn:
                    rows = conn.execute(
                        "SELECT * FROM investigations WHERE status=? "
                        "ORDER BY completed_at DESC LIMIT 10",
                        (status,),
                    ).fetchall()
                    invs = [self.queue._row_to_investigation(r) for r in rows]
            except Exception:
                continue
            for inv in invs:
                if not inv.workspace_path:
                    continue
                ws = Path(inv.workspace_path)
                manifest_path = ws / ".swarm" / "run-manifest.json"
                if manifest_path.exists():
                    continue
                if not (ws / ".swarm" / "deliverable.md").exists():
                    continue  # not actually finished
                logger.info("Sweeping missing run manifest for #%d (%s)",
                            inv.id, inv.codename)
                run = RunningInvestigation(
                    investigation_id=inv.id,
                    workspace_path=ws,
                    tmux_session="",
                    question=inv.question,
                    mode=inv.mode,
                    codename=inv.codename,
                    chat_id=inv.chat_id,
                    rigor=inv.rigor or "adaptive",
                )
                try:
                    self._write_run_manifest(run)
                except Exception as e:
                    logger.warning("Failed to sweep manifest for #%d: %s",
                                   inv.id, e)

    def _requeue_unprovisioned(self, investigation_id: int) -> None:
        """Reset a claimed-but-not-launched investigation back to queued.

        This handles the crash window between ``next_ready()`` (which marks
        the row running) and ``queue.start()`` (which attaches the workspace).
        """
        try:
            self.queue.requeue(investigation_id)
            logger.info("Re-queued unprovisioned investigation #%d", investigation_id)
        except Exception as e:
            logger.warning("Failed to re-queue #%d: %s", investigation_id, e)

    def _launch_investigation(self, inv) -> None:
        from voronoi.server.repo_url import extract_repo_url

        # --- Continuation detection: reuse workspace from prior round ---
        is_continuation = (
            inv.parent_id is not None
            and inv.workspace_path
            and Path(inv.workspace_path).is_dir()
        )

        if is_continuation:
            workspace_path = Path(inv.workspace_path)
            logger.info("Continuation round %d for #%d — reusing workspace %s",
                        inv.cycle_number, inv.id, workspace_path)

            # Build the warm-start prompt BEFORE prepare_continuation()
            # deletes the checkpoint — the prompt needs checkpoint data (BUG-004).
            prompt = self._build_prompt(inv, workspace_path)

            # Prepare workspace: archive .swarm/, tag boundary, prune worktrees
            parent_inv = self.queue.get(inv.parent_id)
            if parent_inv:
                parent_run = RunningInvestigation(
                    investigation_id=parent_inv.id,
                    workspace_path=workspace_path,
                    tmux_session="",
                    question=parent_inv.question,
                    mode=parent_inv.mode,
                    codename=parent_inv.codename,
                    chat_id=parent_inv.chat_id,
                    rigor=parent_inv.rigor or "adaptive",
                )
                self.prepare_continuation(parent_run)

            # Refresh templates (agents, skills, scripts)
            self.workspace_mgr._voronoi_init(workspace_path)

            # Update queue with confirmed workspace path
            self.queue.start(inv.id, str(workspace_path))
        else:
            # Fresh workspace — normal provisioning
            if is_continuation is False and inv.parent_id is not None and inv.workspace_path:
                # Workspace was expected but is missing — warn and provision fresh
                logger.warning(
                    "Continuation workspace missing for #%d (expected %s) — provisioning fresh",
                    inv.id, inv.workspace_path,
                )

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

        # Resolve rigor once — Investigation.rigor is always a non-empty str
        # (coerced by _row_to_investigation), no getattr/fallback needed.
        rigor = inv.rigor

        # Patch .swarm-config.json with rigor-mapped effort level
        self._patch_swarm_config(workspace_path, rigor)

        # For non-continuation launches, build the prompt now (continuations
        # built it earlier, before prepare_continuation deleted the checkpoint).
        if not is_continuation:
            prompt = self._build_prompt(inv, workspace_path)
        prompt_file = workspace_path / ".swarm" / "orchestrator-prompt.txt"
        prompt_file.parent.mkdir(parents=True, exist_ok=True)
        prompt_file.write_text(prompt)

        tmux_session = f"voronoi-inv-{inv.id}"
        self._launch_in_tmux(tmux_session, workspace_path, rigor=rigor)

        self.running[inv.id] = RunningInvestigation(
            investigation_id=inv.id,
            workspace_path=workspace_path,
            tmux_session=tmux_session,
            question=inv.question,
            mode=inv.mode,
            codename=inv.codename,
            chat_id=inv.chat_id,
            rigor=rigor,
        )

        logger.info("Investigation %s (#%d) LIVE in tmux=%s workspace=%s",
                    inv.codename, inv.id, tmux_session, workspace_path)

        label = inv.codename or f"#{inv.id}"
        self.send_message(format_launch(
            codename=label,
            mode=inv.mode,
            rigor=rigor,
            question=inv.question,
        ))

    def _build_prompt(self, inv, workspace_path: Path) -> str:
        from voronoi.server.prompt import build_orchestrator_prompt

        rigor = inv.rigor
        label = inv.codename or f"#{inv.id}"

        prior_context = None
        if inv.parent_id is not None:
            from voronoi.server.prompt import build_warm_start_context
            pi_feedback = inv.pi_feedback or ''
            lineage_id = inv.lineage_id or inv.parent_id
            prior_context = build_warm_start_context(
                lineage_id=lineage_id,
                cycle_number=inv.cycle_number,
                pi_feedback=pi_feedback,
                base_dir=self.config.base_dir,
                workspace=workspace_path,
            )

        return build_orchestrator_prompt(
            question=inv.question,
            mode=inv.mode,
            rigor=rigor,
            workspace_path=str(workspace_path),
            codename=label,
            max_agents=self.config.max_agents,
            prior_context=prior_context,
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
        """Delegate to tmux module."""
        ensure_copilot_auth()

    # Rigor → Copilot CLI --effort mapping (canonical source: tmux.py)
    _EFFORT_BY_RIGOR = EFFORT_BY_RIGOR

    def _launch_in_tmux(self, session: str, workspace_path: Path,
                        prompt_file: Path | None = None,
                        rigor: str = "") -> None:
        """Delegate to tmux module."""
        launch_in_tmux(
            session=session,
            workspace_path=workspace_path,
            agent_command=self.config.agent_command,
            agent_flags=self.config.agent_flags,
            orchestrator_model=self.config.orchestrator_model,
            prompt_file=prompt_file,
            rigor=rigor,
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
        paused_ids = []

        for inv_id, run in list(self.running.items()):
            now = time.time()
            if now - run.last_update_at < self.config.progress_interval:
                continue
            run.last_update_at = now

            # Read eval_score from workspace if available
            self._refresh_eval_score(run)

            # Sync checkpoint criteria_status → success-criteria.json
            self._sync_criteria_from_checkpoint(run)

            try:
                result = subprocess.run(
                    ["tmux", "has-session", "-t", run.tmux_session],
                    capture_output=True, timeout=10,
                )
                session_alive = result.returncode == 0
            except subprocess.TimeoutExpired:
                logger.warning("tmux has-session timed out for #%d — skipping poll",
                               inv_id)
                continue

            events = self._check_progress(run, session_alive=session_alive)
            events.extend(self._check_event_log(run))
            if events:
                # If orchestrator is parked, accumulate events for resume prompt
                # and throttle Telegram digests to every 5 minutes
                if run.orchestrator_parked:
                    self._accumulate_parked_events(run, events)
                    if now - run.last_parked_digest_at >= 300:  # 5-minute throttle
                        run.last_parked_digest_at = now
                        logger.info("Investigation #%d: %d events while parked (phase=%s)",
                                    inv_id, len(events), run.phase)
                        self._send_progress_batch(run, events)
                else:
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

            # Idle-pane polling watchdog (BUG-003): orchestrators must
            # checkpoint-and-exit between OODA cycles, never sleep/poll
            # inside the agent session.  Catch violators before they
            # burn their context window.
            if session_alive and not run.orchestrator_parked:
                self._check_orchestrator_polling(run)

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
                elif not session_alive and not self._is_complete(run, session_dead=True):
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
                        paused_ids.append(inv_id)
                        continue  # don't add to completed_ids
                    # Check if orchestrator exited intentionally while workers run.
                    # If checkpoint has active_workers and any are still alive,
                    # defer restart until workers finish or an urgent event arrives.
                    if run.orchestrator_parked:
                        # Already parked — check if workers are still running.
                        # Use park_entered_at (not last_parked_digest_at, which
                        # is the Telegram throttle timestamp and would reset
                        # every time an event triggered a digest).
                        parked_hours = (now - run.park_entered_at) / 3600 if run.park_entered_at else 0
                        if parked_hours >= self.config.park_timeout_hours:
                            # Safety net: only force-wake if workers are
                            # actually dead.  If workers are still alive,
                            # extend the timeout (exponential backoff) so
                            # long-running experiments aren't interrupted.
                            if self._has_active_workers(run):
                                run.park_entered_at = now
                                logger.info(
                                    "Investigation #%d park timeout "
                                    "(%.1fh) but workers alive — "
                                    "extending park",
                                    inv_id, parked_hours,
                                )
                                continue  # don't add to completed_ids
                            logger.warning("Investigation #%d force-waking — "
                                           "parked for %.1fh (limit %dh)",
                                           inv_id, parked_hours,
                                           self.config.park_timeout_hours)
                            self._wake_from_park(run)
                            continue  # don't add to completed_ids
                        if self._has_active_workers(run):
                            # Workers still running — check for urgent wakes
                            if self._needs_orchestrator(run):
                                logger.info("Investigation #%d waking orchestrator — "
                                            "urgent event detected",
                                            inv_id)
                                self._wake_from_park(run)
                            continue  # don't add to completed_ids
                        else:
                            # Workers done — normal wake (NOT a crash restart)
                            logger.info("Investigation #%d workers finished, "
                                        "waking orchestrator", inv_id)
                            self._wake_from_park(run)
                            continue  # don't add to completed_ids
                    elif self._has_active_workers(run):
                        # First time seeing park
                        run.orchestrator_parked = True
                        run.park_entered_at = now
                        run.last_parked_digest_at = now
                        logger.info("Investigation #%d orchestrator parked — "
                                    "workers still running",
                                    inv_id)
                        continue  # don't add to completed_ids
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

        for inv_id in paused_ids:
            run = self.running[inv_id]
            self._pause_investigation(run, "Copilot/GitHub auth expired")

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

    # Hard upper bound for timeout overrides (1 week)
    _MAX_TIMEOUT_HOURS: int = 168

    def _effective_timeout(self, run: RunningInvestigation) -> int:
        """Return the effective timeout for an investigation.

        Checks for a per-investigation override file at
        ``<workspace>/.swarm/timeout_hours``.  The file should contain a
        single integer (the new total timeout in hours).  If the file is
        missing or unreadable, falls back to ``self.config.timeout_hours``.

        Capped at ``_MAX_TIMEOUT_HOURS`` to prevent runaway investigations.
        """
        override_path = run.workspace_path / ".swarm" / "timeout_hours"
        if override_path.exists():
            try:
                raw = override_path.read_text().strip()
                value = int(raw)
                if value > 0:
                    return min(value, self._MAX_TIMEOUT_HOURS)
                logger.warning(
                    "Invalid timeout override for #%d: value %r must be positive; "
                    "falling back to config default %dh",
                    run.investigation_id, value, self.config.timeout_hours,
                )
            except (ValueError, OSError) as e:
                logger.warning(
                    "Failed to read timeout override at %s for #%d (%s); "
                    "falling back to config default %dh",
                    override_path, run.investigation_id, e,
                    self.config.timeout_hours,
                )
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

    def _sync_criteria_from_checkpoint(self, run: RunningInvestigation) -> None:
        """Sync criteria_status from orchestrator checkpoint into success-criteria.json.

        The orchestrator agent updates ``checkpoint.criteria_status`` (a dict
        mapping criterion IDs to booleans) but may never write those updates
        back to the canonical ``success-criteria.json`` (a list of dicts with
        ``met`` fields). This method only promotes criteria to met when the
        checkpoint explicitly records ``True`` for that criterion; it never
        clears a met criterion from the canonical file because the checkpoint
        may be stale or partial.

        Only the literal boolean ``True`` promotes a criterion. Any other
        value — including truthy strings such as ``"pending"``, numbers, or
        dicts — is ignored and logged as a warning, since those indicate the
        orchestrator wrote a non-schema value into ``criteria_status``. This
        prevents anti-fabrication violations where free-form status text was
        silently promoted to ``met: True`` (see SCIENCE.md §10).

        Called each poll cycle after ``_refresh_eval_score()``.
        """
        cp_path = _find_checkpoint(run.workspace_path)
        sc_path = run.workspace_path / ".swarm" / "success-criteria.json"
        if cp_path is None or not sc_path.exists():
            return
        try:
            cp = json.loads(cp_path.read_text())
            if not isinstance(cp, dict):
                return
            cs = cp.get("criteria_status")
            if not isinstance(cs, dict) or not cs:
                return
            criteria = json.loads(sc_path.read_text())
            if not isinstance(criteria, list) or not criteria:
                return
        except (json.JSONDecodeError, OSError):
            return

        changed = False
        for item in criteria:
            if not isinstance(item, dict):
                continue
            cid = item.get("id", "")
            if cid not in cs:
                continue
            raw = cs[cid]
            # Strict: only the literal boolean True promotes.
            if raw is True:
                if not bool(item.get("met")):
                    item["met"] = True
                    changed = True
            elif raw is False or raw is None:
                # Explicit not-met — ignore (promotion-only sync).
                continue
            else:
                # Non-bool value: reject and warn. Orchestrator wrote a
                # free-form status (e.g., "pending full data") that is not
                # part of the criteria_status schema.
                logger.warning(
                    "Ignoring non-boolean criteria_status[%s]=%r for #%d "
                    "(expected True/False; schema violation)",
                    cid, raw, run.investigation_id,
                )

        if changed:
            try:
                # Atomic write: temp file + rename to avoid corrupting
                # the file while the orchestrator agent may be reading it.
                import tempfile
                tmp_fd, tmp_path = tempfile.mkstemp(
                    dir=str(sc_path.parent), suffix=".tmp",
                )
                closed = False
                try:
                    os.write(tmp_fd, json.dumps(criteria, indent=2).encode())
                    os.close(tmp_fd)
                    closed = True
                    os.replace(tmp_path, str(sc_path))
                except BaseException:
                    if not closed:
                        os.close(tmp_fd)
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    raise
                logger.debug("Synced criteria_status → success-criteria.json for #%d",
                             run.investigation_id)
            except OSError:
                pass

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
                if elapsed_hours >= 8:
                    alert_key = "criteria_zero_8h"
                else:
                    alert_key = "criteria_zero_4h"
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
        cp_path = _find_checkpoint(run.workspace_path)
        if cp_path is not None:
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

    # Directive priority order — higher index = higher priority.
    # _write_directive refuses to overwrite a higher-priority directive.
    _DIRECTIVE_PRIORITY: dict[str, int] = {
        "context_advisory": 1,
        "context_warning": 2,
        "context_critical": 3,
        "sentinel_violation": 4,
    }

    def _write_directive(self, run: RunningInvestigation,
                         level: str, message: str) -> None:
        """Write a dispatcher directive file for the orchestrator to poll.

        Refuses to overwrite an existing directive with higher priority
        so that sentinel violations are not clobbered by context
        directives and vice versa.
        """
        directive_path = run.workspace_path / ".swarm" / "dispatcher-directive.json"
        directive_path.parent.mkdir(parents=True, exist_ok=True)

        # Check existing directive priority
        new_priority = self._DIRECTIVE_PRIORITY.get(level, 0)
        if directive_path.exists():
            try:
                existing = json.loads(directive_path.read_text())
                if isinstance(existing, dict):
                    existing_level = existing.get("directive", "") or existing.get("level", "")
                    existing_priority = self._DIRECTIVE_PRIORITY.get(existing_level, 0)
                    if existing_priority > new_priority:
                        logger.debug(
                            "Skipping %s directive for %s — higher-priority %s already set",
                            level, run.label, existing_level,
                        )
                        return
            except (json.JSONDecodeError, OSError):
                pass

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
        """Check time-based and self-reported context pressure.

        Time-based thresholds are evidence-gated: if the orchestrator's
        context snapshot shows >30% headroom, we skip the force-restart
        and just write the directive (the agent is healthy enough to read it).
        Token-based thresholds (from checkpoint) always trigger regardless
        of elapsed time.
        """
        # Time-based thresholds (escalating)
        if (elapsed_hours >= self.config.context_critical_hours
                and run.context_directive_level != "context_critical"):
            run.context_directive_level = "context_critical"
            self._write_directive(run, "context_critical",
                f"{int(elapsed_hours)}h elapsed. Run /compact NOW to recover context budget, "
                f"write checkpoint, and dispatch Scribe immediately or risk session loss.")
            # Only force-restart if the agent is actually context-pressured.
            # If the snapshot shows >30% headroom, the agent can read the directive itself.
            if self._is_context_pressured(run):
                if self._force_context_restart(run):
                    return
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
            # Force-compact immediately instead of waiting for the 6h interval
            try:
                from voronoi.server.compact import compact_workspace_state
                if compact_workspace_state(run.workspace_path):
                    logger.info("Force-compacted workspace for %s at context_warning",
                                run.label)
            except Exception as e:
                logger.debug("Force-compact failed for %s: %s", run.label, e)
            self.send_message(format_alert(
                run.label,
                f"Context warning — {int(elapsed_hours)}h elapsed. "
                f"Workspace compacted. Directive sent to delegate remaining work."
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
        cp_path = _find_checkpoint(run.workspace_path)
        if cp_path is None:
            return
        try:
            cp = json.loads(cp_path.read_text())
            if not isinstance(cp, dict):
                return

            # Prefer ground-truth snapshot over self-reported estimate
            snapshot = cp.get("context_snapshot")
            if isinstance(snapshot, dict) and snapshot.get("model_limit", 0) > 0:
                limit = snapshot["model_limit"]
                free = snapshot.get("free_tokens", 0)
                remaining = free / limit if limit else 0
                # Log context snapshot event for timeline analysis
                try:
                    from voronoi.server.events import log_context_snapshot
                    log_context_snapshot(
                        run.workspace_path,
                        agent="orchestrator",
                        cycle=cp.get("cycle", 0),
                        model=snapshot.get("model", ""),
                        model_limit=limit,
                        total_used=snapshot.get("total_used", 0),
                        system_tokens=snapshot.get("system_tokens", 0),
                        message_tokens=snapshot.get("message_tokens", 0),
                        free_tokens=free,
                        buffer_tokens=snapshot.get("buffer_tokens", 0),
                    )
                except Exception:
                    pass  # non-critical logging
            else:
                remaining = cp.get("context_window_remaining_pct", 0)

            if not remaining or remaining <= 0:
                return  # orchestrator didn't report

            if (remaining <= 0.15
                    and run.context_directive_level != "context_critical"):
                run.context_directive_level = "context_critical"
                self._write_directive(run, "context_critical",
                    "Context window nearly exhausted (self-reported). "
                    "Run /compact NOW, dispatch Scribe, and write checkpoint.")
                # Force-restart: agent is too exhausted to act on directives
                if self._force_context_restart(run):
                    return
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

    def _is_context_pressured(self, run: RunningInvestigation) -> bool:
        """Check if the orchestrator is actually context-pressured.

        Reads the context_snapshot or context_window_remaining_pct from
        the checkpoint.  Returns True if the agent reports ≤30% remaining,
        or if no snapshot is available (assume the worst).
        """
        cp_path = _find_checkpoint(run.workspace_path)
        if cp_path is None:
            return True  # no data → assume pressured
        try:
            cp = json.loads(cp_path.read_text())
            if not isinstance(cp, dict):
                return True

            snapshot = cp.get("context_snapshot")
            if isinstance(snapshot, dict) and snapshot.get("model_limit", 0) > 0:
                limit = snapshot["model_limit"]
                free = snapshot.get("free_tokens", 0)
                remaining = free / limit if limit else 0
            else:
                remaining = cp.get("context_window_remaining_pct", 0)

            if not remaining or remaining <= 0:
                return True  # no data → assume pressured

            return remaining <= 0.30
        except (json.JSONDecodeError, OSError):
            return True  # can't read → assume pressured

    def _force_context_restart(self, run: RunningInvestigation) -> bool:
        """Force-restart the orchestrator to refresh its context window.

        Called when context_critical is reached (time-based or token-based).
        The agent is likely too exhausted to read directive files, so we
        kill it and restart with a fresh resume prompt.

        Uses a separate counter (context_restarts) from crash retries
        (retry_count) because these are proactive refreshes, not failures.

        Returns True if the restart was successful.
        """
        if run.context_restarts >= self.config.max_context_restarts:
            logger.warning("Investigation #%d exhausted %d context restarts",
                           run.investigation_id, run.context_restarts)
            return False

        run.context_restarts += 1

        logger.info("Force context restart for #%d (context restart %d/%d)",
                    run.investigation_id, run.context_restarts,
                    self.config.max_context_restarts)

        # Compact workspace state first so the resume prompt has fresh data
        try:
            from voronoi.server.compact import compact_workspace_state
            compact_workspace_state(run.workspace_path)
        except Exception:
            pass

        # Kill the current agent session
        subprocess.run(
            ["tmux", "kill-session", "-t", run.tmux_session],
            capture_output=True, timeout=10,
        )

        # Build resume prompt and relaunch
        prompt_file = run.workspace_path / ".swarm" / "orchestrator-prompt.txt"
        if not prompt_file.exists():
            logger.error("Prompt file missing for #%d — cannot context-restart",
                         run.investigation_id)
            return False

        resume_file = self._build_resume_prompt(run)

        # Rotate the log file
        if run.log_path.exists():
            suffix = f".ctx-{run.context_restarts}.log"
            try:
                run.log_path.rename(run.log_path.with_suffix(suffix))
            except OSError:
                pass

        try:
            self._launch_in_tmux(run.tmux_session, run.workspace_path,
                                 prompt_file=resume_file,
                                 rigor=self._effective_rigor(run))
            run.stall_warned = False
            run.context_directive_level = ""

            self.send_message(format_restart(
                run.label,
                attempt=run.context_restarts,
                max_retries=self.config.max_context_restarts,
                log_tail="",
                clean_exit=True,
            ))
            logger.info("Context restart successful for %s", run.label)
            return True
        except Exception as e:
            logger.error("Failed context restart for %s: %s", run.label, e)
            return False

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

    # Number of consecutive polls where the orchestrator pane was observed
    # running `sleep` before we classify the session as a polling violator.
    # Default poll cadence is 30s, so 3 strikes ≈ 60–90s of confirmed idle.
    POLLING_STRIKE_THRESHOLD = 3

    def _orchestrator_pane_command(self, run: RunningInvestigation) -> str | None:
        """Return the current foreground command in the orchestrator's pane.

        Uses ``tmux display-message`` to read ``#{pane_current_command}``
        for the session's active pane.  Returns ``None`` on error (timeout,
        tmux missing, session gone) — callers must treat ``None`` as "no
        signal", not "not polling".
        """
        try:
            result = subprocess.run(
                ["tmux", "display-message", "-p", "-t", run.tmux_session,
                 "#{pane_current_command}"],
                capture_output=True, text=True, timeout=5,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return None
        if result.returncode != 0:
            return None
        cmd = result.stdout.strip()
        return cmd or None

    def _check_orchestrator_polling(self, run: RunningInvestigation) -> None:
        """Detect and recover from orchestrators stuck in a sleep/poll loop.

        The orchestrator protocol requires write-checkpoint-and-exit between
        OODA cycles.  An orchestrator running ``sleep`` inside its pane has
        violated that protocol (e.g., old prompt telling it to poll a human
        gate).  After ``POLLING_STRIKE_THRESHOLD`` consecutive confirmed
        strikes, kill the session and force a context-refresh restart so
        the new session starts with the current prompt and a fresh window.
        """
        cmd = self._orchestrator_pane_command(run)
        if cmd is None:
            return  # no signal — don't change strike state
        if cmd.lower() == "sleep":
            run.polling_strike_count += 1
            logger.debug("Orchestrator polling strike %d/%d for %s",
                         run.polling_strike_count,
                         self.POLLING_STRIKE_THRESHOLD, run.label)
            if run.polling_strike_count >= self.POLLING_STRIKE_THRESHOLD:
                logger.warning("Investigation #%d caught polling "
                               "(%d consecutive sleep observations) — "
                               "killing session for context refresh",
                               run.investigation_id,
                               run.polling_strike_count)
                self.send_message(
                    f"⚠️ *{run.label}* — orchestrator caught polling "
                    f"(`sleep` loop detected). Forcing a context refresh."
                )
                run.polling_strike_count = 0
                # Context-refresh restart uses its own counter and writes
                # a fresh resume prompt, so the reborn session does not
                # inherit the polling directive from the old transcript.
                self._force_context_restart(run)
            return
        # Any non-sleep command resets the counter — orchestrator is working.
        if run.polling_strike_count:
            logger.debug("Orchestrator polling strikes cleared for %s (cmd=%s)",
                         run.label, cmd)
        run.polling_strike_count = 0

    def _check_progress(self, run: RunningInvestigation, *,
                         session_alive: bool = False) -> list[dict]:
        events: list[dict] = []
        tasks: list[dict] | None = None

        # When the agent session is alive its MCP server holds an exclusive
        # flock on the embedded Dolt database.  Calling ``bd list --json``
        # will always fail with a lock error, burning ~3s of retries per
        # poll cycle.  Skip the call entirely and rely on the cached
        # task_snapshot for downstream checks.
        if not session_alive:
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
        events.extend(self._check_sentinel(run))
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
            return events

        for task in tasks:
            tid = task.get("id", "")
            title = task.get("title", "")
            notes = task.get("notes", "")
            if "FINDING" in title.upper() and tid not in run.notified_findings:
                run.notified_findings.add(tid)
                effect = ""
                for line in notes.split("\n"):
                    if any(k in line.upper() for k in ("EFFECT_SIZE", "CI_95", "VALENCE")):
                        effect += f"\n  {line.strip()}"
                msg = f"🔬 *NEW FINDING*\n{title}"
                if effect:
                    msg += f"\n{effect}"
                events.append({"type": "finding", "msg": msg})

            # Surface serendipitous observations to the human
            serendipity_key = f"serendipity:{tid}"
            if serendipity_key not in run.notified_findings and "SERENDIPITY" in notes.upper():
                run.notified_findings.add(serendipity_key)
                # Extract the serendipity description from notes
                desc = ""
                for line in notes.split("\n"):
                    if "SERENDIPITY" in line.upper():
                        desc = line.split(":", 1)[-1].strip() if ":" in line else line.strip()
                        break
                if not desc:
                    desc = title
                events.append({
                    "type": "serendipity",
                    "msg": f"🔮 *Unexpected observation*\n{desc}\n"
                           f"_An agent found something outside the original scope._",
                })
        return events

    def _check_sentinel(self, run: RunningInvestigation) -> list[dict]:
        """Run experiment sentinel audit if a contract exists.

        Checks are event-driven (contract file mtime changed) plus periodic
        (every ``sentinel_interval_hours`` from config, default 6h).
        If the sentinel finds critical failures, it autonomously flags
        ``DESIGN_INVALID`` and sends an alert.

        Also detects:
        - Missing contract after first hour (at Analytical+ rigor)
        - Phase transitions via orchestrator checkpoint
        """
        events: list[dict] = []
        contract_path = run.workspace_path / ".swarm" / "experiment-contract.json"
        audit_path = run.workspace_path / ".swarm" / "sentinel-audit.json"

        # --- Missing contract detection ---
        # At Analytical+ rigor, if the orchestrator has created experiment tasks
        # but no contract after 1 hour, alert.
        if not contract_path.exists():
            elapsed_hours = (time.time() - run.started_at) / 3600
            if (elapsed_hours >= 1.0
                    and run.rigor in ("adaptive", "scientific", "experimental")
                    and self._has_experiment_tasks(run)
                    and not run._sentinel_missing_contract_warned):
                run._sentinel_missing_contract_warned = True
                events.append({
                    "type": "design_invalid",
                    "msg": (
                        "\U0001f6a8 *SENTINEL WARNING* — No experiment contract found\n"
                        "  Experiment tasks exist but `.swarm/experiment-contract.json` "
                        "is missing. The sentinel cannot validate outputs without a contract. "
                        "Write the contract NOW."
                    ),
                })
                # Write directive to force orchestrator to act
                self._write_directive(run, "sentinel_violation",
                    "SENTINEL WARNING: No experiment contract found after 1+ hour. "
                    "Write .swarm/experiment-contract.json before dispatching more workers. "
                    "See the Experiment Contract section in your prompt for the schema.")
            return events

        # --- Phase transition detection via checkpoint ---
        checkpoint_path = _find_checkpoint(run.workspace_path)
        checkpoint_phase = ""
        if checkpoint_path is not None:
            try:
                cp = json.loads(checkpoint_path.read_text())
                checkpoint_phase = cp.get("phase", "") if isinstance(cp, dict) else ""
            except (json.JSONDecodeError, OSError):
                pass

        last_audited_phase = ""
        if audit_path.exists():
            try:
                prev = json.loads(audit_path.read_text())
                last_audited_phase = prev.get("_last_phase", "") if isinstance(prev, dict) else ""
            except (json.JSONDecodeError, OSError):
                pass

        phase_changed = bool(checkpoint_phase and checkpoint_phase != last_audited_phase)

        # Decide whether to run: on contract change or periodically
        try:
            contract_mtime = contract_path.stat().st_mtime
        except OSError:
            return events

        last_audit_time = 0.0
        if audit_path.exists():
            try:
                last_audit_time = audit_path.stat().st_mtime
            except OSError:
                pass

        sentinel_interval = getattr(self.config, "sentinel_interval_hours", 6) * 3600
        now = time.time()
        contract_changed = contract_mtime > last_audit_time
        periodic_due = (now - last_audit_time) > sentinel_interval

        # Also trigger if any output file declared in the contract was recently modified
        output_changed = False
        try:
            from voronoi.science.gates import load_experiment_contract
            contract = load_experiment_contract(run.workspace_path)
            if contract:
                for ro in contract.required_outputs:
                    p = run.workspace_path / ro.get("path", "")
                    if p.exists():
                        try:
                            if p.stat().st_mtime > last_audit_time:
                                output_changed = True
                                break
                        except OSError:
                            pass
        except Exception:
            contract = None

        if not (contract_changed or periodic_due or output_changed or phase_changed):
            return events

        # Run the audit
        trigger = ("phase_transition" if phase_changed else
                   "contract_changed" if contract_changed else
                   "output_produced" if output_changed else "periodic")
        try:
            from voronoi.science.gates import validate_experiment_contract
            result = validate_experiment_contract(
                run.workspace_path, contract=contract, trigger=trigger)
        except Exception as exc:
            logger.debug("Sentinel audit failed for #%d: %s",
                         run.investigation_id, exc)
            return events

        # If phase changed, also run phase gate validation
        if phase_changed and contract and last_audited_phase:
            try:
                from voronoi.science.gates import validate_phase_gate
                pg_result = validate_phase_gate(
                    run.workspace_path, contract, last_audited_phase, checkpoint_phase)
                if not pg_result.passed:
                    for f in pg_result.critical_failures:
                        if f not in result.critical_failures:
                            result.critical_failures.append(f)
                    result.passed = result.passed and pg_result.passed
                    result.checks.extend(pg_result.checks)
            except Exception:
                pass

        # Persist phase in audit for next comparison
        try:
            audit_file = run.workspace_path / ".swarm" / "sentinel-audit.json"
            if audit_file.exists():
                audit_data = json.loads(audit_file.read_text())
                if isinstance(audit_data, dict):
                    audit_data["_last_phase"] = checkpoint_phase
                    audit_file.write_text(json.dumps(audit_data, indent=2))
        except (json.JSONDecodeError, OSError):
            pass

        if not result.passed:
            summary = result.failure_summary
            events.append({
                "type": "design_invalid",
                "msg": (
                    f"\U0001f6a8 *SENTINEL ALERT* — Experiment contract violated\n"
                    f"  {summary}"
                ),
            })
            logger.warning(
                "Sentinel audit FAILED for #%d: %s",
                run.investigation_id, summary,
            )

            # Write a dispatcher directive so the orchestrator is FORCED to act
            # on its next OODA cycle (the orchestrator already obeys directives).
            self._write_directive(run, "sentinel_violation",
                "SENTINEL ALERT: Experiment contract violated. "
                "Read .swarm/sentinel-audit.json for details. "
                "This IS a DESIGN_INVALID event — do NOT create a separate "
                "DESIGN_INVALID task. The sentinel has already flagged it. "
                "Do NOT proceed to the next phase or dispatch new workers. "
                "Dispatch Methodologist for post-mortem, then create a REVISE task.")
        else:
            logger.info(
                "Sentinel audit PASSED for #%d (trigger=%s, %d checks)",
                run.investigation_id, trigger, len(result.checks),
            )

        return events

    def _has_experiment_tasks(self, run: RunningInvestigation) -> bool:
        """Check if task_snapshot contains experiment-type tasks."""
        for t in run.task_snapshot.values():
            notes = t.get("notes", "")
            title = t.get("title", "").lower()
            if any(kw in title for kw in ("experiment", "phase", "baseline", "pilot",
                                           "factorial", "ablation", "benchmark")):
                return True
            if "TASK_TYPE=investigation" in notes or "TASK_TYPE=experiment" in notes:
                return True
        return False

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

        # Phases explicitly set by the orchestrator that must NOT be
        # overridden by file-existence heuristics.  These represent
        # intentional orchestrator states (gate pauses, design phases)
        # that would be incorrectly clobbered by stale files.
        _AUTHORITATIVE_PHASES = frozenset({
            "awaiting-human-gate", "design-review", "experiment-running",
            "pre-registration", "parked", "dispatching",
        })

        checkpoint_phase = ""
        if checkpoint:
            phase = checkpoint.get("phase", "")
            if isinstance(phase, str) and phase:
                run.phase = phase
                checkpoint_phase = phase
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

            # Detect rigor escalation (DISCOVER mode adaptive → scientific)
            checkpoint_rigor = checkpoint.get("rigor", "")
            if isinstance(checkpoint_rigor, str) and checkpoint_rigor:
                if (run.last_rigor
                        and checkpoint_rigor != run.last_rigor
                        and run.mode == "discover"):
                    from voronoi.gateway.progress import RIGOR_DESCRIPTIONS
                    desc = RIGOR_DESCRIPTIONS.get(checkpoint_rigor, checkpoint_rigor)
                    events.append({
                        "type": "rigor_escalation",
                        "msg": f"📐 *Rigor escalated* → {checkpoint_rigor}\n"
                               f"_{desc}_\n"
                               f"The investigation shifted from exploration to structured testing.",
                    })
                run.last_rigor = checkpoint_rigor
                # Sync effective rigor so completion gates use the escalated level
                if run.rigor == "adaptive" and checkpoint_rigor != "adaptive":
                    logger.info("Effective rigor for #%d escalated: %s → %s",
                                run.investigation_id, run.rigor, checkpoint_rigor)

        # File-existence heuristics: only apply when the checkpoint did not
        # report an authoritative phase.  Authoritative phases represent
        # intentional orchestrator states that stale files must not clobber.
        if checkpoint_phase not in _AUTHORITATIVE_PHASES:
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

        # Check for directionally reversed hypotheses (Analytical+ — Judgment Tribunal trigger)
        events.extend(self._check_reversed_hypotheses(run))

        return events

    def _latest_checkpoint(self, run: RunningInvestigation) -> dict | None:
        """Return the newest orchestrator checkpoint from the workspace or worktrees."""
        # Check both canonical and common LLM-shortened checkpoint names
        candidates: list[Path] = []
        for name in ("orchestrator-checkpoint.json", "checkpoint.json"):
            p = run.workspace_path / ".swarm" / name
            if p.exists():
                candidates.append(p)
        swarm_dir = self._swarm_dir(run.workspace_path)
        if swarm_dir:
            for path in sorted(swarm_dir.glob("agent-*")):
                if path.is_dir():
                    # Only look for the canonical orchestrator checkpoint name
                    # in worktrees — "checkpoint.json" is too generic and may
                    # match worker-internal state files.
                    p = path / ".swarm" / "orchestrator-checkpoint.json"
                    if p.exists():
                        candidates.append(p)

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

    def _check_reversed_hypotheses(self, run: RunningInvestigation) -> list[dict]:
        """Check for directionally reversed hypotheses (Judgment Tribunal trigger).

        When a hypothesis is marked refuted_reversed in the belief map and no
        tribunal verdict explains it, generates an interpretation request and
        alerts the PI.  This is the mid-run Tribunal trigger.
        """
        events: list[dict] = []
        try:
            from voronoi.science.interpretation import (
                has_reversed_hypotheses,
                generate_interpretation_request,
                save_interpretation_request,
            )
            has_reversed, descriptions = has_reversed_hypotheses(run.workspace_path)
            if not has_reversed:
                return events

            # Only alert for newly detected reversals
            new_reversals = [d for d in descriptions
                            if d not in run.notified_reversed_hypotheses]
            if not new_reversals:
                return events

            for desc in new_reversals:
                run.notified_reversed_hypotheses.add(desc)

            # Write interpretation request for the orchestrator
            # Extract hypothesis ID from the description if present
            import re
            h_match = re.search(r"Hypothesis (\S+)", new_reversals[0])
            h_id = h_match.group(1) if h_match else ""
            request = generate_interpretation_request(
                finding_id="",  # orchestrator will fill from context
                trigger="refuted_reversed",
                hypothesis_id=h_id,
            )
            save_interpretation_request(run.workspace_path, request)

            events.append({
                "type": "design_invalid",  # Use design_invalid type to trigger milestone messaging
                "msg": (
                    "⚠️ *Judgment Tribunal needed* — directionally reversed hypothesis detected\n"
                    + "\n".join(f"  • {d}" for d in new_reversals[:3])
                    + "\nThe result is statistically significant but in the *opposite* direction "
                    "of the prediction. A Tribunal (Theorist + Statistician + Methodologist) "
                    "must explain this before convergence."
                ),
            })
        except Exception as e:
            logger.debug("Reversed hypothesis check failed: %s", e)
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
            from voronoi.server.events import read_events
            total_count = 0
            total_tokens = 0
            total_failures = 0
            latest_ts = run.last_event_ts
            serendipity_events: list = []

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
                raw = read_events(root, since=since, max_events=500)
                if not raw:
                    continue
                total_count += len(raw)
                for e in raw:
                    total_tokens += e.tokens_used
                    if e.status == "fail":
                        total_failures += 1
                    if e.event == "serendipity":
                        serendipity_events.append(e)
                latest_ts = max(latest_ts, raw[-1].ts)
                run.last_event_ts_by_path[key] = raw[-1].ts

            if total_count == 0:
                return events
            run.last_event_ts = latest_ts

            # Surface serendipity events as milestone notifications
            for sev in serendipity_events:
                skey = f"serendipity_ev:{sev.task_id}:{sev.detail[:60]}"
                if skey not in run.notified_findings:
                    run.notified_findings.add(skey)
                    events.append({
                        "type": "serendipity",
                        "msg": f"🔮 *Unexpected observation*\n{sev.detail}\n"
                               f"_Agent {sev.agent} noticed something outside the plan._",
                    })

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

    def _synthesize_claim_deltas(self, run: RunningInvestigation) -> list[dict]:
        """Detect Claim Ledger changes since the last poll.

        Returns a list of synthetic events with ``type='claim_delta'`` describing
        new claims and status transitions.  The first invocation seeds
        ``run.last_ledger_map`` without emitting any events so existing claims
        are not re-surfaced after a dispatcher restart.
        """
        try:
            from voronoi.science.claims import (
                diff_ledger_states, ledger_state_map, load_ledger,
            )
        except Exception:
            return []
        try:
            inv = self.queue.get(run.investigation_id)
        except Exception:
            inv = None
        lineage_id = (inv.lineage_id if inv and inv.lineage_id is not None
                      else run.investigation_id)
        try:
            ledger = load_ledger(lineage_id, base_dir=self.config.base_dir)
        except Exception:
            return []

        current_map = ledger_state_map(ledger)
        if not run._ledger_baseline_seeded:
            run.last_ledger_map = current_map
            run._ledger_baseline_seeded = True
            return []

        deltas = diff_ledger_states(run.last_ledger_map, current_map, ledger=ledger)
        run.last_ledger_map = current_map

        events: list[dict] = []
        for d in deltas:
            events.append({
                "type": "claim_delta",
                "kind": d["kind"],
                "claim_id": d["claim_id"],
                "from_status": d.get("from_status"),
                "to_status": d["to_status"],
                "statement": d.get("statement", ""),
            })
        return events

    def _update_learning_activity(
        self, run: RunningInvestigation, events: list[dict],
    ) -> None:
        """Track learning progress and escalate via self-steer directives.

        A new finding or a claim status transition resets the activity timer
        AND the strike level — learning has resumed.  New-provisional claims
        alone do not reset it (a claim that never becomes asserted/locked is
        not learning).

        When the quiet window crosses a strike threshold, the dispatcher
        injects an escalating **self-steer directive** into the next
        orchestrator prompt (via ``.swarm/stall-signal.json``). Each strike
        adds a richer belief-snapshot and a concrete set of alternatives
        the orchestrator must choose between. Auto-park only fires at a
        fourth, internal level that requires an additional
        ``stall_final_grace_minutes`` window of silence past strike 3 —
        i.e. three explicit self-steer prompts had no effect.

          * Strike 1 (``stall_strike1_minutes``): directive
            ``diagnose_and_steer``. Telegram: LEARNING_STALLED.
          * Strike 2 (``stall_strike2_minutes``): directive
            ``pivot_or_declare``. Telegram: strike-2 with extend hint.
          * Strike 3 (``stall_strike3_minutes``): directive
            ``final_steer`` — final self-steer; run NOT killed yet.
          * Strike 4 (``stall_strike3_minutes + stall_final_grace_minutes``):
            directive ``auto_park`` — write partial deliverable, kill run.

        Each strike fires at most once per escalation sequence. Recovery
        (a real finding / claim transition) drops the level back to 0, so
        a later stall can escalate again from scratch.
        """
        now = time.time()
        if run.last_learning_activity_at == 0:
            run.last_learning_activity_at = now

        has_finding = any(e.get("type") == "finding" for e in events)
        has_claim_transition = any(
            e.get("type") == "claim_delta" and e.get("kind") == "transition"
            for e in events
        )
        has_task_done = any(e.get("type") == "task_done" for e in events)
        if has_finding or has_claim_transition:
            run.last_learning_activity_at = now
            if run.stall_strike_level > 0:
                run.stall_strike_level = 0
                self._clear_stall_signal(run)
            # Evidence-gated scaling: update epoch state on learning
            self._update_epoch_on_learning(run, events)
            return

        # Infra-progress credit: a task_done event (worker branch merged /
        # task closed) is productive work — reset the activity timer so the
        # stall clock restarts, but keep ``stall_strike_level`` intact so a
        # run that's been escalated still needs real learning to fully
        # recover. This prevents auto-park during hours-long build-out work
        # (encoder + evaluator + runner merges) where findings legitimately
        # cannot exist yet. See docs/SERVER.md §3.
        if has_task_done:
            run.last_learning_activity_at = now
            return

        # Do not cry stall before the orchestrator has produced anything at all
        if run.phase in ("starting", "scouting", "planning") and not run.task_snapshot:
            return

        # Honour explicit stall extension from /voronoi extend command.
        # The extension grants full immunity; findings during the extension
        # period do NOT consume the budget (unlike the old future-timestamp
        # hack).
        if run.stall_extension_expires_at and now < run.stall_extension_expires_at:
            return

        elapsed_min = (now - run.last_learning_activity_at) / 60

        # Phase-aware stall budgets: scale thresholds by a multiplier derived
        # from the orchestrator-declared ``lifecycle_phase`` in the checkpoint.
        multiplier = self._stall_phase_multiplier(run)
        strike1 = self.config.stall_strike1_minutes * multiplier
        strike2 = self.config.stall_strike2_minutes * multiplier
        strike3 = self.config.stall_strike3_minutes * multiplier
        # Strike 4 (auto-park) fires only after an additional grace window
        # past strike 3 — i.e. the orchestrator has had the final self-steer
        # prompt and still produced no learning. Grace is NOT scaled by the
        # phase multiplier: once in final-steer, every phase gets the same
        # bounded tail before termination.
        strike4 = strike3 + self.config.stall_final_grace_minutes

        # Determine the highest strike level the elapsed time now warrants.
        if elapsed_min >= strike4:
            target_level = 4
        elif elapsed_min >= strike3:
            target_level = 3
        elif elapsed_min >= strike2:
            target_level = 2
        elif elapsed_min >= strike1:
            target_level = 1
        else:
            target_level = 0

        # Escalate one step at a time so each strike's side-effects
        # (signal file write, Telegram notification, auto-park) fire.
        while run.stall_strike_level < target_level:
            run.stall_strike_level += 1
            self._fire_stall_strike(run, run.stall_strike_level, elapsed_min)
            if run.stall_strike_level >= 4:
                # Auto-park is terminal; do not escalate further.
                break

    # Phase-aware stall multipliers — applied to stall_strikeN_minutes at
    # comparison time in ``_update_learning_activity``. Mirrors the table in
    # docs/SERVER.md §3.
    _STALL_PHASE_MULTIPLIERS = {
        "setup": 3.0,
        "explore": 1.0,
        "test": 1.0,
        "synthesize": 0.5,
    }

    def _stall_phase_multiplier(self, run: RunningInvestigation) -> float:
        """Return the stall-threshold multiplier for the current lifecycle phase.

        Reads ``OrchestratorCheckpoint.lifecycle_phase`` from the workspace
        when set; otherwise infers a 2× grace for pre-task phases (starting,
        scouting, planning) and 1× for everything else.
        """
        try:
            from voronoi.science.convergence import load_checkpoint
            cp = load_checkpoint(run.workspace_path)
        except Exception:
            cp = None
        declared = (cp.lifecycle_phase or "").strip().lower() if cp else ""
        if declared in self._STALL_PHASE_MULTIPLIERS:
            return self._STALL_PHASE_MULTIPLIERS[declared]
        # Inferred fallback: coarse ``phase`` hints at pre-task state.
        if run.phase in ("starting", "scouting", "planning"):
            return 2.0
        return 1.0

    _STALL_STRIKE_DIRECTIVE = {
        1: {
            "directive": "diagnose_and_steer",
            "instruction": (
                "Learning stall detected — no finding or claim transition "
                "for the strike-1 window. This is your first self-steer "
                "prompt. Review the belief snapshot below, then on THIS "
                "OODA cycle pick exactly ONE action:\n"
                "  (a) Split the hardest open task into smaller, independently "
                "verifiable sub-tasks and dispatch them.\n"
                "  (b) Mark the task currently blocking progress as BLOCKED "
                "on its beads entry, then switch focus to an alternative "
                "hypothesis from your belief map.\n"
                "  (c) Declare a negative / null finding — evidence that the "
                "current path is NOT productive IS learning and resets this "
                "counter.\n"
                "Do NOT dispatch new planning tasks this cycle."
            ),
        },
        2: {
            "directive": "pivot_or_declare",
            "instruction": (
                "Previous self-steer did not produce a finding or claim "
                "transition. You must act decisively THIS cycle:\n"
                "  (a) Pivot — pick an alternative hypothesis from your "
                "belief map and dispatch an experiment task for it, OR\n"
                "  (b) Declare partial findings with whatever evidence "
                "currently exists on the ledger.\n"
                "Planning tasks remain forbidden. Indecision on this cycle "
                "escalates to the final self-steer directive."
            ),
        },
        3: {
            "directive": "final_steer",
            "instruction": (
                "FINAL self-steer. Two prior directives produced no learning. "
                "Emit AT MINIMUM one of the following on this cycle — any of "
                "these counts as learning and resets the escalator:\n"
                "  • A negative finding (evidence a path does not work).\n"
                "  • A claim status transition to BLOCKED or REFUTED on the "
                "ledger.\n"
                "  • A partial deliverable written to "
                "`.swarm/deliverable-partial.md` summarising what IS known.\n"
                "If no learning event is observed within the grace window "
                "that follows, the dispatcher will auto-park the run."
            ),
        },
        4: {
            "directive": "auto_park",
            "instruction": (
                "Auto-parked by dispatcher after strike 3 + grace window: "
                "zero learning despite three self-steer directives. Run is "
                "terminated. See .swarm/deliverable-partial.md."
            ),
        },
    }

    def _build_stall_diagnosis(
        self, run: RunningInvestigation, elapsed_min: float,
    ) -> dict:
        """Assemble the belief-snapshot injected into every strike signal.

        Mirrors what ``_write_partial_deliverable`` captures at terminal
        auto-park, but cheap enough to emit on every strike so the
        orchestrator always has concrete state to reason about when it
        reads the stall directive in its next prompt.
        """
        snapshot: dict = {
            "elapsed_minutes": round(elapsed_min, 1),
            "phase": run.phase,
        }
        try:
            from voronoi.science.convergence import load_checkpoint
            cp = load_checkpoint(run.workspace_path)
        except Exception:
            cp = None
        if cp is not None:
            if cp.lifecycle_phase:
                snapshot["lifecycle_phase"] = cp.lifecycle_phase
            if cp.active_workers:
                snapshot["active_workers"] = list(cp.active_workers)
            if cp.next_actions:
                # Cap to the first few so the prompt stays compact.
                snapshot["next_actions"] = list(cp.next_actions)[:5]
        # Open-task count (coarse but informative): count in-progress
        # and open tasks from the last task snapshot the dispatcher saw.
        if run.task_snapshot:
            open_count = 0
            in_progress_count = 0
            for t in run.task_snapshot.values():
                status = (t or {}).get("status", "")
                if status == "in_progress":
                    in_progress_count += 1
                elif status in ("open", "ready", "blocked"):
                    open_count += 1
            snapshot["tasks_in_progress"] = in_progress_count
            snapshot["tasks_open"] = open_count
        return snapshot

    def _fire_stall_strike(
        self, run: RunningInvestigation, level: int, elapsed_min: float,
    ) -> None:
        """Write stall-signal.json, notify, and (at level 4) auto-park.

        Levels 1–3 are self-steer directives: they inject a belief snapshot
        + concrete alternatives into the next orchestrator prompt. The run
        keeps going. Only level 4 — strike 3 threshold plus the final grace
        window — actually terminates the run.
        """
        spec = self._STALL_STRIKE_DIRECTIVE.get(level)
        if spec is None:
            return
        signal_path = run.workspace_path / ".swarm" / "stall-signal.json"
        try:
            signal_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "level": level,
                "directive": spec["directive"],
                "instruction": spec["instruction"],
                "elapsed_minutes": round(elapsed_min, 1),
                "timestamp": datetime.now(timezone.utc).isoformat(
                    timespec="seconds",
                ),
            }
            # Belief snapshot: only meaningful for self-steer levels (1–3).
            # At level 4 the run is terminating; the partial deliverable
            # captures final state instead.
            if level < 4:
                payload["diagnosis"] = self._build_stall_diagnosis(
                    run, elapsed_min,
                )
            signal_path.write_text(json.dumps(payload, indent=2))
        except OSError as e:
            logger.warning("Failed to write stall-signal.json for %s: %s",
                           run.label, e)

        if level == 1:
            # First strike keeps the familiar LEARNING_STALLED notification
            self.send_message(format_learning_stalled(run.label, elapsed_min))
        elif level == 2:
            self.send_message(
                f"🪫🪫 *{run.label}* — stall escalated (strike 2, "
                f"~{int(round(elapsed_min))}min). Self-steer directive: "
                f"pivot to an alternative hypothesis or declare partial "
                f"findings this cycle.\n\n"
                f"Reply `/voronoi extend {run.label} 60` to grant +60 "
                f"minutes before the final self-steer escalates."
            )
        elif level == 3:
            grace = self.config.stall_final_grace_minutes
            self.send_message(
                f"🪫🪫🪫 *{run.label}* — final self-steer directive "
                f"(strike 3, ~{int(round(elapsed_min))}min). "
                f"Orchestrator must emit a negative finding, a BLOCKED "
                f"declaration, or a partial deliverable this cycle. "
                f"Auto-park in ~{grace}min if no learning.\n\n"
                f"Reply `/voronoi extend {run.label} 60` to grant more "
                f"time."
            )
        elif level == 4:
            self.send_message(
                f"🪫🪫🪫🪫 *{run.label}* — NO_LEARNING auto-parked after "
                f"~{int(round(elapsed_min))}min with zero findings despite "
                f"three self-steer directives. Writing partial deliverable "
                f"and terminating run."
            )
            try:
                self._write_partial_deliverable(run, elapsed_min)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("Failed to write partial deliverable for %s: %s",
                               run.label, e)
            try:
                self._auto_park_stalled_run(run, elapsed_min)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("Failed to auto-park stalled run %s: %s",
                               run.label, e)

    def _clear_stall_signal(self, run: RunningInvestigation) -> None:
        """Remove .swarm/stall-signal.json when learning resumes."""
        signal_path = run.workspace_path / ".swarm" / "stall-signal.json"
        try:
            if signal_path.exists():
                signal_path.unlink()
        except OSError:
            pass

    # ── Evidence-gated scaling ────────────────────────────────────────

    def _update_epoch_on_learning(
        self, run: RunningInvestigation, events: list[dict],
    ) -> None:
        """Update epoch state when evidence-producing events arrive.

        Counts findings, detects belief-map confidence tier changes,
        and auto-advances the epoch when sufficient evidence accumulates.
        """
        from voronoi.science.convergence import (
            load_epoch_state, save_epoch_state, advance_epoch,
            load_belief_map,
        )

        epoch = load_epoch_state(run.workspace_path)

        # Count new findings
        finding_count = sum(1 for e in events if e.get("type") == "finding")
        epoch.findings_this_epoch += finding_count

        # Detect belief-map moves: compare current confidence tiers to snapshot
        bm = load_belief_map(run.workspace_path)
        moves = 0
        current_snapshot: dict[str, str] = {}
        for h in bm.hypotheses:
            current_snapshot[h.id] = h.confidence or "unknown"
            prior = run._prior_belief_snapshot.get(h.id, "unknown")
            if (h.confidence or "unknown") != prior:
                moves += 1
        run._prior_belief_snapshot = current_snapshot
        epoch.belief_map_moves += moves

        # Auto-advance epoch if we have evidence and haven't hit max cap
        if epoch.has_evidence and epoch.max_tranches < self.config.max_agents:
            epoch = advance_epoch(epoch, configured_max=self.config.max_agents)
            logger.info(
                "Investigation #%d advanced to epoch %d (cap: %d tranches)",
                run.investigation_id, epoch.epoch, epoch.max_tranches,
            )
            self.send_message(
                f"📈 *{run.label}* — evidence produced! "
                f"Scaling to epoch {epoch.epoch} "
                f"(now up to {epoch.max_tranches} parallel tranches)."
            )

        save_epoch_state(run.workspace_path, epoch)

    def _write_failure_diagnosis(self, run: RunningInvestigation) -> None:
        """Write structured failure diagnosis for stalled/failed investigations."""
        from voronoi.science.convergence import (
            build_failure_diagnosis, save_failure_diagnosis,
        )
        try:
            diagnosis = build_failure_diagnosis(run.workspace_path)
            save_failure_diagnosis(run.workspace_path, diagnosis)
        except Exception as e:
            logger.warning("Failed to write failure diagnosis for %s: %s",
                           run.label, e)

    def _write_partial_deliverable(
        self, run: RunningInvestigation, elapsed_min: float,
    ) -> None:
        """Emit ``.swarm/deliverable-partial.md`` on auto-park.

        Best-effort: list current claims from the ledger (if any) and the
        success-criteria state so the PI has a record of what the run knew.
        """
        path = run.workspace_path / ".swarm" / "deliverable-partial.md"
        path.parent.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        lines.append(f"# {run.label} — Partial Deliverable (auto-parked)\n")
        lines.append(
            f"**Reason:** No new findings or claim transitions for "
            f"~{int(round(elapsed_min))} minutes "
            f"(stall_strike3_minutes={self.config.stall_strike3_minutes}).\n"
        )
        lines.append(f"**Mode:** {run.mode}  |  **Phase:** {run.phase}\n")

        # Ledger claims (if available)
        inv = self.queue.get(run.investigation_id) if self._queue else None
        if inv is not None and getattr(inv, "lineage_id", None):
            try:
                from voronoi.science.claims import load_ledger
                ledger = load_ledger(inv.lineage_id, base_dir=self.config.base_dir)
                if ledger.claims:
                    lines.append("\n## Claims in Ledger\n")
                    for c in ledger.claims:
                        lines.append(f"- **{c.id}** ({c.status}): {c.statement}\n")
                else:
                    lines.append("\n## Claims in Ledger\n\n*None.*\n")
            except Exception as e:  # pragma: no cover - defensive
                logger.debug("Ledger load for partial deliverable failed: %s", e)

        # Success criteria
        sc_path = run.workspace_path / ".swarm" / "success-criteria.json"
        if sc_path.exists():
            try:
                sc = json.loads(sc_path.read_text())
                if isinstance(sc, list):
                    met = sum(1 for s in sc if s.get("met"))
                    lines.append(
                        f"\n## Success Criteria\n\n{met}/{len(sc)} met at park time.\n"
                    )
                    for s in sc:
                        mark = "x" if s.get("met") else " "
                        lines.append(
                            f"- [{mark}] **{s.get('id','?')}** — {s.get('description','')}\n"
                        )
            except (OSError, json.JSONDecodeError):
                pass

        # Orchestrator checkpoint — what was the agent about to do?
        # This turns "the log is 391 lines, go dig" into a one-glance answer.
        try:
            from voronoi.science.convergence import load_checkpoint
            cp = load_checkpoint(run.workspace_path)
        except Exception:
            cp = None
        if cp is not None and (cp.active_workers or cp.next_actions):
            lines.append("\n## Where The Run Was Headed\n")
            if cp.active_workers:
                lines.append(
                    "\n**Active workers at park time:** "
                    f"{', '.join(cp.active_workers)}\n"
                )
            if cp.next_actions:
                lines.append("\n**Planned next actions:**\n")
                for a in cp.next_actions:
                    lines.append(f"- {a}\n")

        path.write_text("".join(lines))

    def extend_run(
        self, identifier: str, minutes: int = 60,
    ) -> str:
        """Human-in-the-loop stall extension.

        Pushes ``last_learning_activity_at`` forward by ``minutes`` minutes,
        drops ``stall_strike_level`` back to 0, and clears
        ``.swarm/stall-signal.json`` so the next prompt build contains no
        stall directive. Invoked by ``handle_extend`` in response to
        ``/voronoi extend <codename> [minutes]`` — the strike-2 notification
        prompts the PI with this exact command. See docs/SERVER.md §3.
        """
        if minutes <= 0:
            return "❌ `minutes` must be positive."
        # Resolve the target run: match by codename (case-insensitive) or id.
        needle = identifier.strip().lower()
        target: Optional[RunningInvestigation] = None
        for run in self.running.values():
            if (run.codename or "").lower() == needle:
                target = run
                break
            if f"#{run.investigation_id}" == needle or str(run.investigation_id) == needle:
                target = run
                break
        if target is None:
            return f"❌ No running investigation matches *{identifier}*."
        # Grant the extension: set explicit immunity expiry, reset strikes,
        # clear signal.  The activity timer is NOT pushed into the future —
        # that would be silently consumed by the next finding event.
        target.stall_extension_expires_at = time.time() + minutes * 60
        target.last_learning_activity_at = time.time()
        prior_level = target.stall_strike_level
        target.stall_strike_level = 0
        self._clear_stall_signal(target)
        logger.info(
            "Investigation #%d (%s): extended by %d min (strike level was %d)",
            target.investigation_id, target.label, minutes, prior_level,
        )
        return (
            f"⏱ *{target.label}* — granted +{minutes} min stall budget. "
            f"Strike level reset (was {prior_level}). Agent will see a "
            f"clean prompt on the next build."
        )

    def _auto_park_stalled_run(
        self, run: RunningInvestigation, elapsed_min: float,
    ) -> None:
        """Kill the tmux session and mark the investigation failed on strike 3."""
        # Write structured diagnosis before killing the session
        self._write_failure_diagnosis(run)
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", run.tmux_session],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass
        reason = (
            f"Auto-parked: no learning for ~{int(round(elapsed_min))} minutes "
            f"(stall strike 3)."
        )
        try:
            self.queue.fail(run.investigation_id, reason)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("queue.fail() raised for auto-parked %s: %s",
                           run.label, e)
        self.running.pop(run.investigation_id, None)

    def _send_progress_batch(self, run: RunningInvestigation, events: list[dict]) -> None:
        # Synthesize claim-delta events from the persistent claim ledger
        claim_events = self._synthesize_claim_deltas(run)
        if claim_events:
            events = list(events) + claim_events

        # Track learning activity for LEARNING_STALLED detection
        self._update_learning_activity(run, events)

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

        # Persist notification state so it survives dispatcher restarts
        run.save_notification_state()

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

    _CONVERGED_STATUSES = frozenset({
        "converged", "exhausted", "diminishing_returns", "negative_result",
    })

    @staticmethod
    def _convergence_status_ok(data: dict) -> bool:
        """Check if convergence.json data indicates completion.

        Case-insensitive: agents may write 'CONVERGED' or 'converged'.
        """
        if data.get("converged", False):
            return True
        status = data.get("status", "")
        if isinstance(status, str):
            return status.lower() in InvestigationDispatcher._CONVERGED_STATUSES
        return False

    def _effective_rigor(self, run: RunningInvestigation) -> str:
        """Return the effective rigor for an investigation.

        If adaptive rigor has been escalated (tracked via checkpoint rigor
        updates in ``_detect_phase``), return the escalated level so that
        completion gates match the actual rigor in effect.
        """
        if run.rigor == "adaptive" and run.last_rigor and run.last_rigor != "adaptive":
            return run.last_rigor
        return run.rigor

    def _is_complete(self, run: RunningInvestigation, *,
                     session_dead: bool = False) -> bool:
        # HARD GATE: never complete while DESIGN_INVALID tasks are open
        if self._has_open_design_invalid(run):
            return False

        effective_rigor = self._effective_rigor(run)

        if (run.workspace_path / ".swarm" / "deliverable.md").exists():
            # For adaptive rigor (not yet escalated), deliverable is sufficient
            if effective_rigor == "adaptive":
                return True
            # For higher rigor, also need convergence signal
            conv = run.workspace_path / ".swarm" / "convergence.json"
            if conv.exists():
                try:
                    data = json.loads(conv.read_text())
                    if isinstance(data, dict) and self._convergence_status_ok(data):
                        return True
                except (json.JSONDecodeError, OSError):
                    pass
            # Deliverable exists but no convergence signal — attempt to
            # generate one and re-check immediately (so we don't need to
            # wait for the next poll cycle, which may never come if the
            # agent already exited normally).
            # Throttle to avoid running the convergence gate script every
            # poll cycle (30s) when the gate consistently fails.
            # When session_dead=True, bypass the cooldown — no more artifacts
            # will be produced, so we must check now or never.
            now = time.time()
            cooldown_ok = (now - run.last_convergence_attempt_at >= 300)
            if cooldown_ok or session_dead:
                run.last_convergence_attempt_at = now
                self._try_convergence_check(run)
            if conv.exists():
                try:
                    data = json.loads(conv.read_text())
                    if isinstance(data, dict) and self._convergence_status_ok(data):
                        return True
                except (json.JSONDecodeError, OSError):
                    pass
            return False
        conv = run.workspace_path / ".swarm" / "convergence.json"
        if conv.exists():
            try:
                data = json.loads(conv.read_text())
                if isinstance(data, dict) and self._convergence_status_ok(data):
                    return True
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
            effective_rigor = self._effective_rigor(run)
            result = check_convergence(
                run.workspace_path, effective_rigor,
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
                            [str(gate_script), str(run.workspace_path), effective_rigor],
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
        # HARD GATE: refuse to declare success while DESIGN_INVALID is open.
        # Mark as failed so the investigation doesn't become a zombie —
        # the agent session is already dead at this point.
        if not failed and self._has_open_design_invalid(run):
            logger.warning("Completion blocked for %s: DESIGN_INVALID tasks still open",
                           run.label)
            self.send_message(format_alert(
                run.label,
                "Completion blocked — experiments flagged as DESIGN_INVALID are still open. "
                "Fix the design and re-run."
            ))
            failed = True
            failure_reason = "DESIGN_INVALID tasks still open at completion"

        elapsed = (time.time() - run.started_at) / 60
        total_tasks = len(run.task_snapshot)
        closed = sum(1 for t in run.task_snapshot.values() if t["status"] == "closed")

        # If task_snapshot is empty (e.g. after dispatcher restart), try to
        # restore from beads so the completion message isn't misleading (0/0).
        if total_tasks == 0:
            try:
                result = subprocess.run(
                    ["bd", "list", "--json"],
                    capture_output=True, text=True, timeout=10,
                    cwd=str(run.workspace_path),
                )
                if result.returncode == 0 and result.stdout.strip():
                    tasks = json.loads(result.stdout)
                    if isinstance(tasks, list):
                        total_tasks = len(tasks)
                        closed = sum(1 for t in tasks
                                     if isinstance(t, dict) and t.get("status") == "closed")
            except (subprocess.TimeoutExpired, json.JSONDecodeError,
                    FileNotFoundError, OSError):
                pass

        # Second fallback: read .beads/ JSONL directly when bd CLI unavailable
        if total_tasks == 0:
            beads_dir = run.workspace_path / ".beads"
            if beads_dir.is_dir():
                try:
                    for jsonl_file in beads_dir.glob("*.jsonl"):
                        for line in jsonl_file.read_text(errors="replace").splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            try:
                                entry = json.loads(line)
                                if isinstance(entry, dict) and "id" in entry:
                                    total_tasks += 1
                                    if entry.get("status") == "closed":
                                        closed += 1
                            except json.JSONDecodeError:
                                continue
                except OSError:
                    pass

        # Always clean up tmux sessions on completion
        self._cleanup_tmux(run)

        if failed:
            logger.warning("Voronoi %s (#%d) FAILED: %s (%d/%d tasks in %.1fmin)",
                          run.label, run.investigation_id, failure_reason,
                          closed, total_tasks, elapsed)
            self.queue.fail(run.investigation_id, failure_reason)

            # Write structured failure diagnosis for continuation rounds
            self._write_failure_diagnosis(run)

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

        # Detect valid negative result from convergence status
        is_negative_result = False
        conv_reason = ""
        conv_path = run.workspace_path / ".swarm" / "convergence.json"
        if conv_path.exists():
            try:
                conv_data = json.loads(conv_path.read_text())
                if isinstance(conv_data, dict):
                    status = conv_data.get("status", "")
                    if isinstance(status, str) and status.lower() == "negative_result":
                        is_negative_result = True
                        conv_reason = conv_data.get("reason", "")
            except (json.JSONDecodeError, OSError):
                pass

        # Science investigations go to review for PI feedback;
        # build-mode investigations complete immediately.
        is_science = run.mode in ("discover", "prove")
        if is_science:
            if not self._transition_to_review(run):
                # Review transition failed — fall back to complete so the
                # investigation doesn't stay as a zombie "running" row.
                logger.warning("Review transition failed for %s — falling back to complete",
                               run.label)
                self.queue.complete(run.investigation_id)
        else:
            self.queue.complete(run.investigation_id)

        # Write the structured Run Manifest — canonical machine-readable record
        # of the run's claims, experiments, artifacts, and provenance.  Written
        # AFTER the status transition so the manifest captures the finalized
        # ledger state (promoted claims, self-critique objections, continuation
        # proposals).  If the dispatcher crashes between the status transition
        # and this write, _recover_running will sweep for the missing manifest
        # on the next startup (INV-44).
        self._write_run_manifest(run)

        # Send appropriate completion message
        from voronoi.gateway.report import ReportGenerator
        rg = ReportGenerator(run.workspace_path, mode=run.mode,
                             rigor=self._effective_rigor(run))
        if is_negative_result:
            neg_msg = format_negative_result(
                codename=run.label,
                elapsed_sec=time.time() - run.started_at,
                closed=closed,
                total=total_tasks,
                eval_score=run.eval_score,
                reason=conv_reason,
            )
            self.send_message(neg_msg)
        else:
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

        # Sync findings to federated knowledge index
        try:
            from voronoi.gateway.knowledge import FederatedKnowledge
            fk = FederatedKnowledge(self.config.base_dir / "knowledge.db")
            fk.sync_findings(
                str(run.investigation_id), run.codename, run.workspace_path,
            )
        except Exception as e:
            logger.debug("Federated knowledge sync failed: %s", e)

        # Clean up agent worktrees (the -swarm/ directory)
        self._cleanup_worktrees(run)

    def _cleanup_worktrees(self, run: RunningInvestigation) -> None:
        """Remove agent worktrees after investigation completion.

        The swarm directory (active/<slug>-swarm/) contains git worktrees
        created by spawn-agent.sh for each worker agent.  After completion,
        these should be pruned and the directory removed.
        """
        ws = run.workspace_path
        swarm_dir = ws.parent / f"{ws.name}-swarm"

        # 1. Prune stale worktrees from git's perspective
        try:
            subprocess.run(
                ["git", "worktree", "prune"],
                cwd=str(ws), capture_output=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

        # 2. Remove individual worktree directories via git worktree remove
        if swarm_dir.exists():
            try:
                for child in sorted(swarm_dir.iterdir()):
                    if child.is_dir() and (child / ".git").exists():
                        try:
                            subprocess.run(
                                ["git", "worktree", "remove", "--force", str(child)],
                                cwd=str(ws), capture_output=True, timeout=30,
                            )
                        except (subprocess.TimeoutExpired, OSError):
                            pass
            except OSError:
                pass

            # 3. Remove the swarm directory if empty or only has stale content
            try:
                remaining = list(swarm_dir.iterdir())
                if not remaining:
                    swarm_dir.rmdir()
                else:
                    # Force remove — worktrees are expendable after completion
                    shutil.rmtree(swarm_dir, ignore_errors=True)
            except OSError:
                pass

            logger.info("Cleaned up worktrees for %s", run.label)

        # 4. Clean secrets env file (sibling of workspace, outside the git
        # repo — see tmux.py / INV-31).  The shell also ``rm -f``s it
        # immediately after sourcing, so this is belt-and-suspenders for
        # crashes before that step runs.
        env_file = ws.parent / f".tmux-env-{run.tmux_session}"
        if env_file.exists():
            try:
                env_file.unlink()
            except OSError:
                pass

        # Legacy cleanup: remove any residual secrets file from the old
        # in-workspace location that may have been left by a prior
        # dispatcher version.
        legacy_env = ws / ".swarm" / ".tmux-env"
        if legacy_env.exists():
            try:
                legacy_env.unlink()
            except OSError:
                pass

        # 5. Clean shared tmp directory if no other investigations are running
        if not self.running or (
            len(self.running) == 1
            and run.investigation_id in self.running
        ):
            tmp_dir = self.config.base_dir / "tmp"
            if tmp_dir.exists():
                try:
                    shutil.rmtree(tmp_dir, ignore_errors=True)
                    tmp_dir.mkdir(exist_ok=True)
                    logger.info("Cleaned tmp directory")
                except OSError:
                    pass

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
        # Legacy markers (pre-2026 CLI) + current markers.
        # Require >= 2 hits to avoid false positives from random log lines.
        markers = (
            "logout",
            "total session time",
            "total usage est",
            "breakdown by ai model",
            # Current Copilot CLI (2026+) output format
            "session exported to",
            "requests",
            "tokens",
        )
        return sum(marker in lowered for marker in markers) >= 2

    def _bd_in_progress_task_ids(self, workspace: Path) -> list[str]:
        """Return Beads task IDs currently marked ``in_progress``.

        Used by ``_has_active_workers`` to reconcile a possibly-stale
        ``orchestrator-checkpoint.json`` against ground-truth task state
        (BUG-002).  Returns an empty list on any failure — the caller
        treats absence of bd data as "no extra workers to track".
        """
        try:
            from voronoi.beads import has_beads_dir, run_bd_json
            if not has_beads_dir(str(workspace)):
                return []
            code, parsed = run_bd_json(
                "list", "--status", "in_progress", "--json",
                cwd=str(workspace),
            )
        except Exception:  # pragma: no cover — beads module optional
            return []
        if code != 0 or not isinstance(parsed, list):
            return []
        ids: list[str] = []
        for task in parsed:
            if not isinstance(task, dict):
                continue
            tid = task.get("id")
            if isinstance(tid, str) and tid:
                ids.append(tid)
        return ids

    def _has_active_workers(self, run: RunningInvestigation) -> bool:
        """Check if the orchestrator exited with workers still running.

        Reads the checkpoint for ``active_workers`` and checks if any of
        those tmux windows are still alive in the swarm session.  Also
        checks for orphaned copilot processes whose cwd is inside the
        workspace (workers that survived after tmux cleanup).  If so,
        the orchestrator intentionally exited to conserve context and
        should NOT be restarted until the workers finish.

        Reconciles the checkpoint against Beads in-progress tasks
        (BUG-002): a stale checkpoint with ``active_workers=[]`` while
        bd reports ``in_progress`` tasks used to produce duplicate
        worker dispatch on restart.  We now cross-check both sources.
        """
        cp_path = _find_checkpoint(run.workspace_path)
        if cp_path is None:
            return False
        try:
            cp = json.loads(cp_path.read_text())
            if not isinstance(cp, dict):
                return False
        except (json.JSONDecodeError, OSError):
            return False

        # Coerce active_workers to list[str].  The spec types this as a list
        # of task-id strings, but the orchestrator writes the checkpoint
        # directly (bypassing MCP validation), and has been observed emitting
        # list[dict] entries like [{"id": "bd-123", "branch": "..."}].  Such
        # values would crash the downstream `worker in w` substring match
        # with "'in <string>' requires string as left operand, not dict".
        # Extract a string identifier from dict entries; drop anything else.
        raw_workers = cp.get("active_workers", [])
        workers: list[str] = []
        if isinstance(raw_workers, list):
            for item in raw_workers:
                if isinstance(item, str) and item:
                    workers.append(item)
                elif isinstance(item, dict):
                    for key in ("id", "task_id", "branch", "worker", "name"):
                        v = item.get(key)
                        if isinstance(v, str) and v:
                            workers.append(v)
                            break
        if workers and not all(isinstance(w, str)
                               for w in raw_workers if w is not None):
            logger.warning(
                "Investigation %s: checkpoint active_workers contained "
                "non-string entries; coerced to %r",
                run.label, workers,
            )

        # Reconcile with Beads: any in_progress task whose ID isn't already
        # covered by the checkpoint means a worker was dispatched but the
        # checkpoint is stale.  We add the task ID as a potential worker
        # identifier — tmux window names typically encode the task ID, so
        # the downstream substring match ("worker in w") will find it.
        for tid in self._bd_in_progress_task_ids(run.workspace_path):
            if tid and not any(tid in w for w in workers):
                workers.append(tid)

        if not workers:
            return False

        # Read the actual swarm session name from .swarm-config.json
        # (swarm-init.sh writes it as ${PROJECT_NAME}-swarm, which differs
        # from the dispatcher's session naming).
        swarm_session = None
        config_path = run.workspace_path / ".swarm-config.json"
        try:
            cfg = json.loads(config_path.read_text())
            if isinstance(cfg, dict):
                swarm_session = cfg.get("tmux_session")
        except (json.JSONDecodeError, OSError):
            pass
        if not swarm_session:
            swarm_session = run.tmux_session + "-swarm"
        # Check if the swarm tmux session exists at all (once, not per-worker)
        try:
            result = subprocess.run(
                ["tmux", "has-session", "-t", swarm_session],
                capture_output=True, timeout=5,
            )
            if result.returncode != 0:
                # Session gone — skip to orphan check
                workers = []
        except (subprocess.TimeoutExpired, OSError):
            workers = []

        for worker in workers:
            try:
                # Check for a window matching this worker AND verify the
                # process inside the pane is still a copilot/agent process,
                # not a dead shell.  tmux windows survive after the foreground
                # process exits, leaving an idle bash prompt — we must not
                # treat those as "alive".
                result = subprocess.run(
                    ["tmux", "list-windows", "-t", swarm_session, "-F",
                     "#{window_name}"],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode != 0:
                    continue
                windows = result.stdout.strip().splitlines()
                if not any(worker in w for w in windows):
                    continue
                # Window exists — now check if the pane process is still
                # an agent (not just a leftover shell)
                pane_result = subprocess.run(
                    ["tmux", "list-panes", "-t",
                     f"{swarm_session}:{worker}", "-F",
                     "#{pane_current_command}"],
                    capture_output=True, text=True, timeout=5,
                )
                if pane_result.returncode == 0:
                    cmds = pane_result.stdout.strip().splitlines()
                    # A live worker has an agent process (copilot, claude,
                    # node, python, etc.) — not a bare shell
                    shell_names = {"bash", "zsh", "sh", "fish", "dash",
                                   "csh", "tcsh", "ksh", "login"}
                    if any(c.strip() and c.strip() not in shell_names
                           for c in cmds):
                        logger.debug("Worker %s still alive for %s "
                                     "(pane_cmd=%s)",
                                     worker, run.label,
                                     cmds[0] if cmds else "?")
                        return True
                    else:
                        logger.debug("Worker %s window exists but process "
                                     "exited (pane_cmd=%s) for %s",
                                     worker,
                                     cmds[0] if cmds else "?",
                                     run.label)
            except (subprocess.TimeoutExpired, OSError):
                continue

        # Fallback: check for orphaned copilot processes associated with
        # this workspace (workers that outlived their tmux window).  We
        # first grep argv for the workspace path, then fall back to
        # inspecting each PID's CWD via ``lsof`` — many agent CLIs
        # (copilot, claude, gemini) get the workspace as CWD, not argv,
        # so the argv-only check silently misses them (BUG-004).
        # ``pgrep -f`` (not ``-fa``) — macOS BSD pgrep lacks the ``-a`` flag.
        ws_str = str(run.workspace_path)
        try:
            result = subprocess.run(
                ["pgrep", "-f", self.config.agent_command],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                pids = [p.strip() for p in result.stdout.strip().splitlines()
                        if p.strip()]
                if pids:
                    ps_result = subprocess.run(
                        ["ps", "-p", ",".join(pids), "-o", "pid=,command="],
                        capture_output=True, text=True, timeout=10,
                    )
                    if ps_result.returncode == 0:
                        candidate_pids: list[str] = []
                        for line in ps_result.stdout.strip().splitlines():
                            parts = line.strip().split(None, 1)
                            if not parts:
                                continue
                            pid_str = parts[0]
                            cmdline = parts[1] if len(parts) > 1 else ""
                            if ws_str in cmdline:
                                logger.debug("Orphaned worker process "
                                             "(argv match) for %s: %s",
                                             run.label, line[:120])
                                return True
                            candidate_pids.append(pid_str)
                        # argv didn't match — check CWD for each candidate.
                        if candidate_pids and self._any_pid_cwd_in_workspace(
                                candidate_pids, run.workspace_path):
                            return True
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            pass

        # No live workers found — workers finished, proceed with restart
        logger.info("All active_workers done for %s, proceeding with restart",
                    run.label)
        return False

    def _any_pid_cwd_in_workspace(self, pids: list[str],
                                   workspace_path: Path) -> bool:
        """Return True if any PID's current working directory is inside
        ``workspace_path`` (or a subdirectory, e.g. a worktree).

        Uses ``lsof -a -p <pid> -d cwd -Fn`` which works on macOS and Linux
        and emits ``n<path>`` lines for the CWD entry.  Missing ``lsof`` or
        any per-PID failure is treated as "no match" — callers should
        already have covered the common case via argv substring matching.
        """
        if not pids:
            return False
        ws_resolved = workspace_path.resolve()
        for pid in pids:
            try:
                result = subprocess.run(
                    ["lsof", "-a", "-p", pid, "-d", "cwd", "-Fn"],
                    capture_output=True, text=True, timeout=5,
                )
            except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
                return False  # lsof unavailable — bail out of the fallback
            if result.returncode != 0:
                continue
            for line in result.stdout.splitlines():
                if not line.startswith("n"):
                    continue
                cwd_str = line[1:].strip()
                if not cwd_str:
                    continue
                try:
                    cwd = Path(cwd_str).resolve()
                except OSError:
                    continue
                if cwd == ws_resolved or ws_resolved in cwd.parents:
                    logger.debug("Orphaned worker process (cwd match) "
                                 "pid=%s cwd=%s workspace=%s",
                                 pid, cwd, ws_resolved)
                    return True
        return False

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
        return sum(marker in lowered for marker in auth_markers) >= 3

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

            effective_rigor = self._effective_rigor(run)
            result = check_convergence(
                run.workspace_path,
                effective_rigor,
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

    def _needs_orchestrator(self, run: RunningInvestigation) -> bool:
        """Decide whether to wake the parked orchestrator.

        Called each poll cycle while the orchestrator is parked (exited
        intentionally with ``active_workers``).  Returns True if an event
        has occurred that requires the orchestrator's scientific judgment:

        - All active workers have finished (normal wake)
        - DESIGN_INVALID detected in any open task (urgent)
        - Workers are no longer alive (process died)

        Findings and serendipity are accumulated in ``pending_events`` and
        delivered in the resume prompt — they do NOT trigger an immediate
        wake because they are not time-sensitive.
        """
        # 1. Are any workers still alive?
        if not self._has_active_workers(run):
            logger.info("All workers done for %s, waking orchestrator", run.label)
            return True

        # 2. DESIGN_INVALID in any open task (urgent — needs strategic response)
        from voronoi.beads import run_bd_json
        code, tasks = run_bd_json("list", "--json", cwd=str(run.workspace_path))
        if code == 0 and isinstance(tasks, list):
            for task in tasks:
                if not isinstance(task, dict):
                    continue
                tid = task.get("id", "")
                notes = task.get("notes", "")
                status = task.get("status", "")
                if (status != "closed"
                        and "DESIGN_INVALID" in notes.upper()
                        and tid not in run.notified_design_invalid):
                    logger.warning("DESIGN_INVALID detected in %s while parked — "
                                   "waking orchestrator", tid)
                    return True

        return False

    def _accumulate_parked_events(self, run: RunningInvestigation,
                                  events: list[dict]) -> None:
        """Accumulate events while the orchestrator is parked.

        These events are included in the resume prompt when the
        orchestrator is relaunched.
        """
        for event in events:
            etype = event.get("type", "")
            # Skip raw progress bar events — only accumulate meaningful ones
            if etype in ("task_done", "task_new", "task_started",
                         "finding", "serendipity", "design_invalid",
                         "phase", "rigor_escalation"):
                run.pending_events.append(event)
        # Cap at 50 to avoid unbounded growth
        if len(run.pending_events) > 50:
            run.pending_events = run.pending_events[-50:]

    def _wake_from_park(self, run: RunningInvestigation) -> bool:
        """Wake a parked orchestrator without consuming crash-retry budget.

        Unlike ``_try_restart`` (crash recovery), this is the normal wake
        path when workers finish or an urgent event is detected while the
        orchestrator is parked.  It does NOT increment ``retry_count``.

        Returns True if the orchestrator was successfully relaunched.
        """
        run.orchestrator_parked = False
        run.park_entered_at = 0
        run.polling_strike_count = 0

        # Ensure original orchestrator prompt exists
        prompt_file = run.workspace_path / ".swarm" / "orchestrator-prompt.txt"
        if not prompt_file.exists():
            logger.error("Prompt file missing for #%d — cannot wake",
                         run.investigation_id)
            return False

        # Compact workspace state before building resume prompt
        try:
            from voronoi.server.compact import compact_workspace_state
            compact_workspace_state(run.workspace_path)
        except Exception:
            pass

        resume_file = self._build_resume_prompt(run)

        # Rotate the log file so the new session starts clean
        if run.log_path.exists():
            rotated = run.log_path.with_suffix(".wake.log")
            try:
                run.log_path.rename(rotated)
            except OSError:
                pass

        n_events = len(run.pending_events)
        self.send_message(format_wake(
            run.label,
            n_events=n_events,
        ))

        try:
            self._launch_in_tmux(run.tmux_session, run.workspace_path,
                                 prompt_file=resume_file,
                                 rigor=self._effective_rigor(run))
            run.stall_warned = False
            run.context_directive_level = ""
            logger.info("Investigation #%d woke from park (pending_events=%d)",
                        run.investigation_id, n_events)
            return True
        except Exception as e:
            logger.error("Failed to wake #%d from park: %s",
                         run.investigation_id, e)
            return False

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

        # Compact workspace state BEFORE building resume prompt so the
        # state digest is fresh (avoids stale 0/13-met vs 7/13-met mismatches)
        try:
            from voronoi.server.compact import compact_workspace_state
            compact_workspace_state(run.workspace_path)
        except Exception:
            pass

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
                                 prompt_file=resume_file,
                                 rigor=self._effective_rigor(run))
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
        If workers are still running in the workspace, enters park mode
        instead of launching a new orchestrator session — preventing the
        common failure where a resumed orchestrator idle-polls while
        waiting for active workers.

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

        label = inv.codename or f"#{inv.id}"

        # Park-aware resume: if workers are still running, enter park
        # mode instead of launching a new orchestrator that would just
        # idle-poll for worker completion.
        if self._has_active_workers(run):
            run.orchestrator_parked = True
            run.park_entered_at = time.time()
            run.last_parked_digest_at = time.time()
            self.running[inv.id] = run
            self.send_message(
                f"▶️ *{label}* resumed in monitor mode — "
                f"workers still running, will wake when they finish."
            )
            logger.info("Investigation #%d (%s) resumed in park mode — "
                        "workers still running", inv.id, label)
            return (
                f"▶️ *{label}* resumed in monitor mode — "
                f"workers still running."
            )

        # Build resume prompt and launch
        resume_file = self._build_resume_prompt(run)
        try:
            self._launch_in_tmux(run.tmux_session, run.workspace_path,
                                 prompt_file=resume_file,
                                 rigor=self._effective_rigor(run))
        except Exception as e:
            logger.error("Failed to resume #%d: %s", inv.id, e)
            self.queue.fail(inv.id, f"Resume launch failed: {e}")
            return f"❌ Failed to launch #{investigation_id}: {e}"

        self.running[inv.id] = run
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
            paused_since = inv.completed_at or inv.started_at
            if not paused_since:
                continue
            paused_hours = (time.time() - paused_since) / 3600
            if paused_hours >= self.config.pause_timeout_hours:
                logger.warning("Paused investigation #%d timed out after %.1fh",
                               inv.id, paused_hours)
                # Atomic transition: paused → failed (no intermediate running state)
                self.queue.fail_paused(inv.id,
                                       f"Paused for {int(paused_hours)}h without resume — auto-failed")
                label = inv.codename or f"#{inv.id}"
                self.send_message(format_alert(
                    label,
                    f"Was paused for {int(paused_hours)}h with no /resume — auto-failed."
                ))

    def _build_resume_prompt(self, run: RunningInvestigation) -> Path:
        """Build a resume prompt for a restarted session.

        Includes the original question, essential protocol references,
        checkpoint state, remaining tasks, clear next actions, and any
        events accumulated while the orchestrator was parked.
        The restarted agent starts with a clean context window.
        """
        if run.orchestrator_parked:
            restart_label = "WAKE (workers finished or event detected)"
            run.orchestrator_parked = False
        elif run.retry_count > 0:
            restart_label = f"RESTART (attempt {run.retry_count}/{self.config.max_retries})"
        elif run.context_restarts > 0:
            restart_label = f"CONTEXT REFRESH ({run.context_restarts}/{self.config.max_context_restarts})"
        else:
            restart_label = "RESUME (operator-initiated)"
        effective_rigor = self._effective_rigor(run)
        lines: list[str] = [
            f"You are the Voronoi swarm orchestrator. This is a {restart_label}.\n",
            f"**Codename:** {run.label}",
            f"**Mode:** {run.mode} | **Rigor:** {effective_rigor}\n",
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

        # Shared guidance injected into every resume prompt variant
        _common_rules = (
            "- Check `.swarm/dispatcher-directive.json` each OODA cycle.\n"
            "- ALWAYS delegate manuscript writing to a Scribe worker.\n"
            "- Use `bd query` for targeted task lookups, never `bd list --json`.\n"
            "- Dispatch workers via `./scripts/spawn-agent.sh`.\n"
            "- Merge completed work via `./scripts/merge-agent.sh`.\n"
            "- Before convergence, run: `./scripts/convergence-gate.sh . " + effective_rigor + "`\n\n"
            "**Do NOT:**\n"
            "- Sleep, poll, or use `ps aux | grep` to monitor workers\n"
            "- Launch experiments via `nohup` or background subprocesses\n"
            "- Run long-running scripts inline — delegate to workers\n"
            "- Run `sleep 600 && find .llm_cache | wc -l` loops — "
            "they waste your entire context window for zero value\n\n"
            "**If workers are still running**, write your checkpoint with "
            "`active_workers` and EXIT immediately. The dispatcher will wake "
            "you when they finish.\n"
        )

        if run.context_restarts > 0 and run.retry_count == 0:
            lines.append(
                "**CONTEXT REFRESH** — your previous session was healthy but ran out "
                "of context window. Nothing failed. All work is intact.\n"
                "- Do NOT re-validate or re-check completed experiments.\n"
                "- Do NOT re-read files already summarized in the checkpoint/digest.\n"
                "- Pick up EXACTLY where you left off from the checkpoint below.\n"
                "- Read `.swarm/brief-digest.md` for compressed project state.\n"
                + _common_rules
            )
        else:
            lines.append(
                "- All previous experimental work is preserved in the workspace.\n"
                "- Do NOT re-run experiments that already produced results.\n"
                "- Read `.swarm/brief-digest.md` instead of re-reading full PROMPT.md.\n"
                "- Work from the checkpoint and state digest below.\n"
                + _common_rules
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
        cp_path = _find_checkpoint(run.workspace_path)
        if cp_path is not None:
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

        # Events accumulated while orchestrator was parked
        if run.pending_events:
            lines.append("## Events Since Your Last Session\n")
            lines.append(
                "The following events occurred while you were away. "
                "Evaluate them and incorporate into your OODA cycle.\n"
            )
            for ev in run.pending_events:
                etype = ev.get("type", "")
                msg = ev.get("msg", "")
                if msg:
                    lines.append(f"- **{etype}**: {msg}")
            lines.append("")
            # Drain the events — they've been delivered
            run.pending_events.clear()

        # Brief digest (if written by orchestrator at startup)
        brief_path = run.workspace_path / ".swarm" / "brief-digest.md"
        if brief_path.exists():
            try:
                lines.append("## Project Brief Digest\n")
                lines.append(brief_path.read_text().strip())
                lines.append("")
            except OSError:
                pass

        # Convergence-aware directive: if checkpoint shows near-convergence,
        # tell the agent to skip the full role file and just verify + commit.
        near_convergence = False
        if cp_path is not None and cp_path.exists():
            try:
                cp_data = json.loads(cp_path.read_text())
                if isinstance(cp_data, dict):
                    phase = str(cp_data.get("phase", "")).lower()
                    blockers = cp_data.get("blockers", "")
                    remaining = cp_data.get("remaining", [])
                    no_blockers = not blockers or "none" in str(blockers).lower()
                    few_remaining = isinstance(remaining, list) and len(remaining) <= 3
                    if ("converg" in phase or "final" in phase) and no_blockers and few_remaining:
                        near_convergence = True
            except (json.JSONDecodeError, OSError):
                pass

        lines.append("## What To Do Now\n")
        if near_convergence:
            lines.append(
                "**NEAR-CONVERGENCE RESTART — keep this session lean:**\n"
                "1. Do NOT read `.github/agents/swarm-orchestrator.agent.md` — you already know the protocol\n"
                "2. Read ONLY: checkpoint (above) + `bd ready` + dispatcher-directive\n"
                "3. Verify convergence: run `./scripts/convergence-gate.sh . " + effective_rigor + "`\n"
                "4. If gate passes: commit, close remaining beads, write convergence.json\n"
                "5. If gate fails: fix the specific blocker, then re-run gate\n"
                "6. Do NOT re-read paper, belief map, eval score, or claim-evidence unless gate fails\n"
            )
        else:
            lines.append(
                "1. Read `.swarm/orchestrator-checkpoint.json` for full state\n"
                "2. Run `bd ready --json` to see remaining tasks\n"
                "3. If all experiments are done, **dispatch a Scribe worker** for the manuscript\n"
                "4. If `.swarm/brief-digest.md` exists, read it for critical constraints\n"
                "5. **Conserve context** — delegate writing to workers, keep your session lean\n"
                "6. Do NOT re-read files already summarized in the checkpoint above\n"
            )

        resume_file = run.workspace_path / ".swarm" / "orchestrator-prompt-resume.txt"
        resume_file.write_text("\n".join(lines))
        logger.info("Wrote minimal resume prompt for #%d (%d lines)",
                    run.investigation_id, len(lines))
        return resume_file

    def _cleanup_tmux(self, run: RunningInvestigation) -> None:
        """Delegate to tmux module."""
        cleanup_tmux(run.tmux_session, run.workspace_path)

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

    def _handle_abort(self, inv_id: int | None = None) -> None:
        """Abort running investigation(s).

        If *inv_id* is given, only that investigation is aborted.
        Otherwise all running investigations are aborted (global signal).
        Uses ``queue.abort()`` (running → cancelled) so aborted work is
        not accidentally resumable.
        """
        targets = (
            [(inv_id, self.running[inv_id])]
            if inv_id is not None and inv_id in self.running
            else list(self.running.items())
        )
        for tid, run in targets:
            subprocess.run(
                ["tmux", "kill-session", "-t", run.tmux_session],
                capture_output=True, timeout=10,
            )
            self.queue.abort(tid, "Aborted by operator")
            self.send_message(f"*{run.label}* aborted.")
            self.running.pop(tid, None)

    def _check_abort_signal(self) -> None:
        """Check if the router wrote an abort signal file and act on it."""
        for run in list(self.running.values()):
            signal_path = run.workspace_path / ".swarm" / "abort-signal"
            if signal_path.exists():
                logger.info("Abort signal detected for #%d", run.investigation_id)
                try:
                    signal_path.unlink()
                except OSError:
                    pass
                self._handle_abort(run.investigation_id)
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
            if self._effective_rigor(run) not in ("scientific", "experimental"):
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
                                 prompt_file=resume_file,
                                 rigor=self._effective_rigor(run))
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

            # Require the task title to START with a FINDING marker. The
            # prior substring check matched "FINDINGS" anywhere in a title
            # (e.g. "Analyze pricing dataset for five action-changing
            # findings"), which laundered task titles into provisional
            # claims.  See docs/SCIENCE.md §17 and docs/INVARIANTS.md INV-47.
            title_upper = title.upper().lstrip()
            if not (
                title_upper.startswith("FINDING:")
                or title_upper.startswith("FINDING -")
                or title_upper.startswith("FINDING —")
            ):
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
            for prefix in ("FINDING:", "FINDING -", "FINDING —", "FINDING"):
                if statement.upper().startswith(prefix):
                    statement = statement[len(prefix):].strip()
                    break

            try:
                ledger.add_claim(
                    statement=statement,
                    provenance=provenance,
                    source_cycle=inv.cycle_number,
                    supporting_findings=[tid],
                    effect_summary=effect or None,
                    sample_summary=sample_summary,
                    artifacts=artifacts,
                )
            except ValueError as e:
                logger.info(
                    "Skipping ill-formed FINDING for task %s in %s: %s",
                    tid, run.label, e,
                )
                continue
            new_claims = True

        if new_claims:
            save_ledger(inv.lineage_id, ledger, base_dir=self.config.base_dir)

    def _write_run_manifest(self, run: RunningInvestigation) -> None:
        """Assemble and persist ``.swarm/run-manifest.json`` for a completed run.

        Best-effort, non-fatal: manifest-writing must never block the
        completion pipeline.  The manifest is a derived artifact — if any
        source ``.swarm/`` file is missing the factory produces a partial
        but valid manifest rather than raising.
        """
        try:
            from voronoi.science.manifest import (
                build_manifest_from_workspace,
                save_manifest,
            )
            inv = self.queue.get(run.investigation_id)
            ledger = None
            if inv is not None and inv.lineage_id is not None:
                try:
                    from voronoi.science.claims import load_ledger
                    ledger = load_ledger(
                        inv.lineage_id, base_dir=self.config.base_dir,
                    )
                except Exception as e:  # pragma: no cover - defensive
                    logger.debug("Ledger load for manifest failed: %s", e)
                    ledger = None

            manifest = build_manifest_from_workspace(
                run.workspace_path,
                investigation=inv,
                ledger=ledger,
                rigor=self._effective_rigor(run),
            )
            path = save_manifest(run.workspace_path, manifest)
            logger.info("Wrote run manifest for %s: %s", run.label, path)
        except Exception as e:
            logger.warning("Failed to write run manifest for %s: %s", run.label, e)

    def _transition_to_review(self, run: RunningInvestigation) -> bool:
        """Transition a completed science investigation to review status.

        Generates self-critique, continuation proposals, syncs final findings
        to ledger, and sends the review message to Telegram.

        Returns True if the transition succeeded, False if it failed
        (caller should fall back to queue.complete()).
        """
        inv = self.queue.get(run.investigation_id)
        if inv is None:
            return False

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

            # Generate continuation proposals from self-critique + tribunal verdicts
            try:
                from voronoi.science.interpretation import (
                    generate_continuation_proposals,
                    load_tribunal_results,
                    save_continuation_proposals,
                )
                tribunal_results = load_tribunal_results(run.workspace_path)
                proposals = generate_continuation_proposals(ledger, tribunal_results)
                if proposals:
                    save_continuation_proposals(run.workspace_path, proposals)
            except Exception as e:
                logger.debug("Continuation proposal generation failed: %s", e)

            # Transition to review BEFORE sending the notification so that
            # immediate /continue clicks find the correct status (BUG-002).
            if not self.queue.review(run.investigation_id):
                logger.warning("Review transition failed for #%d — status may have changed",
                               run.investigation_id)
                return False

            # Build review message with claims
            review_text = self._build_review_message(run, ledger)
            self.send_message(review_text)
        else:
            if not self.queue.review(run.investigation_id):
                logger.warning("Review transition failed for #%d — status may have changed",
                               run.investigation_id)
                return False
            self.send_message(
                f"🔬 *{run.label}* converged — ready for review.\n"
                f"Reply with feedback or send `/voronoi continue {run.label}` to iterate."
            )
        return True

    def _build_review_message(self, run: RunningInvestigation,
                              ledger) -> str:
        """Build the Telegram review message from the claim ledger."""
        inv = self.queue.get(run.investigation_id)
        cycle_num = inv.cycle_number if inv else (run.improvement_rounds or 1)
        lines = [
            f"🔬 *{run.label}* — Round {cycle_num} complete "
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

        # Show continuation proposals if available
        try:
            from voronoi.science.interpretation import load_continuation_proposals
            proposals = load_continuation_proposals(run.workspace_path)
            if proposals:
                lines.append("\n📋 *Suggested follow-ups (ranked by information gain):*")
                for p in proposals[:5]:
                    lines.append(f"  {p.id}. {p.description} [{p.effort}]")
        except Exception:
            pass

        lines.append(
            "\nReply with your feedback, or:\n"
            f"`/voronoi deliberate {run.label}` — reason about results interactively\n"
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
            "checkpoint.json",
            "success-criteria.json", "experiments.tsv", "eval-score.json",
            "convergence.json", "claim-evidence.json", "report.pdf",
            "state-digest.md", "scout-brief.md", "events.jsonl",
        ]
        for fname in files_to_archive:
            src = swarm / fname
            if src.exists():
                try:
                    shutil.copy2(src, archive_dir / fname)
                except OSError:
                    pass

        # 3. Clean .swarm/ for fresh orchestrator (keep reusable files)
        # Keep: belief-map.json, experiments.tsv, success-criteria.json,
        #       scout-brief.md, brief-digest.md, state-digest.md.
        files_to_remove = [
            "deliverable.md", "events.jsonl", "orchestrator-checkpoint.json",
            "checkpoint.json",
            "convergence.json", "eval-score.json", "dispatcher-directive.json",
            "human-gate.json",
        ]
        for fname in files_to_remove:
            p = swarm / fname
            if p.exists():
                try:
                    p.unlink()
                except OSError:
                    pass

        # Keep: belief-map.json, experiments.tsv, success-criteria.json,
        #       scout-brief.md, brief-digest.md, state-digest.md.
        # Archived state remains available under .swarm/archive/run-N/.

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
