"""Dispatch/merge gates, invariants, and calibration checks."""

from __future__ import annotations

import csv as csv_mod
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from voronoi.utils import extract_field

from voronoi.science.pre_registration import validate_pre_registration
from voronoi.science.fabrication import verify_finding_against_data

logger = logging.getLogger("voronoi.science")


# ---------------------------------------------------------------------------
# Gate checks (used by dispatcher)
# ---------------------------------------------------------------------------

def check_dispatch_gates(task: dict, workspace: Path, rigor: str) -> tuple[bool, list[str]]:
    """Check if a task is ready to be dispatched based on artifact contracts and rigor gates."""
    blockers: list[str] = []
    notes = task.get("notes", "")

    requires = extract_field(notes, "REQUIRES")
    if requires:
        for req in requires.split(","):
            req = req.strip()
            if req and not (workspace / req).exists():
                blockers.append(f"REQUIRES missing: {req}")

    gate = extract_field(notes, "GATE")
    if gate:
        gate_path = workspace / gate.strip()
        if not gate_path.exists():
            blockers.append(f"GATE file missing: {gate}")
        else:
            try:
                gate_data = json.loads(gate_path.read_text())
                if isinstance(gate_data, dict):
                    status = gate_data.get("status", "")
                    converged = gate_data.get("converged", False)
                    if status not in ("converged", "pass", "passed") and not converged:
                        blockers.append(f"GATE not passing: {gate} (status={status})")
            except (json.JSONDecodeError, OSError):
                blockers.append(f"GATE file unreadable: {gate}")

    task_type = extract_field(notes, "TASK_TYPE")
    if task_type == "investigation" and rigor in ("scientific", "experimental"):
        methodologist_review = extract_field(notes, "METHODOLOGIST_REVIEW")
        if not methodologist_review:
            blockers.append("Methodologist review required (Scientific+ investigation)")
        elif methodologist_review == "REJECTED":
            blockers.append("Methodologist REJECTED this design")
        elif methodologist_review == "CONDITIONAL":
            blockers.append("Methodologist review CONDITIONAL — conditions not yet met")

    if task_type == "investigation" and rigor in ("analytical", "scientific", "experimental"):
        valid, missing = validate_pre_registration(notes, rigor)
        if not valid:
            blockers.append(f"Pre-registration incomplete: {', '.join(missing)}")

    return len(blockers) == 0, blockers


def check_merge_gates(task: dict, workspace: Path, rigor: str) -> tuple[bool, list[str]]:
    """Check if a task's output is ready to be merged based on quality gates."""
    blockers: list[str] = []
    notes = task.get("notes", "")

    produces = extract_field(notes, "PRODUCES")
    if produces:
        for prod in produces.split(","):
            prod = prod.strip()
            if prod and not (workspace / prod).exists():
                blockers.append(f"PRODUCES missing: {prod}")

    title = task.get("title", "")
    if "FINDING" in title.upper() and rigor in ("analytical", "scientific", "experimental"):
        stat_review = extract_field(notes, "STAT_REVIEW")
        if not stat_review:
            blockers.append("Finding needs Statistician review")
        elif stat_review == "REJECTED":
            blockers.append("Statistician REJECTED this finding")

    if "FINDING" in title.upper() and rigor in ("scientific", "experimental"):
        critic_review = extract_field(notes, "CRITIC_REVIEW")
        if not critic_review:
            blockers.append("Finding needs Critic review")
        elif critic_review == "REJECTED":
            blockers.append("Critic REJECTED this finding")

    if "FINDING" in title.upper() and rigor in ("analytical", "scientific", "experimental"):
        fab_result = verify_finding_against_data(
            workspace, notes, str(task.get("id", ""))
        )
        for flag in fab_result.critical_flags:
            blockers.append(f"FABRICATION_CHECK: {flag.message}")

    task_type = extract_field(notes, "TASK_TYPE")
    if task_type == "investigation" and rigor in ("analytical", "scientific", "experimental"):
        eva_status = extract_field(notes, "EVA")
        if not eva_status:
            blockers.append("EVA not recorded — run Experimental Validity Audit before merge")
        elif eva_status.upper().startswith("FAIL"):
            blockers.append("EVA FAILED — experiment design invalid, fix before merge")

    return len(blockers) == 0, blockers


# ---------------------------------------------------------------------------
# Investigation-Level Invariants
# ---------------------------------------------------------------------------

@dataclass
class Invariant:
    """A cross-cutting constraint that must hold for all agents."""
    id: str
    description: str
    check_type: str  # prompt_contains, output_excludes, metric_equals, custom
    params: dict = field(default_factory=dict)


def load_invariants(workspace: Path) -> list[Invariant]:
    """Load invariants from .swarm/invariants.json."""
    path = workspace / ".swarm" / "invariants.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            return []
        return [
            Invariant(
                id=item.get("id", ""),
                description=item.get("description", ""),
                check_type=item.get("check_type", "custom"),
                params=item.get("params", {}),
            )
            for item in data
            if isinstance(item, dict) and item.get("id")
        ]
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load invariants: %s", e)
        return []


def save_invariants(workspace: Path, invariants: list[Invariant]) -> None:
    """Save invariants to .swarm/invariants.json."""
    path = workspace / ".swarm" / "invariants.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(inv) for inv in invariants], indent=2))


def format_invariants_for_prompt(invariants: list[Invariant]) -> str:
    """Format invariants for injection into agent prompts."""
    if not invariants:
        return ""
    lines = ["## Investigation Invariants — MANDATORY\n"]
    lines.append("These constraints apply to ALL agents. Violations are structural failures.\n")
    for inv in invariants:
        lines.append(f"- **{inv.id}**: {inv.description}")
    return "\n".join(lines)


@dataclass
class InvariantCheckResult:
    """Result of checking invariants against agent output."""
    passed: bool
    violations: list[str] = field(default_factory=list)


def check_invariants(invariants: list[Invariant], context: str) -> InvariantCheckResult:
    """Check invariants against a context string (agent output, prompt, etc.)."""
    violations: list[str] = []
    for inv in invariants:
        if inv.check_type == "prompt_contains":
            required = inv.params.get("text", "")
            if required and required not in context:
                violations.append(f"{inv.id}: required text not found")
        elif inv.check_type == "output_excludes":
            forbidden = inv.params.get("text", "")
            if forbidden and forbidden in context:
                violations.append(f"{inv.id}: forbidden text found")
    return InvariantCheckResult(passed=len(violations) == 0, violations=violations)


def validate_data_invariants(workspace: Path, invariants: list[Invariant]) -> InvariantCheckResult:
    """Check data-file invariants (e.g. min_csv_rows) against actual files."""
    violations: list[str] = []
    for inv in invariants:
        if inv.check_type != "min_csv_rows":
            continue
        min_rows = int(inv.params.get("min_rows", 0))
        glob_pattern = inv.params.get("glob", "**/*.csv")
        if min_rows <= 0:
            continue
        csv_files = list(workspace.glob(glob_pattern))
        for csv_file in csv_files:
            try:
                with open(csv_file) as f:
                    reader = csv_mod.reader(f)
                    header = next(reader, None)
                    if header is None:
                        violations.append(
                            f"{inv.id}: {csv_file.relative_to(workspace)} has no rows (empty file)"
                        )
                        continue
                    row_count = sum(1 for _ in reader)
                if row_count < min_rows:
                    violations.append(
                        f"{inv.id}: {csv_file.relative_to(workspace)} has {row_count} data rows, "
                        f"minimum is {min_rows}"
                    )
            except (OSError, StopIteration):
                violations.append(
                    f"{inv.id}: {csv_file.relative_to(workspace)} could not be read"
                )
    return InvariantCheckResult(passed=len(violations) == 0, violations=violations)


# ---------------------------------------------------------------------------
# REVISE Task & Calibration Check
# ---------------------------------------------------------------------------

@dataclass
class CalibrationResult:
    """Result of checking pilot experiment calibration."""
    passed: bool
    metric_name: str
    actual_value: float
    target_lo: float
    target_hi: float
    message: str


def check_calibration(task_notes: str) -> list[CalibrationResult]:
    """Check whether pilot experiment results meet calibration targets."""
    results: list[CalibrationResult] = []
    targets: dict[str, tuple[float, float]] = {}
    actuals: dict[str, float] = {}

    for line in task_notes.split("\n"):
        line = line.strip()
        t_match = re.search(
            r"CALIBRATION_TARGET\s*:\s*(\w+)\s*=\s*\[([\d.]+)\s*,\s*([\d.]+)\]",
            line, re.I,
        )
        if t_match:
            targets[t_match.group(1)] = (float(t_match.group(2)), float(t_match.group(3)))
        a_match = re.search(
            r"CALIBRATION_ACTUAL\s*:\s*(\w+)\s*=\s*([\d.]+)",
            line, re.I,
        )
        if a_match:
            actuals[a_match.group(1)] = float(a_match.group(2))

    for metric, (lo, hi) in targets.items():
        actual = actuals.get(metric)
        if actual is None:
            results.append(CalibrationResult(
                passed=False, metric_name=metric,
                actual_value=0.0, target_lo=lo, target_hi=hi,
                message=f"{metric}: no actual value reported",
            ))
        elif lo <= actual <= hi:
            results.append(CalibrationResult(
                passed=True, metric_name=metric,
                actual_value=actual, target_lo=lo, target_hi=hi,
                message=f"{metric}: {actual:.2f} within [{lo}, {hi}]",
            ))
        else:
            results.append(CalibrationResult(
                passed=False, metric_name=metric,
                actual_value=actual, target_lo=lo, target_hi=hi,
                message=f"{metric}: {actual:.2f} outside [{lo}, {hi}]",
            ))

    return results


def parse_revise_context(task_notes: str) -> dict:
    """Extract REVISE metadata from Beads notes."""
    ctx: dict = {}
    ctx["revise_of"] = extract_field(task_notes, "REVISE_OF")
    ctx["prior_result"] = extract_field(task_notes, "PRIOR_RESULT")
    ctx["failure_diagnosis"] = extract_field(task_notes, "FAILURE_DIAGNOSIS")
    ctx["revised_params"] = extract_field(task_notes, "REVISED_PARAMS")
    return {k: v for k, v in ctx.items() if v}


# ---------------------------------------------------------------------------
# Replication
# ---------------------------------------------------------------------------

@dataclass
class ReplicationNeed:
    """A finding that needs replication."""
    finding_id: str
    title: str
    reason: str


def find_replication_needs(workspace: Path) -> list[ReplicationNeed]:
    """Identify findings that should be replicated."""
    from voronoi.beads import run_bd as _run_bd
    needs: list[ReplicationNeed] = []
    code, output = _run_bd("list", "--json", cwd=str(workspace))
    if code != 0:
        return needs

    try:
        tasks = json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return needs

    for task in tasks:
        title = task.get("title", "")
        notes = task.get("notes", "")
        if "FINDING" not in title.upper():
            continue
        if "REPLICATED" in notes and "REPLICATED:no" not in notes.lower():
            continue

        tid = task.get("id", "")
        reasons = []

        ci = extract_field(notes, "CI_95")
        if ci:
            try:
                nums = re.findall(r'[-+]?\d*\.?\d+', ci)
                if len(nums) >= 2:
                    lo, hi = float(nums[0]), float(nums[1])
                    effect = extract_field(notes, "EFFECT_SIZE")
                    if effect:
                        eff_nums = re.findall(r'[-+]?\d*\.?\d+', effect)
                        if eff_nums:
                            eff_val = abs(float(eff_nums[0]))
                            if eff_val > 0 and (hi - lo) / eff_val > 0.6:
                                reasons.append("wide_ci")
            except (ValueError, IndexError):
                pass

        quality = extract_field(notes, "QUALITY")
        if quality:
            try:
                if float(quality) < 0.7:
                    reasons.append("low_quality")
            except ValueError:
                pass

        if reasons:
            needs.append(ReplicationNeed(
                finding_id=tid, title=title, reason=reasons[0],
            ))

    return needs


# ---------------------------------------------------------------------------
# Success Criteria helpers
# ---------------------------------------------------------------------------

def load_success_criteria(workspace: Path) -> list[dict]:
    """Load success criteria from .swarm/success-criteria.json."""
    path = workspace / ".swarm" / "success-criteria.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            return []
        return [c for c in data if isinstance(c, dict)]
    except (json.JSONDecodeError, OSError):
        return []


def save_success_criteria(workspace: Path, criteria: list[dict]) -> None:
    """Save success criteria to .swarm/success-criteria.json."""
    path = workspace / ".swarm" / "success-criteria.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(criteria, indent=2))
