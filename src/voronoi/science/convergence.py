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
from voronoi.science import _helpers

logger = logging.getLogger("voronoi.science")


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

    @property
    def uncertainty(self) -> float:
        return 1.0 - abs(self.posterior - 0.5) * 2

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
        bm = BeliefMap(cycle=data.get("cycle", 0), last_updated=data.get("last_updated", ""))
        for h in data.get("hypotheses", []):
            bm.hypotheses.append(Hypothesis(
                id=h.get("id", ""), name=h.get("name", ""),
                prior=h.get("prior", 0.5), posterior=h.get("posterior", h.get("prior", 0.5)),
                status=h.get("status", "untested"), evidence=h.get("evidence", []),
                testability=h.get("testability", 0.5), impact=h.get("impact", 0.5),
            ))
        return bm
    except (json.JSONDecodeError, OSError) as e:
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
# Orchestrator Checkpoint
# ===================================================================

@dataclass
class OrchestratorCheckpoint:
    cycle: int = 0
    phase: str = "starting"
    mode: str = "investigate"
    rigor: str = "standard"
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
            mode=d.get("mode", "investigate"), rigor=d.get("rigor", "standard"),
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


def check_convergence(workspace: Path, rigor: str,
                      eval_score: float = 0.0,
                      improvement_rounds: int = 0) -> ConvergenceResult:
    blockers: list[str] = []
    swarm = workspace / ".swarm"

    if rigor == "standard":
        if not (swarm / "deliverable.md").exists():
            blockers.append("No deliverable produced")
        if blockers:
            return ConvergenceResult(False, "not_ready", "; ".join(blockers), blockers=blockers)
        return ConvergenceResult(True, "converged", "All build tasks complete")

    if eval_score <= 0.0:
        blockers.append("No evaluator score yet")

    tasks = _helpers._fetch_tasks(workspace)
    design_invalid = _helpers._find_design_invalid(workspace, tasks)
    if design_invalid:
        blockers.append(f"{len(design_invalid)} DESIGN_INVALID experiment(s) — fix before converging")
    blockers.extend(_check_success_criteria(workspace))
    blockers.extend(_check_hypothesis_alignment(workspace))
    conflicts = _helpers._find_consistency_conflicts(workspace, tasks)
    if conflicts:
        blockers.append(f"{len(conflicts)} unresolved consistency conflicts")
    contested = _helpers._find_contested_findings(workspace, tasks)
    if contested:
        blockers.append(f"{len(contested)} contested findings")

    if rigor == "analytical":
        if eval_score >= 0.75 and not blockers:
            return ConvergenceResult(True, "converged", "Evaluator PASS", score=eval_score)
        if eval_score >= 0.50 and improvement_rounds < 2:
            return ConvergenceResult(False, "not_ready",
                                     f"Score {eval_score:.2f} — improvement round needed",
                                     score=eval_score, blockers=blockers)
        if improvement_rounds >= 2:
            return ConvergenceResult(True, "diminishing_returns",
                                     f"Max improvement rounds reached (score={eval_score:.2f})",
                                     score=eval_score)

    if rigor in ("scientific", "experimental"):
        bm = load_belief_map(workspace)
        if not bm.hypotheses:
            blockers.append("No hypotheses in belief map")
        elif not bm.all_resolved():
            unresolved = [h.name for h in bm.hypotheses if h.status in ("untested", "testing")]
            blockers.append(f"Unresolved hypotheses: {', '.join(unresolved[:3])}")
        theories = _helpers._find_theories(workspace, tasks)
        if not any(t.get("status") == "refuted" for t in theories):
            blockers.append("No competing theory ruled out yet")
        if not _helpers._find_tested_predictions(workspace, tasks):
            blockers.append("No novel prediction tested")
        fragile = _helpers._find_undocumented_fragile(workspace, tasks)
        if fragile:
            blockers.append(f"{len(fragile)} fragile findings without conditions documented")

    if rigor == "experimental":
        unreplicated = _helpers._find_unreplicated_high_impact(workspace, tasks)
        if unreplicated:
            blockers.append(f"{len(unreplicated)} high-impact findings not yet replicated")

    if eval_score >= 0.75 and not blockers:
        return ConvergenceResult(True, "converged", f"All criteria met (score={eval_score:.2f})", score=eval_score)
    if improvement_rounds >= 2 and not blockers:
        return ConvergenceResult(True, "diminishing_returns", "Max improvement rounds, blockers cleared", score=eval_score)
    if blockers:
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


def _check_hypothesis_alignment(workspace: Path) -> list[str]:
    blockers: list[str] = []
    tasks = _helpers._fetch_tasks(workspace)
    if tasks:
        for t in tasks:
            notes = t.get("notes", "")
            if "RESULT_CONTRADICTS_HYPOTHESIS" in notes and t.get("status") != "closed":
                blockers.append(
                    f"Result contradicts hypothesis in task {t.get('id', '?')}: "
                    f"{extract_field(notes, 'RESULT_CONTRADICTS_HYPOTHESIS')}")
    return blockers
