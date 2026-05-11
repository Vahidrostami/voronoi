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


from voronoi.utils import extract_field, is_finding_title  # noqa: E402


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
    timeout_hours: int | None = None  # no default wall-clock kill; positive values are review budgets
    max_retries: int = 2         # max times to restart a dead agent
    stall_minutes: int = 45      # warn/restart if 0 tasks after this long
    pause_timeout_hours: int | None = None  # no default missed-message expiry
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
    # Strike 3: directive = "final_steer" (last self-steer, grace before partial review)
    # Strike 4: directive = "partial_review" (durable PI decision point)
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
    _last_graph_health_verdict: str = ""  # Last graph-health verdict (INV-58); fire event only on transition
    _sentinel_missing_contract_warned: bool = False  # Track sentinel missing-contract warning
    notified_reversed_hypotheses: set = field(default_factory=set)  # Track which reversed hypotheses have been alerted
    last_convergence_attempt_at: float = 0  # Throttle _try_convergence_check() calls
    last_ledger_map: dict[str, str] = field(default_factory=dict)  # claim_id → status for delta detection
    _ledger_baseline_seeded: bool = False  # First poll seeds baseline without emitting deltas
    last_learning_activity_at: float = 0  # Last time a new finding/claim transition was observed
    stall_strike_level: int = 0  # Self-steer escalation: 0/1/2/3/4 (4 = partial review)
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

# ---------------------------------------------------------------------------
# Mixin imports — see scripts/split_dispatcher.py for cluster definitions.
# Method-resolution: every InvestigationDispatcher.<method> still resolves
# via the MRO, so test patches against the class continue to work.
# ---------------------------------------------------------------------------
from voronoi.server.dispatcher._launch import _LaunchMixin
from voronoi.server.dispatcher._recovery import _RecoveryMixin
from voronoi.server.dispatcher._progress import _ProgressMixin
from voronoi.server.dispatcher._audits import _AuditsMixin
from voronoi.server.dispatcher._stalls import _StallsMixin
from voronoi.server.dispatcher._liveness import _LivenessMixin
from voronoi.server.dispatcher._completion import _CompletionMixin


class _CoreMixin:
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

            # BUG-002 FIX: Stall escalation must run on EVERY due poll, not just
            # when events are sent. Synthesize claim deltas and evaluate learning
            # activity before the `if events:` check so quiet polls still advance
            # the stall escalator.
            claim_events = self._synthesize_claim_deltas(run)
            all_events = list(events) + claim_events
            self._update_learning_activity(run, all_events)
            self._write_status_snapshot(run, session_alive=session_alive)

            if events:
                # If orchestrator is parked, accumulate events for resume prompt
                # and throttle Telegram digests to every 5 minutes
                if run.orchestrator_parked:
                    self._accumulate_parked_events(run, events)
                    if now - run.last_parked_digest_at >= 300:  # 5-minute throttle
                        run.last_parked_digest_at = now
                        logger.info("Investigation #%d: %d events while parked (phase=%s)",
                                    inv_id, len(events), run.phase)
                        self._send_progress_batch(run, events, claim_events)
                else:
                    logger.info("Investigation #%d: %d events (phase=%s)",
                                inv_id, len(events), run.phase)
                    self._send_progress_batch(run, events, claim_events)

            if inv_id not in self.running:
                # A stall escalation may have parked the run into review.
                continue

            # Check for explicit wall-clock review budget (disabled by default;
            # per-investigation override via .swarm/timeout_hours)
            elapsed_hours = (now - run.started_at) / 3600
            effective_timeout = self._effective_timeout(run)
            timed_out = (
                effective_timeout is not None
                and elapsed_hours >= effective_timeout
            )

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
                    budget = effective_timeout or 0
                    reason = f"time budget reached ({budget}h)"
                    logger.warning(
                        "Investigation #%d reached explicit time budget after %.1fh",
                        inv_id, elapsed_hours,
                    )
                    self.send_message(
                        f"⏱ *{run.label}* — explicit time budget reached "
                        f"after ~{elapsed_hours:.1f}h. Parked for review; "
                        f"use `/voronoi review {run.label}` or "
                        f"`/voronoi continue {run.label} <feedback>` when ready."
                    )
                    self._park_for_partial_review(
                        run,
                        reason=(
                            f"Explicit time budget reached after "
                            f"{elapsed_hours:.1f}h"
                        ),
                        blocker="time_budget",
                        elapsed_min=elapsed_hours * 60,
                    )
                    logger.info("Investigation #%d finished (%s)", inv_id, reason)
                    continue
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

    def _send_progress_batch(self, run: RunningInvestigation, events: list[dict], 
                             claim_events: list[dict] | None = None) -> None:
        # Claim deltas already synthesized and passed in from poll_progress
        # (BUG-002 fix: moved synthesis upstream so stall evaluation happens
        # every poll, not just when events are sent).
        if claim_events:
            events = list(events) + claim_events

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



class InvestigationDispatcher(_CoreMixin, _LaunchMixin, _RecoveryMixin, _ProgressMixin, _AuditsMixin, _StallsMixin, _LivenessMixin, _CompletionMixin):
    """Launches queued investigations and monitors their progress.

    Integrates with the Telegram bridge via two callbacks:
      send_message(text)  — send a chat message
      send_document(chat_id, path, caption)  — send a file
    """
    _EFFORT_BY_RIGOR = EFFORT_BY_RIGOR

    _DIRECTIVE_PRIORITY: dict[str, int] = {
        "context_advisory": 1,
        "context_warning": 2,
        "context_critical": 3,
        "swarm_degenerate": 3,
        "sentinel_violation": 4,
    }

    POLLING_STRIKE_THRESHOLD = 3

    _GRAPH_HEALTH_AUDITED_TYPES = frozenset({
        "investigation", "experiment", "evaluation", "exploration", "build", "paper",
    })

    _GRAPH_HEALTH_EXEMPT_TYPES = frozenset({
        "epic", "scout", "theory", "methodologist", "baseline", "finding",
        "review_stats", "review_critic", "synthesis",
    })

    _GRAPH_ORPHAN_RATIO_THRESHOLD = 0.4

    _GRAPH_SIBLING_CLUSTER_THRESHOLD = 5

    _GRAPH_HEALTH_MIN_CLOSED = 5  # below this, signal is too noisy

    _STALL_PHASE_MULTIPLIERS = {
        "setup": 3.0,
        "explore": 1.0,
        "test": 1.0,
        "synthesize": 0.5,
    }

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
                "that follows, the dispatcher will park the run for partial review."
            ),
        },
        4: {
            "directive": "partial_review",
            "instruction": (
                "Parked for partial review by dispatcher after strike 3 + "
                "grace window: zero learning despite three self-steer "
                "directives. See .swarm/deliverable-partial.md and "
                ".swarm/failure-diagnosis.json. The PI may review, "
                "continue, or complete the reviewed partial state later."
            ),
        },
    }

    # _CONVERGED_STATUSES moved to dispatcher/_completion.py as a module-level
    # constant; mixin code references it directly to avoid forward-referencing
    # the composed class from inside its own bases.


