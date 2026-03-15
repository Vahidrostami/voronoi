"""Shared internal helpers for the science subpackage."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from voronoi.beads import run_bd as _run_bd
from voronoi.utils import extract_field

logger = logging.getLogger("voronoi.science")


def _fetch_tasks(workspace: Path) -> list[dict] | None:
    """Fetch all tasks from Beads once.  Returns None on failure."""
    code, output = _run_bd("list", "--json", cwd=str(workspace))
    if code != 0:
        logger.warning("bd list --json failed (exit=%d) in %s", code, workspace)
        return None
    if not output:
        return None
    try:
        data = json.loads(output)
        if not isinstance(data, list):
            logger.warning("bd list --json returned non-list: %s", type(data).__name__)
            return None
        return data
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("bd list --json returned invalid JSON in %s: %s", workspace, e)
        return None


def _find_consistency_conflicts(workspace: Path, tasks: list[dict] | None = None) -> list[dict]:
    """Find unresolved consistency conflicts in the workspace."""
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []

    conflicts = []
    for task in tasks:
        notes = task.get("notes", "")
        if "CONSISTENCY_CONFLICT" in notes and task.get("status") != "closed":
            conflict_val = extract_field(notes, "CONSISTENCY_CONFLICT")
            if " vs " in conflict_val:
                parts = conflict_val.split(" vs ")
                finding_a = parts[0].strip()
                finding_b = parts[-1].strip()
            else:
                finding_a = ""
                finding_b = ""
            conflicts.append({
                "id": task.get("id", ""),
                "finding_a": finding_a,
                "finding_b": finding_b,
            })
    return conflicts


def _find_contested_findings(workspace: Path, tasks: list[dict] | None = None) -> list[str]:
    """Find findings marked CONTESTED."""
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    return [t.get("id", "") for t in tasks
            if "ADVERSARIAL_RESULT: CONTESTED" in t.get("notes", "")]


def _find_theories(workspace: Path, tasks: list[dict] | None = None) -> list[dict]:
    """Find theory entries in Beads."""
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    theories = []
    for t in tasks:
        notes = t.get("notes", "")
        if "TYPE:theory" in notes:
            status = extract_field(notes, "STATUS")
            theories.append({"id": t.get("id", ""), "status": status})
    return theories


def _find_tested_predictions(workspace: Path, tasks: list[dict] | None = None) -> list[str]:
    """Find predictions that have been tested."""
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    return [t.get("id", "") for t in tasks
            if "PREDICTION_TESTED" in t.get("notes", "")
            and t.get("status") == "closed"]


def _find_undocumented_fragile(workspace: Path, tasks: list[dict] | None = None) -> list[str]:
    """Find fragile findings without documented conditions."""
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    fragile = []
    for t in tasks:
        notes = t.get("notes", "")
        if "ROBUST:no" in notes.lower() and "CONDITIONS:" not in notes:
            fragile.append(t.get("id", ""))
    return fragile


def _find_unreplicated_high_impact(workspace: Path, tasks: list[dict] | None = None) -> list[str]:
    """Find high-impact findings that haven't been replicated."""
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    unreplicated = []
    for t in tasks:
        title = t.get("title", "")
        notes = t.get("notes", "")
        if "FINDING" not in title.upper():
            continue
        if t.get("priority", 9) <= 1:
            if "REPLICATED:no" in notes.lower() or "REPLICATED" not in notes:
                unreplicated.append(t.get("id", ""))
    return unreplicated


def _find_design_invalid(workspace: Path, tasks: list[dict] | None = None) -> list[str]:
    """Find open tasks flagged DESIGN_INVALID."""
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []
    return [t.get("id", "") for t in tasks
            if "DESIGN_INVALID" in t.get("notes", "")
            and t.get("status") != "closed"]
