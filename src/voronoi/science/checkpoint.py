"""Orchestrator checkpoint — context management for long-running sessions."""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("voronoi.science")


@dataclass
class OrchestratorCheckpoint:
    """Compressed orchestrator state that survives context loss and restarts."""
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
    """Load orchestrator checkpoint from .swarm/orchestrator-checkpoint.json."""
    path = workspace / ".swarm" / "orchestrator-checkpoint.json"
    if not path.exists():
        return OrchestratorCheckpoint()
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            return OrchestratorCheckpoint()
        return OrchestratorCheckpoint(
            cycle=data.get("cycle", 0),
            phase=data.get("phase", "starting"),
            mode=data.get("mode", "investigate"),
            rigor=data.get("rigor", "standard"),
            hypotheses_summary=data.get("hypotheses_summary", ""),
            total_tasks=data.get("total_tasks", 0),
            closed_tasks=data.get("closed_tasks", 0),
            active_workers=data.get("active_workers", []),
            recent_events=data.get("recent_events", []),
            recent_decisions=data.get("recent_decisions", []),
            dead_ends=data.get("dead_ends", []),
            next_actions=data.get("next_actions", []),
            criteria_status=data.get("criteria_status", {}),
            eval_score=data.get("eval_score", 0.0),
            improvement_rounds=data.get("improvement_rounds", 0),
            last_updated=data.get("last_updated", ""),
        )
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load orchestrator checkpoint: %s", e)
        return OrchestratorCheckpoint()


def save_checkpoint(workspace: Path, cp: OrchestratorCheckpoint) -> None:
    """Save orchestrator checkpoint to .swarm/orchestrator-checkpoint.json."""
    path = workspace / ".swarm" / "orchestrator-checkpoint.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    cp.last_updated = datetime.now(timezone.utc).isoformat()
    cp.recent_events = cp.recent_events[-5:]
    cp.recent_decisions = cp.recent_decisions[-5:]
    data = asdict(cp)
    path.write_text(json.dumps(data, indent=2))


def format_checkpoint_for_prompt(cp: OrchestratorCheckpoint) -> str:
    """Format checkpoint as a compact prompt injection (~500 tokens max)."""
    lines = [
        f"## Checkpoint (cycle {cp.cycle}, phase: {cp.phase})\n",
        f"Mode: {cp.mode} | Rigor: {cp.rigor}",
        f"Tasks: {cp.closed_tasks}/{cp.total_tasks} done",
    ]

    if cp.active_workers:
        lines.append(f"Active workers: {', '.join(cp.active_workers)}")

    if cp.hypotheses_summary:
        lines.append(f"Hypotheses: {cp.hypotheses_summary}")

    if cp.criteria_status:
        met = sum(1 for v in cp.criteria_status.values() if v)
        total = len(cp.criteria_status)
        details = ", ".join(
            f"{k}:{'met' if v else 'pending'}"
            for k, v in cp.criteria_status.items()
        )
        lines.append(f"Success criteria: {met}/{total} met ({details})")

    if cp.eval_score > 0:
        lines.append(f"Quality score: {cp.eval_score:.2f} (round {cp.improvement_rounds})")

    if cp.recent_events:
        lines.append("\nRecent events:")
        for e in cp.recent_events:
            lines.append(f"  - {e}")

    if cp.next_actions:
        lines.append("\nPlanned next:")
        for a in cp.next_actions:
            lines.append(f"  - {a}")

    if cp.dead_ends:
        lines.append("\nDead ends (DO NOT re-explore):")
        for d in cp.dead_ends:
            lines.append(f"  - {d}")

    return "\n".join(lines)
