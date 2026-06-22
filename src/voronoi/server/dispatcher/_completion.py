"""Completion mixin for InvestigationDispatcher.

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




# Convergence statuses recognised by ``_convergence_status_ok``.
# Module-level so the mixin can reference it without a forward reference to
# the composed ``InvestigationDispatcher`` class.
_CONVERGED_STATUSES = frozenset({
    "converged", "exhausted", "diminishing_returns", "negative_result",
})


class _CompletionMixin:
    def _has_open_design_invalid(self, run: RunningInvestigation) -> bool:
        """Check if any open tasks have DESIGN_INVALID flag.

        Uses the cached task_snapshot from the last progress poll to avoid
        extra subprocess calls.
        """
        for t in run.task_snapshot.values():
            if t["status"] != "closed" and "DESIGN_INVALID" in t.get("notes", ""):
                return True
        return False

    def _has_open_design_invalid_hard_check(self, run: RunningInvestigation) -> bool:
        """Hard check for open DESIGN_INVALID tasks against Beads source-of-truth.

        Called from completion gate when the orchestrator session is already
        dead and task_snapshot may be stale/empty (BUG-001). Returns True if
        Beads reports any non-closed task with DESIGN_INVALID in its notes.
        """
        from voronoi.beads import run_bd_json
        code, tasks = run_bd_json("list", "--json", cwd=str(run.workspace_path))
        if code != 0 or not isinstance(tasks, list):
            # bd call failed — treat as no signal (allow completion)
            return False
        for task in tasks:
            if not isinstance(task, dict):
                continue
            status = task.get("status", "")
            notes = task.get("notes", "")
            if status != "closed" and "DESIGN_INVALID" in notes:
                logger.warning(
                    "Completion blocked for %s: DESIGN_INVALID in task %s (hard check)",
                    run.label, task.get("id", "?")
                )
                return True
        return False

    @staticmethod
    def _convergence_status_ok(data: dict) -> bool:
        """Check if convergence.json data indicates completion.

        Case-insensitive: agents may write 'CONVERGED' or 'converged'.
        """
        if data.get("converged", False):
            return True
        status = data.get("status", "")
        if isinstance(status, str):
            return status.lower() in _CONVERGED_STATUSES
        return False

    def _convergence_signals_completion(self, run: RunningInvestigation) -> bool:
        """Return True iff .swarm/convergence.json exists and signals completion."""
        conv = run.workspace_path / ".swarm" / "convergence.json"
        if not conv.exists():
            return False
        try:
            data = json.loads(conv.read_text())
        except (json.JSONDecodeError, OSError):
            return False
        return isinstance(data, dict) and self._convergence_status_ok(data)

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
        # HARD GATE: never complete while DESIGN_INVALID tasks are open.
        # First, do a quick cached check to avoid expensive Beads calls when
        # completion is not plausible.
        if self._has_open_design_invalid(run):
            return False

        effective_rigor = self._effective_rigor(run)
        completion_plausible = False

        if (run.workspace_path / ".swarm" / "deliverable.md").exists():
            # For adaptive rigor (not yet escalated), deliverable is sufficient
            if effective_rigor == "adaptive":
                completion_plausible = True
            else:
                # For higher rigor, also need convergence signal
                completion_plausible = self._convergence_signals_completion(run)
                if not completion_plausible:
                    # Deliverable exists but no convergence — try to generate one
                    # Throttle to avoid running the gate every poll cycle (30s).
                    # When session_dead=True, bypass cooldown.
                    now = time.time()
                    cooldown_ok = (now - run.last_convergence_attempt_at >= 300)
                    if cooldown_ok or session_dead:
                        run.last_convergence_attempt_at = now
                        self._try_convergence_check(run)
                    completion_plausible = self._convergence_signals_completion(run)
        else:
            # No deliverable — check if convergence.json alone signals completion
            completion_plausible = self._convergence_signals_completion(run)

        if not completion_plausible:
            return False

        # BUG-001 fix: completion signals exist, but task_snapshot may be stale
        # (e.g., after dispatcher restart, or when session_alive=True and
        # _check_progress skips bd to avoid lock contention). Do a final hard
        # check against Beads source-of-truth before declaring completion.
        if self._has_open_design_invalid_hard_check(run):
            return False

        return True

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

        # NOTE: previously a second fallback parsed .beads/*.jsonl directly when
        # bd was unavailable, but Beads' JSONL is an append-only event log
        # (multiple entries per task id, including historical 'closed' events),
        # so counting lines inflated totals and over-counted closures. When bd
        # is unavailable we now report 0/0 honestly instead of fabricating
        # numbers from the event log.

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
                    shutil.rmtree(swarm_dir)
            except OSError:
                from voronoi.server.workspace import describe_live_file_holders
                holders = describe_live_file_holders([swarm_dir])
                if holders:
                    logger.warning(
                        "Could not remove %s; live processes hold files: %s",
                        swarm_dir, ", ".join(holders[:8]),
                    )
                else:
                    logger.warning(
                        "Could not remove %s; it may contain open NFS lock files",
                        swarm_dir,
                    )

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
        from voronoi.utils import extract_field, is_finding_title

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
            if not is_finding_title(title):
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
            "stall-signal.json", "deliverable-partial.md",
            "failure-diagnosis.json", "run-manifest.json",
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
            "human-gate.json", "stall-signal.json", "deliverable-partial.md",
            "failure-diagnosis.json",
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

