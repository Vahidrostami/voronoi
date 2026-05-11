"""Progress mixin for InvestigationDispatcher.

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




class _ProgressMixin:
    def _effective_timeout(self, run: RunningInvestigation) -> int | None:
        """Return the explicit wall-clock review budget for an investigation.

        Checks for a per-investigation override file at
        ``<workspace>/.swarm/timeout_hours``.  The file should contain a
        single positive integer (the total review budget in hours).  Values
        ``0``, ``off``, ``none``, and ``disabled`` turn the budget off for
        the run. If the file is
        missing or unreadable, falls back to ``self.config.timeout_hours``.
        """
        override_path = run.workspace_path / ".swarm" / "timeout_hours"
        if override_path.exists():
            try:
                raw = override_path.read_text().strip()
                if raw.lower() in {"", "0", "off", "none", "disabled"}:
                    return None
                value = int(raw)
                if value > 0:
                    return value
                logger.warning(
                    "Invalid timeout override for #%d: value %r must be positive; "
                    "falling back to config default %s",
                    run.investigation_id, value, self.config.timeout_hours,
                )
            except (ValueError, OSError) as e:
                logger.warning(
                    "Failed to read timeout override at %s for #%d (%s); "
                    "falling back to config default %s",
                    override_path, run.investigation_id, e,
                    self.config.timeout_hours,
                )
        return self.config.timeout_hours

    def _write_timeout_convergence(self, run: RunningInvestigation) -> None:
        """Write partial-review convergence for an explicit time budget."""
        effective = self._effective_timeout(run)
        self._write_partial_convergence(
            run,
            reason=f"Explicit time budget reached after {effective}h",
            blocker="time_budget",
        )

    def _write_partial_convergence(
        self, run: RunningInvestigation, *, reason: str, blocker: str,
    ) -> None:
        """Write convergence.json for a durable partial-review state."""
        conv_path = run.workspace_path / ".swarm" / "convergence.json"
        conv_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "status": "partial",
            "converged": False,
            "reason": reason,
            "score": run.eval_score,
            "blockers": [blocker],
            "gate_passed": False,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        conv_path.write_text(json.dumps(data, indent=2))

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
        if level in ("sentinel_violation", "swarm_degenerate"):
            data["action"] = "stop_and_fix"
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
        events.extend(self._check_graph_health(run, tasks))
        events.extend(self._detect_phase(run))

        # Sync findings to cross-run Claim Ledger
        if tasks:
            try:
                self._sync_findings_to_ledger(run, tasks)
            except Exception as e:
                logger.debug("Claim ledger sync failed for #%d: %s",
                             run.investigation_id, e)

        return events

    def _write_status_snapshot(self, run: RunningInvestigation, *,
                               session_alive: bool) -> None:
        """Write the PI-facing status snapshot for the current poll."""
        try:
            from voronoi.server.snapshot import (
                WorkspaceSnapshot,
                build_investigation_status,
                write_investigation_status,
            )
            tasks = [
                {
                    "id": task_id,
                    "status": task.get("status", ""),
                    "title": task.get("title", ""),
                    "notes": task.get("notes", ""),
                }
                for task_id, task in run.task_snapshot.items()
                if isinstance(task, dict)
            ] or None
            snapshot = WorkspaceSnapshot.from_workspace(
                run.workspace_path,
                tasks=tasks,
                old_phase=run.phase,
            )
            status = build_investigation_status(
                run.workspace_path,
                snapshot,
                investigation_id=run.investigation_id,
                codename=run.codename,
                mode=run.mode,
                rigor=run.rigor,
                question=run.question,
                session_alive=session_alive,
                orchestrator_parked=run.orchestrator_parked,
            )
            write_investigation_status(run.workspace_path, status)
        except Exception as exc:
            logger.debug("Failed to write status snapshot for #%d: %s",
                         run.investigation_id, exc)

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
            # Prefix-only check: a substring match would surface ghost
            # titles like "Analyze ... findings" as real findings, reset
            # learning-stall timers, and mislead the PI. See INV-47.
            if is_finding_title(title) and tid not in run.notified_findings:
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

