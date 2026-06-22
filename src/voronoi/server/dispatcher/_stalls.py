"""Stalls mixin for InvestigationDispatcher.

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




class _StallsMixin:
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
        the orchestrator must choose between. Partial review only fires at a
        fourth, internal level that requires an additional
        ``stall_final_grace_minutes`` window of silence past strike 3 —
        i.e. three explicit self-steer prompts had no effect.

        Strike 1 is ``diagnose_and_steer``. Strike 2 is
        ``pivot_or_declare``. Strike 3 is ``final_steer`` and the run is not
        killed yet. Strike 4 is ``partial_review``: write partial deliverable
        and diagnosis, then park into review instead of failing.

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
        # recover. This prevents premature partial review during hours-long build-out work
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
        # Strike 4 (partial review) fires only after an additional grace window
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

        # Escalate at most ONE strike level per poll tick. Each strike's
        # purpose is to give the orchestrator a fresh OODA cycle to react;
        # firing 1 → 2 → 3 → 4 in a single tick (no orchestrator wake in
        # between) defeats the entire self-steer design. If the elapsed
        # window already crosses several thresholds (e.g. after a long
        # dispatcher outage), we still only advance one level — subsequent
        # ticks will continue the escalation, leaving real time for the
        # orchestrator to respond between levels.
        if run.stall_strike_level < target_level:
            run.stall_strike_level += 1
            self._fire_stall_strike(run, run.stall_strike_level, elapsed_min)

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

    def _build_stall_diagnosis(
        self, run: RunningInvestigation, elapsed_min: float,
    ) -> dict:
        """Assemble the belief-snapshot injected into every strike signal.

        Mirrors what ``_write_partial_deliverable`` captures at partial-review
        parking, but cheap enough to emit on every strike so the
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
        """Write stall-signal.json, notify, and (at level 4) partial-review.

        Levels 1–3 are self-steer directives: they inject a belief snapshot
        + concrete alternatives into the next orchestrator prompt. The run
        keeps going. Only level 4 — strike 3 threshold plus the final grace
        window — parks the run into review without marking it failed.
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
            # At level 4 the run is being parked; the partial deliverable
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
                f"Partial review in ~{grace}min if no learning.\n\n"
                f"Reply `/voronoi extend {run.label} 60` to grant more "
                f"time."
            )
        elif level == 4:
            self.send_message(
                f"🪫🪫🪫🪫 *{run.label}* — no-learning partial review after "
                f"~{int(round(elapsed_min))}min with zero findings despite "
                f"three self-steer directives. Writing diagnosis and parking "
                f"for PI review. Use `/voronoi review {run.label}` or "
                f"`/voronoi continue {run.label} <feedback>` when ready."
            )
            try:
                self._park_stalled_run_for_partial_review(run, elapsed_min)
            except Exception as e:  # pragma: no cover - defensive
                logger.warning("Failed to park stalled run for partial review %s: %s",
                               run.label, e)

    def _clear_stall_signal(self, run: RunningInvestigation) -> None:
        """Remove .swarm/stall-signal.json when learning resumes."""
        signal_path = run.workspace_path / ".swarm" / "stall-signal.json"
        try:
            if signal_path.exists():
                signal_path.unlink()
        except OSError:
            pass

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

        # Auto-advance epochs while we have evidence and headroom remains.
        # Each epoch transition consumes one belief-map move; remaining
        # moves carry over so a single learning batch with N moves can
        # unlock up to N epochs in one tick instead of throttling
        # parallelism for N more poll cycles.
        advanced = False
        while epoch.belief_map_moves > 0 and epoch.max_tranches < self.config.max_agents:
            carryover = epoch.belief_map_moves - 1
            epoch = advance_epoch(epoch, configured_max=self.config.max_agents)
            epoch.belief_map_moves = carryover
            advanced = True
            logger.info(
                "Investigation #%d advanced to epoch %d (cap: %d tranches)",
                run.investigation_id, epoch.epoch, epoch.max_tranches,
            )
        if advanced:
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
        self, run: RunningInvestigation, elapsed_min: float, *, reason: str = "",
    ) -> None:
        """Emit ``.swarm/deliverable-partial.md`` for partial review.

        Best-effort: list current claims from the ledger (if any) and the
        success-criteria state so the PI has a record of what the run knew.
        """
        path = run.workspace_path / ".swarm" / "deliverable-partial.md"
        path.parent.mkdir(parents=True, exist_ok=True)

        lines: list[str] = []
        lines.append(f"# {run.label} — Partial Review Deliverable\n")
        reason_text = reason or (
            f"No new findings or claim transitions for "
            f"~{int(round(elapsed_min))} minutes "
            f"(stall_strike3_minutes={self.config.stall_strike3_minutes})."
        )
        lines.append(
            f"**Reason:** {reason_text}\n"
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

    def _park_stalled_run_for_partial_review(
        self, run: RunningInvestigation, elapsed_min: float,
    ) -> None:
        reason = (
            f"No learning for ~{int(round(elapsed_min))} minutes "
            f"after three self-steer directives"
        )
        self._park_for_partial_review(
            run,
            reason=reason,
            blocker="learning_stall",
            elapsed_min=elapsed_min,
        )

    def _park_for_partial_review(
        self,
        run: RunningInvestigation,
        *,
        reason: str,
        blocker: str,
        elapsed_min: float,
    ) -> None:
        """Persist partial-review artifacts and transition running → review.

        This is deliberately separate from ``_transition_to_review`` because
        normal review means successful convergence and may promote provisional
        claims. Partial review is a durable decision point: preserve evidence,
        write diagnosis, but do not harden weak claims.
        """
        try:
            self._sync_findings_to_ledger(run)
        except Exception as e:  # pragma: no cover - defensive
            logger.debug("Partial-review ledger sync failed for %s: %s", run.label, e)
        self._write_partial_convergence(run, reason=reason, blocker=blocker)
        self._write_failure_diagnosis(run)
        try:
            self._write_partial_deliverable(run, elapsed_min, reason=reason)
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Failed to write partial deliverable for %s: %s",
                           run.label, e)
        try:
            subprocess.run(
                ["tmux", "kill-session", "-t", run.tmux_session],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass
        try:
            if self.queue.review(run.investigation_id):
                self._write_run_manifest(run)
            else:
                logger.warning(
                    "queue.review() did not transition partial-review run %s",
                    run.label,
                )
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("Partial-review transition failed for %s: %s",
                           run.label, e)
        self.running.pop(run.investigation_id, None)

