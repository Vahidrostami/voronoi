"""WorkspaceSnapshot — read-only capture of investigation workspace state.

Consolidates the phase-detection and workspace-reading logic previously
duplicated across the dispatcher, router, and progress modules into a
single read that can be passed around.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
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

        if tasks is None and not task_snapshot and checkpoint:
            total_tasks, closed_tasks, in_progress_tasks, ready_tasks = _checkpoint_task_counts(
                checkpoint
            )

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


def build_investigation_status(
    workspace_path: Path,
    snapshot: WorkspaceSnapshot,
    *,
    investigation_id: int,
    codename: str = "",
    mode: str = "",
    rigor: str = "",
    question: str = "",
    session_alive: bool = False,
    orchestrator_parked: bool = False,
    generated_at: datetime | None = None,
) -> dict:
    """Build the PI-facing status projection for an investigation."""
    generated = generated_at or datetime.now(timezone.utc)
    checkpoint = snapshot.checkpoint or {}
    active_workers = _coerce_str_list(checkpoint.get("active_workers"))
    next_actions = _coerce_str_list(checkpoint.get("next_actions"))
    recent_events = _coerce_str_list(checkpoint.get("recent_events"))
    ready_items = _task_items(snapshot.task_snapshot, {"open", "ready"})
    in_progress_items = _task_items(snapshot.task_snapshot, {"in_progress"})
    gates = _build_gates(workspace_path, snapshot)
    recommended_action = _recommended_action(
        gates=gates,
        ready_items=ready_items,
        in_progress_items=in_progress_items,
        active_workers=active_workers,
        snapshot=snapshot,
        session_alive=session_alive,
    )
    status = "parked" if orchestrator_parked else "running" if session_alive else "not_running"
    operator_summary = _operator_summary(snapshot, status, gates)

    return {
        "investigation_id": investigation_id,
        "codename": codename,
        "mode": mode,
        "rigor": rigor,
        "question": question,
        "phase": snapshot.phase,
        "status": status,
        "session_alive": session_alive,
        "orchestrator_parked": orchestrator_parked,
        "generated_at": generated.isoformat(),
        "tasks": {
            "total": snapshot.total_tasks,
            "closed": snapshot.closed_tasks,
            "in_progress": snapshot.in_progress_tasks,
            "ready": snapshot.ready_tasks,
            "in_progress_items": in_progress_items,
            "ready_items": ready_items,
        },
        "science": {
            "criteria_met": snapshot.criteria_met,
            "criteria_total": snapshot.criteria_total,
            "eval_score": snapshot.eval_score,
            "active_workers": active_workers,
            "next_actions": next_actions,
            "recent_events": recent_events,
        },
        "gates": gates,
        "operator_summary": operator_summary,
        "recommended_action": recommended_action,
    }


def write_investigation_status(workspace_path: Path, status: dict) -> None:
    """Persist run-status.json and health.md atomically."""
    swarm = workspace_path / ".swarm"
    swarm.mkdir(parents=True, exist_ok=True)
    _write_text_atomic(swarm / "run-status.json", json.dumps(status, indent=2) + "\n")
    _write_text_atomic(swarm / "health.md", format_health_markdown(status))


def format_health_markdown(status: dict) -> str:
    """Render a short Markdown operator view from run-status.json data."""
    tasks = status.get("tasks", {}) if isinstance(status.get("tasks"), dict) else {}
    science = status.get("science", {}) if isinstance(status.get("science"), dict) else {}
    gates = status.get("gates", {}) if isinstance(status.get("gates"), dict) else {}
    lines = [
        f"# Investigation Health: {status.get('codename') or '#' + str(status.get('investigation_id', ''))}",
        "",
        f"Status: {status.get('status', 'unknown')}",
        f"Phase: {status.get('phase', 'starting')}",
        f"Summary: {status.get('operator_summary', '')}",
        f"Recommended action: {status.get('recommended_action', 'inspect_workspace')}",
        "",
        "## Tasks",
        f"- Closed: {tasks.get('closed', 0)}/{tasks.get('total', 0)}",
        f"- In progress: {tasks.get('in_progress', 0)}",
        f"- Ready/open: {tasks.get('ready', 0)}",
    ]
    lines.extend(_format_task_lines("In progress work", tasks.get("in_progress_items", [])))
    lines.extend(_format_task_lines("Ready/open work", tasks.get("ready_items", [])))
    lines.extend([
        "",
        "## Science",
        f"- Success criteria: {science.get('criteria_met', 0)}/{science.get('criteria_total', 0)}",
        f"- Eval score: {science.get('eval_score', 0.0)}",
    ])
    active_workers = science.get("active_workers", [])
    if active_workers:
        lines.append(f"- Active workers: {', '.join(str(w) for w in active_workers)}")
    next_actions = science.get("next_actions", [])
    if next_actions:
        lines.append("- Next actions: " + "; ".join(str(a) for a in next_actions))
    lines.extend(["", "## Gates"])
    for key in sorted(gates):
        lines.append(f"- {key}: {gates[key]}")
    return "\n".join(lines).rstrip() + "\n"


def _build_gates(workspace_path: Path, snapshot: WorkspaceSnapshot) -> dict[str, str]:
    criteria = "pending"
    if snapshot.criteria_total > 0:
        criteria = f"{snapshot.criteria_met}/{snapshot.criteria_total}"
    return {
        "belief_map": "present" if snapshot.has_belief_map else "pending",
        "convergence": _convergence_gate(workspace_path, snapshot),
        "deliverable": "present" if snapshot.has_deliverable else "pending",
        "eval_score": f"{snapshot.eval_score:.3f}" if snapshot.eval_score else "pending",
        "sentinel": _sentinel_gate(workspace_path),
        "success_criteria": criteria,
    }


def _convergence_gate(workspace_path: Path, snapshot: WorkspaceSnapshot) -> str:
    if not snapshot.has_convergence:
        return "pending"
    path = workspace_path / ".swarm" / "convergence.json"
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return "present"
    if not isinstance(data, dict):
        return "present"
    status = data.get("status")
    if isinstance(status, str) and status:
        return status
    converged = data.get("converged")
    if converged is True:
        return "converged"
    if converged is False:
        return "not_converged"
    return "present"


def _sentinel_gate(workspace_path: Path) -> str:
    path = workspace_path / ".swarm" / "sentinel-audit.json"
    if not path.exists():
        return "pending"
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return "unknown"
    if not isinstance(data, dict):
        return "unknown"
    if data.get("passed") is True:
        return "passed"
    if data.get("passed") is False:
        return "failed"
    verdict = data.get("verdict") or data.get("status")
    if isinstance(verdict, str) and verdict:
        return verdict
    return "unknown"


def _recommended_action(
    *,
    gates: dict[str, str],
    ready_items: list[dict[str, str]],
    in_progress_items: list[dict[str, str]],
    active_workers: list[str],
    snapshot: WorkspaceSnapshot,
    session_alive: bool,
) -> str:
    if gates.get("sentinel") == "failed":
        return "fix_failed_gate"
    if ready_items:
        return "resolve_ready_work"
    if in_progress_items or active_workers or session_alive:
        return "wait_for_active_work"
    if snapshot.has_deliverable and not snapshot.has_convergence:
        return "run_convergence_check"
    if snapshot.has_deliverable and snapshot.has_convergence:
        return "review_results"
    if snapshot.total_tasks == 0:
        return "wait_for_orchestrator_plan"
    return "inspect_workspace"


def _operator_summary(snapshot: WorkspaceSnapshot, status: str, gates: dict[str, str]) -> str:
    if gates.get("sentinel") == "failed":
        return f"{snapshot.phase} is blocked by a failed sentinel gate."
    if snapshot.total_tasks:
        return (
            f"{status.capitalize()} {snapshot.phase} with "
            f"{snapshot.closed_tasks}/{snapshot.total_tasks} tasks closed."
        )
    return f"{status.capitalize()} {snapshot.phase}; no Beads tasks visible yet."


def _coerce_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            result.append(item)
        elif isinstance(item, dict):
            for key in ("branch", "id", "task_id", "name"):
                raw = item.get(key)
                if isinstance(raw, str) and raw:
                    result.append(raw)
                    break
    return result


def _checkpoint_task_counts(checkpoint: dict) -> tuple[int, int, int, int]:
    total = _coerce_non_negative_int(checkpoint.get("total_tasks"))
    closed = min(_coerce_non_negative_int(checkpoint.get("closed_tasks")), total)
    active_workers = _coerce_str_list(checkpoint.get("active_workers"))
    remaining = max(total - closed, 0)
    in_progress = min(len(active_workers), remaining)
    ready = max(remaining - in_progress, 0)
    return total, closed, in_progress, ready


def _coerce_non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    return max(number, 0)


def _task_items(
    task_snapshot: dict,
    statuses: set[str],
    *,
    limit: int = 5,
) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for task_id, task in task_snapshot.items():
        if not isinstance(task, dict):
            continue
        status = str(task.get("status", ""))
        if status not in statuses:
            continue
        items.append({
            "id": str(task_id),
            "title": str(task.get("title", "")),
            "status": status,
        })
        if len(items) >= limit:
            break
    return items


def _format_task_lines(title: str, items: object) -> list[str]:
    if not isinstance(items, list) or not items:
        return []
    lines = [f"- {title}:"]
    for item in items[:5]:
        if not isinstance(item, dict):
            continue
        task_id = item.get("id", "")
        task_title = item.get("title", "")
        lines.append(f"  - {task_id}: {task_title}")
    return lines


def _write_text_atomic(path: Path, text: str) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(text)
    tmp_path.replace(path)


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
