"""Convergence detection — determines when an investigation is complete."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from voronoi.utils import extract_field

from voronoi.science.belief_map import load_belief_map
from voronoi.science import _helpers

logger = logging.getLogger("voronoi.science")


@dataclass
class ConvergenceResult:
    """Result of a convergence check."""
    converged: bool
    status: str  # converged, not_ready, blocked, exhausted, diminishing_returns
    reason: str
    score: float = 0.0  # evaluator score if available
    blockers: list[str] = field(default_factory=list)


def check_convergence(workspace: Path, rigor: str,
                      eval_score: float = 0.0,
                      improvement_rounds: int = 0) -> ConvergenceResult:
    """Check if an investigation meets convergence criteria for its rigor level."""
    blockers: list[str] = []
    swarm = workspace / ".swarm"

    # --- Standard: all tasks closed + tests passing ---
    if rigor == "standard":
        if not (swarm / "deliverable.md").exists():
            blockers.append("No deliverable produced")
        if blockers:
            return ConvergenceResult(False, "not_ready", "; ".join(blockers), blockers=blockers)
        return ConvergenceResult(True, "converged", "All build tasks complete")

    # --- Analytical+: evaluator score required ---
    if eval_score <= 0.0:
        blockers.append("No evaluator score yet")

    tasks = _helpers._fetch_tasks(workspace)

    design_invalid = _helpers._find_design_invalid(workspace, tasks)
    if design_invalid:
        blockers.append(f"{len(design_invalid)} DESIGN_INVALID experiment(s) — fix before converging")

    criteria_blockers = _check_success_criteria(workspace)
    blockers.extend(criteria_blockers)

    alignment_blockers = _check_hypothesis_alignment(workspace)
    blockers.extend(alignment_blockers)

    conflicts = _helpers._find_consistency_conflicts(workspace, tasks)
    if conflicts:
        blockers.append(f"{len(conflicts)} unresolved consistency conflicts")

    contested = _helpers._find_contested_findings(workspace, tasks)
    if contested:
        blockers.append(f"{len(contested)} contested findings")

    if rigor == "analytical":
        if eval_score >= 0.75:
            if not blockers:
                return ConvergenceResult(True, "converged", "Evaluator PASS", score=eval_score)
        elif eval_score >= 0.50 and improvement_rounds < 2:
            return ConvergenceResult(False, "not_ready",
                                     f"Score {eval_score:.2f} — improvement round needed",
                                     score=eval_score, blockers=blockers)
        elif improvement_rounds >= 2:
            return ConvergenceResult(True, "diminishing_returns",
                                     f"Max improvement rounds reached (score={eval_score:.2f})",
                                     score=eval_score)

    # --- Scientific+: hypothesis resolution required ---
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

        predictions = _helpers._find_tested_predictions(workspace, tasks)
        if not predictions:
            blockers.append("No novel prediction tested")

        fragile_undoc = _helpers._find_undocumented_fragile(workspace, tasks)
        if fragile_undoc:
            blockers.append(f"{len(fragile_undoc)} fragile findings without conditions documented")

    # --- Experimental: replication required ---
    if rigor == "experimental":
        unreplicated = _helpers._find_unreplicated_high_impact(workspace, tasks)
        if unreplicated:
            blockers.append(f"{len(unreplicated)} high-impact findings not yet replicated")

    if eval_score >= 0.75 and not blockers:
        return ConvergenceResult(True, "converged",
                                 f"All criteria met (score={eval_score:.2f})",
                                 score=eval_score)

    if improvement_rounds >= 2 and not blockers:
        return ConvergenceResult(True, "diminishing_returns",
                                 "Max improvement rounds, blockers cleared",
                                 score=eval_score)

    if blockers:
        return ConvergenceResult(False, "blocked", "; ".join(blockers),
                                 score=eval_score, blockers=blockers)

    return ConvergenceResult(False, "not_ready", "Evaluation in progress",
                             score=eval_score)


def write_convergence(workspace: Path, result: ConvergenceResult) -> Path:
    """Write convergence.json to the workspace."""
    path = workspace / ".swarm" / "convergence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "status": result.status,
        "converged": result.converged,
        "reason": result.reason,
        "score": result.score,
        "blockers": result.blockers,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(data, indent=2))
    return path


# --- Convergence sub-checks (private) ---

def _check_success_criteria(workspace: Path) -> list[str]:
    """Check .swarm/success-criteria.json and return blockers for unmet criteria."""
    path = workspace / ".swarm" / "success-criteria.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            return []
    except (json.JSONDecodeError, OSError):
        return []
    blockers: list[str] = []
    for criterion in data:
        if not isinstance(criterion, dict):
            continue
        cid = criterion.get("id", "?")
        met = criterion.get("met", False)
        desc = criterion.get("description", "")
        if not met:
            blockers.append(f"Success criterion {cid} not met: {desc}")
    return blockers


def _check_hypothesis_alignment(workspace: Path) -> list[str]:
    """Check if confirmed hypotheses align with actual result direction."""
    blockers: list[str] = []
    tasks = _helpers._fetch_tasks(workspace)
    if tasks:
        for t in tasks:
            notes = t.get("notes", "")
            if "RESULT_CONTRADICTS_HYPOTHESIS" in notes and t.get("status") != "closed":
                blockers.append(
                    f"Result contradicts hypothesis in task {t.get('id', '?')}: "
                    f"{extract_field(notes, 'RESULT_CONTRADICTS_HYPOTHESIS')}"
                )
    return blockers
