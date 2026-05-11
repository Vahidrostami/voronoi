"""Audits mixin for InvestigationDispatcher.

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




class _AuditsMixin:
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
            schema_failure = any("CONTRACT_SCHEMA" in f
                                 for f in result.critical_failures)
            if schema_failure:
                directive_msg = (
                    "SENTINEL ALERT: experiment-contract.json has an unknown "
                    "schema and is being rejected on every audit. "
                    "Read .swarm/sentinel-audit.json. "
                    "Rewrite .swarm/experiment-contract.json using the schema "
                    "documented in your prompt §Experiment Contract — top-level "
                    "keys MUST be from: experiment_id, independent_variable, "
                    "conditions, manipulation_checks, required_outputs, "
                    "degeneracy_checks, phase_gates. Do NOT use 'studies', "
                    "'phases', 'hard_gates', 'primary_metric', 'runner' as "
                    "top-level keys — they are silently ignored. "
                    "This is a SCHEMA error, not a design failure: do NOT "
                    "dispatch Methodologist; just fix the file."
                )
            else:
                directive_msg = (
                    "SENTINEL ALERT: Experiment contract violated. "
                    "Read .swarm/sentinel-audit.json for details. "
                    "This IS a DESIGN_INVALID event — do NOT create a separate "
                    "DESIGN_INVALID task. The sentinel has already flagged it. "
                    "Do NOT proceed to the next phase or dispatch new workers. "
                    "Dispatch Methodologist for post-mortem, then create a "
                    "REVISE task."
                )
            self._write_directive(run, "sentinel_violation", directive_msg)
        else:
            logger.info(
                "Sentinel audit PASSED for #%d (trigger=%s, %d checks)",
                run.investigation_id, trigger, len(result.checks),
            )

        return events

    def _has_experiment_tasks(self, run: RunningInvestigation) -> bool:
        """Check if task_snapshot contains experiment-type tasks."""
        experiment_types = {"investigation", "experiment", "replication", "evaluation"}
        for t in run.task_snapshot.values():
            notes = t.get("notes", "")
            title = t.get("title", "").lower()
            if any(kw in title for kw in ("experiment", "phase", "baseline", "pilot",
                                           "factorial", "ablation", "benchmark")):
                return True
            # ``extract_field`` accepts both ``KEY:value`` and ``KEY=value``;
            # the prior hand-rolled ``KEY=value`` check missed every task
            # written by ``voronoi_create_task`` (which uses the colon form).
            task_type = extract_field(notes, "TASK_TYPE").lower()
            if task_type in experiment_types:
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

    def _check_graph_health(
        self, run: RunningInvestigation, tasks: list[dict] | None,
    ) -> list[dict]:
        """Audit Beads DAG topology each OODA cycle (INV-58).

        Detects the swarm-degenerate failure mode where Beads becomes a
        flat work queue: many root-ready sibling tasks with shared
        normalized title prefixes and no parent edges. Persists
        ``.swarm/graph-health.json`` and emits a ``swarm-degenerate``
        directive when the orphan ratio or sibling-cluster size cross
        thresholds.
        """
        events: list[dict] = []
        if tasks is None:
            return events

        # Only audit PROVE / Analytical+ runs — DISCOVER mode at low rigor
        # legitimately produces many flat exploration tasks.
        if run.mode != "prove" and run.rigor not in (
            "analytical", "scientific", "experimental",
        ):
            return events

        closed = [t for t in tasks if (t.get("status") or "") == "closed"]
        if len(closed) < self._GRAPH_HEALTH_MIN_CLOSED:
            return events

        def _task_type(task: dict) -> str:
            notes = task.get("notes", "") or ""
            m = re.search(r"(?im)^\s*TASK_TYPE\s*[:=]\s*([A-Za-z_]+)", notes)
            if m:
                return m.group(1).strip().lower()
            return (task.get("type") or "").strip().lower()

        def _has_parent(task: dict) -> bool:
            if task.get("parent_id") or task.get("parent"):
                return True
            deps = task.get("dependencies") or task.get("depends_on") or []
            return bool(deps)

        orphan_count = 0
        auditable = 0
        for t in closed:
            ttype = _task_type(t)
            if ttype in self._GRAPH_HEALTH_EXEMPT_TYPES:
                continue
            if self._GRAPH_HEALTH_AUDITED_TYPES and ttype and ttype not in self._GRAPH_HEALTH_AUDITED_TYPES:
                # Unknown / scout-adjacent types — skip rather than over-audit.
                continue
            auditable += 1
            if not _has_parent(t):
                orphan_count += 1

        orphan_ratio = (orphan_count / auditable) if auditable else 0.0

        # Sibling-cluster detection: normalize the first 3 words of each
        # closed title and count buckets. ≥5 tasks in one bucket indicates
        # a laundering loop ("Analyze business prompt …").
        clusters: dict[str, list[str]] = {}
        for t in closed:
            title = (t.get("title") or "").strip().lower()
            if not title:
                continue
            words = re.findall(r"[a-z0-9]+", title)
            if len(words) < 3:
                continue
            key = " ".join(words[:3])
            clusters.setdefault(key, []).append(t.get("id", ""))
        cluster_max = max((len(v) for v in clusters.values()), default=0)
        cluster_titles = [k for k, v in clusters.items()
                          if len(v) >= self._GRAPH_SIBLING_CLUSTER_THRESHOLD]

        reasons: list[str] = []
        if orphan_ratio > self._GRAPH_ORPHAN_RATIO_THRESHOLD:
            reasons.append(
                f"orphan_ratio {orphan_ratio:.2f} > "
                f"{self._GRAPH_ORPHAN_RATIO_THRESHOLD}"
            )
        if cluster_max >= self._GRAPH_SIBLING_CLUSTER_THRESHOLD:
            reasons.append(
                f"sibling cluster of {cluster_max} tasks "
                f"with normalized prefix {cluster_titles[0]!r}"
            )

        verdict = "degenerate" if reasons else "healthy"
        report = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_closed": len(closed),
            "auditable_closed": auditable,
            "orphan_count": orphan_count,
            "orphan_ratio": round(orphan_ratio, 3),
            "sibling_cluster_max": cluster_max,
            "sibling_cluster_titles": cluster_titles,
            "verdict": verdict,
            "reasons": reasons,
        }

        try:
            health_path = run.workspace_path / ".swarm" / "graph-health.json"
            health_path.parent.mkdir(parents=True, exist_ok=True)
            health_path.write_text(json.dumps(report, indent=2))
        except OSError as exc:
            logger.debug("Failed to write graph-health.json for #%d: %s",
                         run.investigation_id, exc)

        prior_verdict = run._last_graph_health_verdict
        run._last_graph_health_verdict = verdict
        if verdict == "degenerate" and prior_verdict != "degenerate":
            msg = (
                "🕸️ *SWARM DEGENERATE* — Beads DAG looks flat\n  "
                + "; ".join(reasons)
                + ". Restate laundered task titles, attach orphans to a "
                "parent epic, or escalate to Methodologist before dispatching new workers."
            )
            events.append({"type": "swarm_degenerate", "msg": msg})
            self._write_directive(
                run, "swarm_degenerate",
                "SWARM DEGENERATE: Beads DAG audit failed (INV-58). "
                + "; ".join(reasons)
                + ". Read .swarm/graph-health.json. "
                "Do NOT dispatch additional analysis workers. Either "
                "restate ghost tasks with concrete propositions / "
                "FINDING: prefixes, attach orphan tasks to a parent "
                "epic, or dispatch Methodologist for a plan audit."
            )

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

