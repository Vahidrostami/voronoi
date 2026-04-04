"""WorkspaceSnapshot — read-only capture of investigation workspace state.

Consolidates the phase-detection and workspace-reading logic previously
duplicated across the dispatcher, router, and progress modules into a
single read that can be passed around.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("voronoi.snapshot")


@dataclass
class WorkspaceSnapshot:
    """Read-only snapshot of .swarm/ workspace state.

    Built once per poll/request cycle.  All consumers (dispatcher,
    router, progress formatters) read from this instead of probing
    the filesystem independently.
    """

    phase: str = "starting"
    total_tasks: int = 0
    closed_tasks: int = 0
    in_progress_tasks: int = 0
    ready_tasks: int = 0
    has_deliverable: bool = False
    has_convergence: bool = False
    has_belief_map: bool = False
    has_scout_brief: bool = False
    eval_score: float = 0.0
    criteria_met: int = 0
    criteria_total: int = 0
    checkpoint: dict | None = None
    task_snapshot: dict = field(default_factory=dict)

    @classmethod
    def from_workspace(
        cls,
        workspace_path: Path,
        tasks: list[dict] | None = None,
        old_phase: str = "",
    ) -> "WorkspaceSnapshot":
        """Build a snapshot by reading .swarm/ files and optional task list.

        Parameters
        ----------
        workspace_path : Path
            Root of the investigation workspace.
        tasks : list[dict] | None
            Pre-fetched Beads task list (avoids a subprocess call).
            Each dict should have ``id``, ``status``, ``title``, ``notes``.
        old_phase : str
            Previous phase — used for scouting→planning transition.
        """
        swarm = workspace_path / ".swarm"

        has_deliverable = (swarm / "deliverable.md").exists()
        has_convergence = (swarm / "convergence.json").exists()
        has_belief_map = (swarm / "belief-map.json").exists() or (swarm / "belief-map.md").exists()
        has_scout_brief = (swarm / "scout-brief.md").exists()

        # --- Task counts ---
        task_snapshot: dict = {}
        total_tasks = 0
        closed_tasks = 0
        in_progress_tasks = 0
        ready_tasks = 0
        if tasks is not None:
            for t in tasks:
                tid = t.get("id", "")
                st = t.get("status", "")
                task_snapshot[tid] = {
                    "status": st,
                    "title": t.get("title", ""),
                    "notes": t.get("notes", ""),
                }
                total_tasks += 1
                if st == "closed":
                    closed_tasks += 1
                elif st == "in_progress":
                    in_progress_tasks += 1
                elif st in ("open", "ready"):
                    ready_tasks += 1

        # --- Eval score ---
        eval_score = 0.0
        eval_path = swarm / "eval-score.json"
        if eval_path.exists():
            try:
                data = json.loads(eval_path.read_text())
                if isinstance(data, dict):
                    score = float(data.get("score", 0.0))
                    if 0.0 <= score <= 1.0:
                        eval_score = score
            except (json.JSONDecodeError, OSError, ValueError):
                pass

        # --- Success criteria ---
        criteria_met = 0
        criteria_total = 0
        sc_path = swarm / "success-criteria.json"
        if sc_path.exists():
            try:
                criteria = json.loads(sc_path.read_text())
                if isinstance(criteria, list):
                    criteria_total = len(criteria)
                    criteria_met = sum(1 for c in criteria if isinstance(c, dict) and c.get("met"))
            except (json.JSONDecodeError, OSError):
                pass

        # --- Checkpoint ---
        checkpoint: dict | None = None
        from voronoi.utils import find_checkpoint
        cp_path = find_checkpoint(workspace_path)
        if cp_path is not None:
            try:
                data = json.loads(cp_path.read_text())
                if isinstance(data, dict):
                    checkpoint = data
            except (json.JSONDecodeError, OSError):
                pass

        # --- Phase detection ---
        phase = _detect_phase(
            has_deliverable=has_deliverable,
            has_convergence=has_convergence,
            has_belief_map=has_belief_map,
            has_scout_brief=has_scout_brief,
            task_snapshot=task_snapshot,
            total_tasks=total_tasks,
            closed_tasks=closed_tasks,
            in_progress_tasks=in_progress_tasks,
            checkpoint=checkpoint,
            old_phase=old_phase,
        )

        return cls(
            phase=phase,
            total_tasks=total_tasks,
            closed_tasks=closed_tasks,
            in_progress_tasks=in_progress_tasks,
            ready_tasks=ready_tasks,
            has_deliverable=has_deliverable,
            has_convergence=has_convergence,
            has_belief_map=has_belief_map,
            has_scout_brief=has_scout_brief,
            eval_score=eval_score,
            criteria_met=criteria_met,
            criteria_total=criteria_total,
            checkpoint=checkpoint,
            task_snapshot=task_snapshot,
        )


def _detect_phase(
    *,
    has_deliverable: bool,
    has_convergence: bool,
    has_belief_map: bool,
    has_scout_brief: bool,
    task_snapshot: dict,
    total_tasks: int,
    closed_tasks: int,
    in_progress_tasks: int,
    checkpoint: dict | None,
    old_phase: str,
) -> str:
    """Derive investigation phase from workspace artifacts.

    This is the single source of truth for phase detection.
    Previously duplicated in dispatcher._detect_phase() and
    router.handle_whatsup().
    """
    # Checkpoint may declare phase explicitly
    if checkpoint:
        phase = checkpoint.get("phase", "")
        if isinstance(phase, str) and phase:
            # Checkpoint phase is authoritative when the orchestrator sets it
            return phase

    if has_deliverable:
        return "complete"
    if has_convergence:
        return "converging"
    if has_belief_map and total_tasks > 0:
        return "synthesizing"
    if has_scout_brief and old_phase == "scouting":
        return "planning"

    if task_snapshot:
        titles = [t.get("title", "") for t in task_snapshot.values()]
        has_scout = any("scout" in t.lower() for t in titles)
        has_review = any(
            k in " ".join(titles).upper()
            for k in ("STAT_REVIEW", "CRITIC_REVIEW", "METHODOLOGIST")
        )

        if has_scout and closed_tasks == 0 and in_progress_tasks > 0:
            return "scouting"
        if has_review and in_progress_tasks > 0:
            return "reviewing"
        if in_progress_tasks > 0 or closed_tasks > 0:
            return "investigating"
        if total_tasks > 0:
            return "planning"

    if total_tasks > 0:
        if in_progress_tasks > 0:
            return "investigating"
        return "planning"

    return "starting"
