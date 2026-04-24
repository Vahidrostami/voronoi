"""Convergence detection, belief map, and orchestrator checkpoint.

These three concerns are bundled because they share the same lifecycle:
the orchestrator reads/writes them every OODA cycle, and convergence
is the only code-side consumer of belief map state.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from voronoi.utils import extract_field
from voronoi.science import consistency as _helpers
from voronoi.science import interpretation as _interp

logger = logging.getLogger("voronoi.science")

# Confidence tiers — ordinal scale that LLMs can reliably distinguish.
# Maps tier name → uncertainty value for information-gain prioritization.
CONFIDENCE_TIERS: dict[str, float] = {
    "unknown": 1.0,
    "hunch": 0.7,
    "supported": 0.4,
    "strong": 0.15,
    "resolved": 0.0,
}

VALID_CONFIDENCE_TIERS = frozenset(CONFIDENCE_TIERS)


def _infer_confidence_from_posterior(posterior: float) -> str:
    """Infer a confidence tier from a legacy posterior value."""
    uncertainty = 1.0 - abs(posterior - 0.5) * 2
    if uncertainty >= 0.85:
        return "unknown"
    if uncertainty >= 0.55:
        return "hunch"
    if uncertainty >= 0.25:
        return "supported"
    if uncertainty >= 0.05:
        return "strong"
    return "resolved"


# ===================================================================
# Belief Map
# ===================================================================

@dataclass
class Hypothesis:
    id: str
    name: str
    prior: float
    posterior: float
    status: str = "untested"
    evidence: list[str] = field(default_factory=list)
    testability: float = 0.5
    impact: float = 0.5
    confidence: str = ""       # unknown | hunch | supported | strong | resolved
    rationale: str = ""        # Evidence-linked reasoning for current confidence
    next_test: str = ""        # What experiment/analysis would change confidence

    @property
    def uncertainty(self) -> float:
        # Prefer confidence tier when available; fall back to posterior math
        if self.confidence and self.confidence in CONFIDENCE_TIERS:
            return CONFIDENCE_TIERS[self.confidence]
        return 1.0 - abs(self.posterior - 0.5) * 2

    @property
    def display_name(self) -> str:
        """Name with fallback to id — never returns empty string."""
        return self.name or self.id or "?"

    @property
    def information_gain(self) -> float:
        return self.uncertainty * self.impact * self.testability


@dataclass
class BeliefMap:
    hypotheses: list[Hypothesis] = field(default_factory=list)
    cycle: int = 0
    last_updated: str = ""

    def add_hypothesis(self, h: Hypothesis) -> None:
        self.hypotheses.append(h)

    def update_hypothesis(self, h_id: str, posterior: float,
                          status: str, evidence_id: str = "") -> bool:
        for h in self.hypotheses:
            if h.id == h_id:
                h.posterior = max(0.0, min(1.0, posterior))
                h.status = status
                if evidence_id:
                    h.evidence.append(evidence_id)
                return True
        return False

    def get_priority_order(self) -> list[Hypothesis]:
        untested = [h for h in self.hypotheses if h.status in ("untested", "testing")]
        return sorted(untested, key=lambda h: h.information_gain, reverse=True)

    def all_resolved(self) -> bool:
        return all(h.status not in ("untested", "testing") for h in self.hypotheses)

    def summary(self) -> dict:
        by_status: dict[str, int] = {}
        for h in self.hypotheses:
            by_status[h.status] = by_status.get(h.status, 0) + 1
        return {"total": len(self.hypotheses), "by_status": by_status, "cycle": self.cycle}


def load_belief_map(workspace: Path) -> BeliefMap:
    path = workspace / ".swarm" / "belief-map.json"
    if not path.exists():
        return BeliefMap()
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            logger.warning("belief-map.json is not a dict in %s", workspace)
            return BeliefMap()
        bm = BeliefMap(cycle=data.get("cycle", 0), last_updated=data.get("last_updated", ""))
        raw_hyps = data.get("hypotheses", [])
        # Schema migration: accept both list-of-objects (canonical) and
        # dict-keyed-by-id (legacy/malformed).  See INV-33.
        migrated = False
        if isinstance(raw_hyps, dict):
            logger.warning("belief-map.json has dict-keyed hypotheses in %s — migrating to list", workspace)
            items: list[dict] = []
            for key, val in raw_hyps.items():
                if isinstance(val, dict):
                    if "id" not in val:
                        val["id"] = key
                    items.append(val)
                elif isinstance(val, str):
                    items.append({"id": key, "name": val})
            raw_hyps = items
            migrated = True
        if not isinstance(raw_hyps, list):
            logger.warning("belief-map.json hypotheses is not a list or dict in %s", workspace)
            raw_hyps = []
        for h in raw_hyps:
            if not isinstance(h, dict):
                continue
            posterior = h.get("posterior", h.get("prior", 0.5))
            confidence = h.get("confidence", "")
            # Infer confidence from posterior for legacy data missing the field
            if not confidence:
                confidence = _infer_confidence_from_posterior(float(posterior))
            bm.hypotheses.append(Hypothesis(
                id=h.get("id", ""), name=h.get("name", ""),
                prior=h.get("prior", 0.5), posterior=posterior,
                status=h.get("status", "untested"), evidence=h.get("evidence", []),
                testability=h.get("testability", 0.5), impact=h.get("impact", 0.5),
                confidence=confidence,
                rationale=h.get("rationale", ""),
                next_test=h.get("next_test", ""),
            ))
        # Persist migration so subsequent reads don't re-trigger warnings
        if migrated:
            try:
                data["hypotheses"] = raw_hyps
                path.write_text(json.dumps(data, indent=2))
                logger.info("Persisted belief-map migration for %s", workspace)
            except OSError:
                pass
        return bm
    except (json.JSONDecodeError, OSError, AttributeError, TypeError) as e:
        logger.warning("Failed to load belief map: %s", e)
        return BeliefMap()


def save_belief_map(workspace: Path, bm: BeliefMap) -> None:
    path = workspace / ".swarm" / "belief-map.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    bm.last_updated = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps({
        "cycle": bm.cycle, "last_updated": bm.last_updated,
        "hypotheses": [asdict(h) for h in bm.hypotheses],
    }, indent=2))


# ===================================================================
# Evidence-Gated Epoch Tracking
# ===================================================================

# Scaling tiers: epoch → max parallel tranches allowed.
# Each tier is earned by producing evidence in the prior epoch.
EPOCH_AGENT_CAP: dict[int, int] = {
    1: 2,   # Prove the approach works
    2: 4,   # Evidence supports scaling
    3: 6,   # Full scale (matches default max_agents)
}

# Default cap for epochs beyond the table
_DEFAULT_FULL_CAP: int = 6


@dataclass
class EpochState:
    """Persistent epoch tracking state for an investigation.

    Written to ``.swarm/epoch-state.json`` and read by both the
    dispatcher (to enforce agent caps and detect stalls) and the
    orchestrator prompt (to communicate the current budget).
    """
    epoch: int = 1
    max_tranches: int = 2
    findings_this_epoch: int = 0
    belief_map_moves: int = 0  # Confidence tier changes in this epoch
    tokens_this_epoch: int = 0
    epoch_started_at: str = ""
    history: list[dict] = field(default_factory=list)

    @property
    def learning_rate(self) -> float:
        """Findings per million tokens in this epoch (0 if no tokens yet)."""
        if self.tokens_this_epoch <= 0:
            return 0.0
        return self.findings_this_epoch / (self.tokens_this_epoch / 1_000_000)

    @property
    def has_evidence(self) -> bool:
        """True if this epoch produced at least one belief-map-moving finding."""
        return self.belief_map_moves > 0


def load_epoch_state(workspace: Path) -> EpochState:
    """Load epoch state from workspace, returning defaults for new investigations."""
    path = workspace / ".swarm" / "epoch-state.json"
    if not path.exists():
        return EpochState(
            epoch_started_at=datetime.now(timezone.utc).isoformat(),
        )
    try:
        d = json.loads(path.read_text())
        if not isinstance(d, dict):
            return EpochState(
                epoch_started_at=datetime.now(timezone.utc).isoformat(),
            )
        return EpochState(
            epoch=d.get("epoch", 1),
            max_tranches=d.get("max_tranches", 2),
            findings_this_epoch=d.get("findings_this_epoch", 0),
            belief_map_moves=d.get("belief_map_moves", 0),
            tokens_this_epoch=d.get("tokens_this_epoch", 0),
            epoch_started_at=d.get("epoch_started_at", ""),
            history=d.get("history", []),
        )
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load epoch-state.json: %s", e)
        return EpochState(
            epoch_started_at=datetime.now(timezone.utc).isoformat(),
        )


def save_epoch_state(workspace: Path, state: EpochState) -> None:
    """Persist epoch state to workspace."""
    path = workspace / ".swarm" / "epoch-state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2))


def advance_epoch(state: EpochState, configured_max: int = _DEFAULT_FULL_CAP) -> EpochState:
    """Advance to the next epoch after evidence was produced.

    Archives the current epoch's metrics into ``history`` and increases
    the agent cap for the next epoch.
    """
    state.history.append({
        "epoch": state.epoch,
        "findings": state.findings_this_epoch,
        "belief_map_moves": state.belief_map_moves,
        "tokens": state.tokens_this_epoch,
        "started_at": state.epoch_started_at,
        "advanced_at": datetime.now(timezone.utc).isoformat(),
    })
    state.epoch += 1
    # Cap increases per EPOCH_AGENT_CAP table, never exceeding configured max
    raw_cap = EPOCH_AGENT_CAP.get(state.epoch, configured_max)
    state.max_tranches = min(raw_cap, configured_max)
    state.findings_this_epoch = 0
    state.belief_map_moves = 0
    state.tokens_this_epoch = 0
    state.epoch_started_at = datetime.now(timezone.utc).isoformat()
    return state


def compute_learning_rate_display(state: EpochState) -> str:
    """Format learning rate for Telegram digest display."""
    if state.tokens_this_epoch <= 0:
        return ""
    rate = state.learning_rate
    if rate <= 0:
        return f"Learning: 0 findings (epoch {state.epoch}, cap {state.max_tranches} tranches)"
    return (
        f"Learning: {rate:.1f} findings/M tokens "
        f"(epoch {state.epoch}, cap {state.max_tranches} tranches)"
    )


# ===================================================================
# Structured Failure Diagnosis
# ===================================================================


def build_failure_diagnosis(workspace: Path) -> dict:
    """Build a structured diagnosis of why an investigation stalled or failed.

    Returns a dict suitable for writing to ``.swarm/failure-diagnosis.json``
    and for injecting into continuation warm-start prompts.
    """
    swarm = workspace / ".swarm"
    diagnosis: dict = {
        "met_criteria": [],
        "unmet_criteria": [],
        "systemic_issues": [],
        "epoch_history": [],
        "proposed_action": "",
    }

    # Success criteria analysis
    sc_path = swarm / "success-criteria.json"
    if sc_path.exists():
        try:
            sc = json.loads(sc_path.read_text())
            if isinstance(sc, list):
                for c in sc:
                    if not isinstance(c, dict):
                        continue
                    cid = c.get("id", "?")
                    desc = c.get("description", "")
                    if c.get("met"):
                        diagnosis["met_criteria"].append(cid)
                    else:
                        diagnosis["unmet_criteria"].append({
                            "id": cid,
                            "description": desc,
                            "diagnosis": "NOT_TESTED",
                            "recommendation": "",
                        })
        except (json.JSONDecodeError, OSError):
            pass

    # Check experiments to refine diagnosis
    exp_path = swarm / "experiments.tsv"
    if exp_path.exists():
        try:
            lines = exp_path.read_text().strip().splitlines()
            exp_count = max(0, len(lines) - 1)  # minus header
            keep_count = sum(1 for l in lines[1:] if "\tkeep\t" in l)
            crash_count = sum(1 for l in lines[1:] if "\tcrash\t" in l)
            if exp_count == 0:
                diagnosis["systemic_issues"].append(
                    "Zero experiments ran — plan likely overscoped or setup failed"
                )
            elif keep_count == 0:
                diagnosis["systemic_issues"].append(
                    f"{exp_count} experiments attempted but 0 produced usable results"
                )
            if crash_count > exp_count * 0.5 and exp_count > 0:
                diagnosis["systemic_issues"].append(
                    f"{crash_count}/{exp_count} experiments crashed — infrastructure issue"
                )
        except OSError:
            pass

    # Epoch history for learning rate trajectory
    epoch_state = load_epoch_state(workspace)
    diagnosis["epoch_history"] = epoch_state.history
    if epoch_state.epoch == 1 and epoch_state.findings_this_epoch == 0:
        diagnosis["systemic_issues"].append(
            "Never advanced past epoch 1 — no evidence-producing work completed"
        )
        diagnosis["proposed_action"] = (
            "Start with a single minimum-viable experiment that tests "
            "the core assumption before scaling"
        )

    # Belief map state
    bm = load_belief_map(workspace)
    if bm.hypotheses:
        untested = sum(1 for h in bm.hypotheses if h.status == "untested")
        if untested == len(bm.hypotheses):
            diagnosis["systemic_issues"].append(
                f"All {untested} hypotheses still untested — "
                f"agents dispatched but none produced findings"
            )
    else:
        diagnosis["systemic_issues"].append(
            "No hypotheses in belief map — investigation never reached hypothesis stage"
        )

    # Refine unmet criteria diagnoses based on experiment data
    for entry in diagnosis["unmet_criteria"]:
        if entry["diagnosis"] == "NOT_TESTED" and exp_path.exists():
            # If experiments ran but criterion unmet, it's a real null, not untested
            try:
                lines = exp_path.read_text().strip().splitlines()
                keep_count = sum(1 for l in lines[1:] if "\tkeep\t" in l)
                if keep_count > 0:
                    entry["diagnosis"] = "TESTED_BUT_UNMET"
                    entry["recommendation"] = (
                        "Experiments ran but did not satisfy this criterion — "
                        "review results to determine if this is a real null or "
                        "a methodology issue"
                    )
            except OSError:
                pass

    return diagnosis


def save_failure_diagnosis(workspace: Path, diagnosis: dict) -> None:
    """Write structured diagnosis to workspace."""
    path = workspace / ".swarm" / "failure-diagnosis.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    diagnosis["timestamp"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(diagnosis, indent=2))


# ===================================================================
# Orchestrator Checkpoint
# ===================================================================

@dataclass
class OrchestratorCheckpoint:
    cycle: int = 0
    phase: str = "starting"
    mode: str = "discover"
    rigor: str = "adaptive"
    # Orchestrator-declared work mode for phase-aware stall budgets.
    # "" (empty) = inferred from ``phase``; "setup" | "explore" | "test" |
    # "synthesize" when the orchestrator knows better than the coarse phase.
    # Consumed by dispatcher._stall_phase_multiplier(). See docs/SERVER.md §3.
    lifecycle_phase: str = ""
    hypotheses_summary: str = ""
    total_tasks: int = 0
    closed_tasks: int = 0
    active_workers: list[str] = field(default_factory=list)
    recent_events: list[str] = field(default_factory=list)
    recent_decisions: list[str] = field(default_factory=list)
    dead_ends: list[str] = field(default_factory=list)
    next_actions: list[str] = field(default_factory=list)
    criteria_status: dict[str, bool] = field(default_factory=dict)
    eval_score: float = 0.0
    improvement_rounds: int = 0
    last_updated: str = ""
    # Token budget tracking — prevents surprise context overflow
    tokens_this_cycle: int = 0
    tokens_cumulative: int = 0
    context_window_remaining_pct: float = 1.0
    # Structured /context snapshot — ground-truth from Copilot CLI
    context_snapshot: dict = field(default_factory=dict)
    # Expected keys: model, model_limit, total_used, system_tokens,
    # message_tokens, free_tokens, buffer_tokens (all ints except model=str)


def load_checkpoint(workspace: Path) -> OrchestratorCheckpoint:
    path = workspace / ".swarm" / "orchestrator-checkpoint.json"
    if not path.exists():
        return OrchestratorCheckpoint()
    try:
        d = json.loads(path.read_text())
        if not isinstance(d, dict):
            return OrchestratorCheckpoint()
        return OrchestratorCheckpoint(
            cycle=d.get("cycle", 0), phase=d.get("phase", "starting"),
            mode=d.get("mode", "discover"), rigor=d.get("rigor", "adaptive"),
            lifecycle_phase=d.get("lifecycle_phase", ""),
            hypotheses_summary=d.get("hypotheses_summary", ""),
            total_tasks=d.get("total_tasks", 0), closed_tasks=d.get("closed_tasks", 0),
            active_workers=d.get("active_workers", []),
            recent_events=d.get("recent_events", []),
            recent_decisions=d.get("recent_decisions", []),
            dead_ends=d.get("dead_ends", []),
            next_actions=d.get("next_actions", []),
            criteria_status=d.get("criteria_status", {}),
            eval_score=d.get("eval_score", 0.0),
            improvement_rounds=d.get("improvement_rounds", 0),
            last_updated=d.get("last_updated", ""),
            tokens_this_cycle=d.get("tokens_this_cycle", 0),
            tokens_cumulative=d.get("tokens_cumulative", 0),
            context_window_remaining_pct=d.get("context_window_remaining_pct", 1.0),
            context_snapshot=d.get("context_snapshot", {}),
        )
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load orchestrator checkpoint: %s", e)
        return OrchestratorCheckpoint()


def save_checkpoint(workspace: Path, cp: OrchestratorCheckpoint) -> None:
    path = workspace / ".swarm" / "orchestrator-checkpoint.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    cp.last_updated = datetime.now(timezone.utc).isoformat()
    cp.recent_events = cp.recent_events[-5:]
    cp.recent_decisions = cp.recent_decisions[-5:]
    path.write_text(json.dumps(asdict(cp), indent=2))


def format_checkpoint_for_prompt(cp: OrchestratorCheckpoint) -> str:
    lines = [f"## Checkpoint (cycle {cp.cycle}, phase: {cp.phase})\n",
             f"Mode: {cp.mode} | Rigor: {cp.rigor}",
             f"Tasks: {cp.closed_tasks}/{cp.total_tasks} done"]
    if cp.active_workers:
        lines.append(f"Active workers: {', '.join(cp.active_workers)}")
    if cp.hypotheses_summary:
        lines.append(f"Hypotheses: {cp.hypotheses_summary}")
    if cp.criteria_status:
        met = sum(1 for v in cp.criteria_status.values() if v)
        details = ", ".join(f"{k}:{'met' if v else 'pending'}" for k, v in cp.criteria_status.items())
        lines.append(f"Success criteria: {met}/{len(cp.criteria_status)} met ({details})")
    if cp.eval_score > 0:
        lines.append(f"Quality score: {cp.eval_score:.2f} (round {cp.improvement_rounds})")
    if cp.tokens_cumulative > 0:
        lines.append(f"Token budget: {cp.tokens_this_cycle:,} this cycle, "
                     f"{cp.tokens_cumulative:,} cumulative "
                     f"({cp.context_window_remaining_pct:.0%} window remaining)")
    if cp.context_snapshot:
        snap = cp.context_snapshot
        model = snap.get("model", "")
        limit = snap.get("model_limit", 0)
        sys_tok = snap.get("system_tokens", 0)
        msg_tok = snap.get("message_tokens", 0)
        free_tok = snap.get("free_tokens", 0)
        if limit:
            lines.append(
                f"Context ({model}): system={sys_tok:,} messages={msg_tok:,} "
                f"free={free_tok:,} / {limit:,}"
            )
    if cp.recent_events:
        lines.append("\nRecent events:")
        lines.extend(f"  - {e}" for e in cp.recent_events)
    if cp.next_actions:
        lines.append("\nPlanned next:")
        lines.extend(f"  - {a}" for a in cp.next_actions)
    if cp.dead_ends:
        lines.append("\nDead ends (DO NOT re-explore):")
        lines.extend(f"  - {d}" for d in cp.dead_ends)
    return "\n".join(lines)


# ===================================================================
# Convergence Detection
# ===================================================================

@dataclass
class ConvergenceResult:
    converged: bool
    status: str
    reason: str
    score: float = 0.0
    blockers: list[str] = field(default_factory=list)


# -- Red Team verdict gate (INV-47) -----------------------------------------


_RED_TEAM_VERDICT_FILE = "red-team-verdict.json"
_RED_TEAM_PASS_VERDICTS = {"pass", "pass_with_caveats"}
_RED_TEAM_FAIL_VERDICT = "fatal_flaw"


def _check_red_team_verdict(workspace: Path) -> list[str]:
    """Return blockers if the Red Team verdict is missing or fatal.

    Scientific+ rigor requires an independent adversarial reviewer to have
    inspected the deliverable and written `.swarm/red-team-verdict.json`
    with a `verdict` field in {pass, pass_with_caveats, fatal_flaw}.
    Missing file, unparseable JSON, or fatal_flaw verdict all block
    convergence — the orchestrator must dispatch the red-team agent (or
    address the flagged flaw) before retrying.
    """
    path = workspace / ".swarm" / _RED_TEAM_VERDICT_FILE
    if not path.exists():
        return ["Red Team review missing — dispatch the red-team agent"]
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return ["Red Team verdict file is unreadable — re-run the red-team agent"]
    verdict = (data.get("verdict") or "").strip().lower()
    if verdict == _RED_TEAM_FAIL_VERDICT:
        reason = data.get("reason", "fatal flaw identified")
        return [f"Red Team blocked convergence: {reason}"]
    if verdict not in _RED_TEAM_PASS_VERDICTS:
        return [f"Red Team verdict is invalid: {verdict or '(missing)'}"]
    return []


def check_convergence(workspace: Path, rigor: str,
                      eval_score: float = 0.0,
                      improvement_rounds: int = 0) -> ConvergenceResult:
    blockers: list[str] = []
    swarm = workspace / ".swarm"

    # --- Interpretive Coherence Gate (Analytical+, includes adaptive) ---
    # Must run before any early-return path so that tribunal/reversal
    # blockers are enforced for ALL rigor levels.  See INV-42 and INV-43.
    tribunal_clear, tribunal_blockers = _interp.check_tribunal_clear(workspace)
    if not tribunal_clear:
        blockers.extend(tribunal_blockers)

    has_reversed, reversed_blockers = _interp.has_reversed_hypotheses(workspace)
    if has_reversed:
        blockers.extend(reversed_blockers)

    if rigor == "adaptive":
        if not (swarm / "deliverable.md").exists():
            blockers.append("No deliverable produced")
        if blockers:
            return ConvergenceResult(False, "not_ready", "; ".join(blockers), blockers=blockers)
        # Adaptive rigor: basic convergence if eval score present, otherwise just deliverable
        if eval_score >= 0.75 and not blockers:
            return ConvergenceResult(True, "converged", "Evaluator PASS", score=eval_score)
        # If score is moderate but ALL success criteria are met, allow convergence
        # rather than blocking indefinitely for a higher score
        if eval_score >= 0.50 and _all_criteria_met(workspace):
            return ConvergenceResult(
                True, "converged",
                f"All success criteria met (score={eval_score:.2f})",
                score=eval_score,
            )
        if eval_score >= 0.50 and improvement_rounds < 2:
            return ConvergenceResult(False, "not_ready",
                                     f"Score {eval_score:.2f} — improvement round needed",
                                     score=eval_score, blockers=blockers)
        if eval_score <= 0.0 and improvement_rounds == 0:
            return ConvergenceResult(True, "converged", "All tasks complete")
        if eval_score <= 0.0 and improvement_rounds >= 1:
            # Evaluator was attempted but scored zero — diminishing returns
            return ConvergenceResult(True, "diminishing_returns",
                                     f"Max improvement rounds reached (score=0.0)",
                                     score=eval_score)
        # Score in (0.0, 0.50): needs improvement if rounds remain
        if eval_score < 0.50 and improvement_rounds < 2:
            return ConvergenceResult(False, "not_ready",
                                     f"Score {eval_score:.2f} — improvement round needed",
                                     score=eval_score, blockers=blockers)
        if improvement_rounds >= 2:
            return ConvergenceResult(True, "diminishing_returns",
                                     f"Max improvement rounds reached (score={eval_score:.2f})",
                                     score=eval_score)
        return ConvergenceResult(True, "converged", "All tasks complete")

    # For scientific/experimental rigor: full convergence checks
    if eval_score <= 0.0:
        blockers.append("No evaluator score yet")

    tasks = _helpers._fetch_tasks(workspace)
    design_invalid = _helpers._find_design_invalid(workspace, tasks)
    if design_invalid:
        blockers.append(f"{len(design_invalid)} DESIGN_INVALID experiment(s) — fix before converging")
    blockers.extend(_check_success_criteria(workspace))
    blockers.extend(_check_hypothesis_alignment(workspace, tasks))
    conflicts = _helpers._find_consistency_conflicts(workspace, tasks)
    if conflicts:
        blockers.append(f"{len(conflicts)} unresolved consistency conflicts")
    contested = _helpers._find_contested_findings(workspace, tasks)
    if contested:
        blockers.append(f"{len(contested)} contested findings")

    # Tribunal and reversed-hypothesis checks already ran above (before
    # the adaptive early-return) — no need to duplicate here.

    if rigor in ("scientific", "experimental"):
        bm = load_belief_map(workspace)
        if not bm.hypotheses:
            blockers.append("No hypotheses in belief map")
        elif not bm.all_resolved():
            unresolved = [h.name for h in bm.hypotheses
                          if h.status in ("untested", "testing")]
            blockers.append(f"Unresolved hypotheses: {', '.join(unresolved[:3])}")
        theories = _helpers._find_theories(workspace, tasks)
        if not any(t.get("status") == "refuted" for t in theories):
            blockers.append("No competing theory ruled out yet")
        if not _helpers._find_tested_predictions(workspace, tasks):
            blockers.append("No novel prediction tested")
        fragile = _helpers._find_undocumented_fragile(workspace, tasks)
        if fragile:
            blockers.append(f"{len(fragile)} fragile findings without conditions documented")

        # Red Team gate (INV-47): scientific+ rigor requires an independent
        # adversarial review verdict in .swarm/red-team-verdict.json before
        # convergence is permitted.  A fatal_flaw verdict blocks; pass or
        # pass_with_caveats allows the normal downstream gates to decide.
        rt_blockers = _check_red_team_verdict(workspace)
        blockers.extend(rt_blockers)

    if rigor == "experimental":
        unreplicated = _helpers._find_unreplicated_high_impact(workspace, tasks)
        if unreplicated:
            blockers.append(f"{len(unreplicated)} high-impact findings not yet replicated")

    if eval_score >= 0.75 and not blockers:
        return ConvergenceResult(True, "converged", f"All criteria met (score={eval_score:.2f})", score=eval_score)
    # If score is moderate but ALL success criteria are met and no other
    # blockers, allow convergence — prevents agents from looping until
    # context exhaustion when the actual investigation goals are satisfied.
    if eval_score >= 0.50 and not blockers and _all_criteria_met(workspace):
        return ConvergenceResult(
            True, "converged",
            f"All success criteria met (score={eval_score:.2f})",
            score=eval_score,
        )
    if improvement_rounds >= 2 and not blockers:
        return ConvergenceResult(True, "diminishing_returns", "Max improvement rounds, blockers cleared", score=eval_score)
    if blockers:
        # Check for valid negative result: deliverable exists, experiments ran,
        # but hypothesis was falsified (criteria unmet by design, not by bug).
        has_deliverable = (swarm / "deliverable.md").exists()
        has_contradiction = any("RESULT_CONTRADICTS_HYPOTHESIS" in b for b in blockers)
        # Also check task notes for contradictions (closed tasks don't produce blockers)
        if not has_contradiction and tasks:
            has_contradiction = any(
                "RESULT_CONTRADICTS_HYPOTHESIS" in t.get("notes", "")
                for t in tasks if isinstance(t, dict)
            )
        # A negative result needs: deliverable + eval score + no DESIGN_INVALID
        no_design_invalid = not any("DESIGN_INVALID" in b for b in blockers)
        if (has_deliverable and eval_score >= 0.50 and no_design_invalid
                and has_contradiction and improvement_rounds >= 1):
            return ConvergenceResult(
                True, "negative_result",
                f"Valid negative result — hypothesis falsified (score={eval_score:.2f})",
                score=eval_score,
                blockers=blockers,
            )
        return ConvergenceResult(False, "blocked", "; ".join(blockers), score=eval_score, blockers=blockers)
    return ConvergenceResult(False, "not_ready", "Evaluation in progress", score=eval_score)


def write_convergence(workspace: Path, result: ConvergenceResult) -> Path:
    path = workspace / ".swarm" / "convergence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "status": result.status, "converged": result.converged,
        "reason": result.reason, "score": result.score, "blockers": result.blockers,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }, indent=2))
    return path


def _all_criteria_met(workspace: Path) -> bool:
    """Return True if success-criteria.json exists AND every criterion is met."""
    path = workspace / ".swarm" / "success-criteria.json"
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, list) or not data:
            return False
    except (json.JSONDecodeError, OSError):
        return False
    return all(c.get("met", False) for c in data if isinstance(c, dict))


def _check_success_criteria(workspace: Path) -> list[str]:
    path = workspace / ".swarm" / "success-criteria.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            return []
    except (json.JSONDecodeError, OSError):
        return []
    return [f"Success criterion {c.get('id', '?')} not met: {c.get('description', '')}"
            for c in data if isinstance(c, dict) and not c.get("met", False)]


def _check_hypothesis_alignment(workspace: Path, tasks: list[dict] | None = None) -> list[str]:
    blockers: list[str] = []
    if tasks is None:
        tasks = _helpers._fetch_tasks(workspace)
    if tasks:
        for t in tasks:
            notes = t.get("notes", "")
            if "RESULT_CONTRADICTS_HYPOTHESIS" in notes and t.get("status") != "closed":
                blockers.append(
                    f"Result contradicts hypothesis in task {t.get('id', '?')}: "
                    f"{extract_field(notes, 'RESULT_CONTRADICTS_HYPOTHESIS')}")
    return blockers
