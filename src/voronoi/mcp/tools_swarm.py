""".swarm/ state file tools — validated JSON writes for orchestrator state.

Each tool reads/writes a specific ``.swarm/`` file with schema enforcement.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from voronoi.beads import run_bd_json
from voronoi.mcp.validators import (
    ValidationError,
    require_enum,
    require_non_empty,
    require_probability,
    sanitize_tsv_field,
    VALID_CHECKPOINT_PHASES,
    VALID_EXPERIMENT_STATUSES,
)

logger = logging.getLogger("voronoi.mcp.tools_swarm")


def _workspace_path() -> Path:
    return Path(os.environ.get("VORONOI_WORKSPACE", ".")).resolve()


def _swarm_dir() -> Path:
    d = _workspace_path() / ".swarm"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _optional_non_negative_int(value: Any, field: str) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a non-negative integer, got {value!r}")
    if number < 0:
        raise ValidationError(f"{field} must be non-negative, got {number}")
    return number


def _optional_str_list(value: Any, field: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, (list, tuple)):
        raise ValidationError(f"{field} must be a list, got {type(value).__name__}")
    return [str(item) for item in value]


# ---------------------------------------------------------------------------
# voronoi_write_checkpoint
# ---------------------------------------------------------------------------

def write_checkpoint(
    cycle: Any,
    phase: str,
    total_tasks: Any = None,
    closed_tasks: Any = None,
    hypotheses_summary: str = "",
    active_workers: Any = None,
    recent_events: Any = None,
    recent_decisions: Any = None,
    dead_ends: Any = None,
    next_actions: Any = None,
    eval_score: Any = None,
    context_window_remaining_pct: Any = None,
    mode: str = "",
    rigor: str = "",
    criteria_status: Any = None,
    improvement_rounds: Any = None,
    tokens_this_cycle: Any = None,
    tokens_cumulative: Any = None,
) -> dict[str, Any]:
    """Write orchestrator checkpoint with schema validation.

    Parameters
    ----------
    cycle : int
        OODA cycle number (must be non-negative).
    phase : str
        Current investigation phase (validated enum).
    total_tasks, closed_tasks : int
        Task progress counters.
    hypotheses_summary : str
        Compact hypothesis status (e.g. 'H1:confirmed, H2:testing').
    active_workers : list[str]
        Branch names of running agents.
    recent_events, recent_decisions : list[str]
        Rolling windows.
    dead_ends : list[str]
        Approaches to not re-explore.
    next_actions : list[str]
        Orchestrator TODO list.
    eval_score : float
        Latest evaluator quality score.
    context_window_remaining_pct : float
        Estimated remaining context (0.0–1.0).
    """
    from voronoi.science.convergence import load_checkpoint, save_checkpoint

    cycle_val = int(cycle) if cycle is not None and cycle != "" else 0
    if cycle_val < 0:
        raise ValidationError("cycle must be non-negative")

    phase = require_enum(phase, VALID_CHECKPOINT_PHASES, "phase")
    workspace = _workspace_path()
    checkpoint = load_checkpoint(workspace)
    checkpoint.cycle = cycle_val
    checkpoint.phase = phase
    if mode:
        checkpoint.mode = mode
    if rigor:
        checkpoint.rigor = rigor
    total_tasks_val = _optional_non_negative_int(total_tasks, "total_tasks")
    if total_tasks_val is not None:
        checkpoint.total_tasks = total_tasks_val
    closed_tasks_val = _optional_non_negative_int(closed_tasks, "closed_tasks")
    if closed_tasks_val is not None:
        checkpoint.closed_tasks = closed_tasks_val
    if hypotheses_summary:
        checkpoint.hypotheses_summary = hypotheses_summary
    active_workers_val = _optional_str_list(active_workers, "active_workers")
    if active_workers_val is not None:
        checkpoint.active_workers = active_workers_val
    recent_events_val = _optional_str_list(recent_events, "recent_events")
    if recent_events_val is not None:
        checkpoint.recent_events = recent_events_val
    recent_decisions_val = _optional_str_list(recent_decisions, "recent_decisions")
    if recent_decisions_val is not None:
        checkpoint.recent_decisions = recent_decisions_val
    dead_ends_val = _optional_str_list(dead_ends, "dead_ends")
    if dead_ends_val is not None:
        checkpoint.dead_ends = dead_ends_val
    next_actions_val = _optional_str_list(next_actions, "next_actions")
    if next_actions_val is not None:
        checkpoint.next_actions = next_actions_val
    if criteria_status is not None:
        if not isinstance(criteria_status, dict):
            raise ValidationError(f"criteria_status must be a dict, got {type(criteria_status).__name__}")
        checkpoint.criteria_status = {str(key): bool(value) for key, value in criteria_status.items()}
    if eval_score is not None and eval_score != "":
        checkpoint.eval_score = require_probability(eval_score, "eval_score")
    improvement_rounds_val = _optional_non_negative_int(improvement_rounds, "improvement_rounds")
    if improvement_rounds_val is not None:
        checkpoint.improvement_rounds = improvement_rounds_val
    tokens_this_cycle_val = _optional_non_negative_int(tokens_this_cycle, "tokens_this_cycle")
    if tokens_this_cycle_val is not None:
        checkpoint.tokens_this_cycle = tokens_this_cycle_val
    tokens_cumulative_val = _optional_non_negative_int(tokens_cumulative, "tokens_cumulative")
    if tokens_cumulative_val is not None:
        checkpoint.tokens_cumulative = tokens_cumulative_val
    if context_window_remaining_pct is not None and context_window_remaining_pct != "":
        checkpoint.context_window_remaining_pct = require_probability(
            context_window_remaining_pct,
            "context_window_remaining_pct",
        )

    save_checkpoint(workspace, checkpoint)
    return {
        "status": "written",
        "cycle": checkpoint.cycle,
        "phase": checkpoint.phase,
        "last_updated": checkpoint.last_updated,
    }


# ---------------------------------------------------------------------------
# voronoi_update_belief_map
# ---------------------------------------------------------------------------

def update_belief_map(
    hypothesis_id: str,
    name: str = "",
    posterior: Any = None,
    evidence_ids: Any = None,
    status: str = "",
) -> dict[str, Any]:
    """Update a hypothesis in the belief map with validated references.

    Parameters
    ----------
    hypothesis_id : str
        Hypothesis identifier (e.g. 'H1').
    name : str
        Human-readable hypothesis description.
    posterior : float
        Updated probability (0.0–1.0).
    evidence_ids : list[str]
        Beads task IDs that support/refute this hypothesis.
    status : str
        Hypothesis status (e.g. 'testing', 'confirmed', 'refuted').
    """
    from voronoi.science.convergence import Hypothesis, load_belief_map, save_belief_map

    hypothesis_id = require_non_empty(hypothesis_id, "hypothesis_id")

    if posterior is not None:
        posterior = require_probability(posterior, "posterior")
    workspace = _workspace_path()
    validated_evidence: list[str] | None = None
    if evidence_ids is not None:
        if not isinstance(evidence_ids, (list, tuple)):
            raise ValidationError(f"evidence_ids must be a list, got {type(evidence_ids).__name__}")
        validated_evidence = []
        for evidence_id in evidence_ids:
            evidence_task_id = require_non_empty(evidence_id, "evidence_id")
            code, task_data = run_bd_json("show", evidence_task_id, "--json", cwd=str(workspace))
            if code != 0 or not isinstance(task_data, dict):
                raise ValidationError(f"Unknown evidence task: {evidence_task_id}")
            validated_evidence.append(evidence_task_id)

    belief_map = load_belief_map(workspace)
    hypothesis = next((item for item in belief_map.hypotheses if item.id == hypothesis_id), None)
    if hypothesis is None:
        initial_posterior = posterior if posterior is not None else 0.5
        hypothesis = Hypothesis(
            id=hypothesis_id,
            name=name or hypothesis_id,
            prior=initial_posterior,
            posterior=initial_posterior,
            status=status or "untested",
            evidence=validated_evidence or [],
        )
        belief_map.hypotheses.append(hypothesis)
    else:
        if name:
            hypothesis.name = name
        if posterior is not None:
            hypothesis.posterior = posterior
        if status:
            hypothesis.status = status
        if validated_evidence is not None:
            hypothesis.evidence = validated_evidence

    save_belief_map(workspace, belief_map)

    return {
        "hypothesis_id": hypothesis_id,
        "posterior": hypothesis.posterior,
        "evidence_count": len(hypothesis.evidence),
        "status": "updated",
    }


# ---------------------------------------------------------------------------
# voronoi_update_success_criteria
# ---------------------------------------------------------------------------

def update_success_criteria(
    criteria_id: str,
    met: bool = False,
    evidence: str = "",
    description: str = "",
) -> dict[str, Any]:
    """Update a success criterion status.

    Parameters
    ----------
    criteria_id : str
        Criterion identifier (e.g. 'SC1').
    met : bool
        Whether the criterion is met.
    evidence : str
        Evidence or finding that satisfies the criterion.
    description : str
        Criterion description (for initial creation).
    """
    criteria_id = require_non_empty(criteria_id, "criteria_id")

    path = _swarm_dir() / "success-criteria.json"
    if path.exists():
        try:
            criteria = json.loads(path.read_text())
            if not isinstance(criteria, list):
                criteria = []
        except json.JSONDecodeError:
            criteria = []
    else:
        criteria = []

    # Find or create the criterion
    found = False
    for c in criteria:
        if isinstance(c, dict) and c.get("id") == criteria_id:
            c["met"] = bool(met)
            if evidence:
                c["evidence"] = evidence
            if description:
                c["description"] = description
            found = True
            break

    if not found:
        criteria.append({
            "id": criteria_id,
            "description": description or criteria_id,
            "met": bool(met),
            "evidence": evidence,
        })

    path.write_text(json.dumps(criteria, indent=2))

    return {"criteria_id": criteria_id, "met": met, "status": "updated"}


# ---------------------------------------------------------------------------
# voronoi_log_experiment
# ---------------------------------------------------------------------------

def log_experiment(
    task_id: str,
    branch: str,
    metric: str,
    value: Any,
    experiment_status: str,
    description: str = "",
) -> dict[str, Any]:
    """Append an experiment result to the ledger with validated status.

    Parameters
    ----------
    task_id : str
        Beads task ID.
    branch : str
        Git branch for this experiment.
    metric : str
        Metric name (e.g. 'MBRS', 'F1').
    value : float or str
        Metric value.
    experiment_status : str
        One of: keep, discard, crash, running.
    description : str
        Brief description of the experiment.
    """
    task_id = require_non_empty(task_id, "task_id")
    branch = require_non_empty(branch, "branch")
    metric = require_non_empty(metric, "metric")
    experiment_status = require_enum(experiment_status,
                                     VALID_EXPERIMENT_STATUSES,
                                     "experiment_status")

    swarm = _swarm_dir()
    tsv_path = swarm / "experiments.tsv"

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
    row = f"{timestamp}\t{sanitize_tsv_field(task_id)}\t{sanitize_tsv_field(branch)}\t{sanitize_tsv_field(metric)}\t{sanitize_tsv_field(str(value))}\t{experiment_status}\t{sanitize_tsv_field(description)}"

    if not tsv_path.exists():
        header = "timestamp\ttask_id\tbranch\tmetric\tvalue\tstatus\tdesc"
        tsv_path.write_text(header + "\n" + row + "\n")
    else:
        with open(tsv_path, "a") as f:
            f.write(row + "\n")

    return {
        "task_id": task_id,
        "metric": metric,
        "value": value,
        "experiment_status": experiment_status,
        "status": "logged",
    }
