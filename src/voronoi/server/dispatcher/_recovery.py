"""Recovery mixin for InvestigationDispatcher.

Auto-extracted from dispatcher.py by scripts/split_dispatcher.py.
Do not edit method signatures here without updating tests."""

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




class _RecoveryMixin:
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
        """Auto-fail paused investigations only when explicitly configured."""
        if not self.config.pause_timeout_hours or self.config.pause_timeout_hours <= 0:
            return
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

