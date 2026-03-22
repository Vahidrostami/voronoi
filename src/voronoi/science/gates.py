"""Dispatch/merge gates, pre-registration, invariants, calibration, replication."""

from __future__ import annotations

import csv as csv_mod
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from voronoi.utils import extract_field
from voronoi.science.fabrication import verify_finding_against_data

logger = logging.getLogger("voronoi.science")


# ===================================================================
# Pre-registration (merged from pre_registration.py)
# ===================================================================

PRE_REG_FIELDS = {
    "HYPOTHESIS", "METHOD", "CONTROLS", "EXPECTED_RESULT",
    "CONFOUNDS", "STAT_TEST", "SAMPLE_SIZE",
}
PRE_REG_SCIENTIFIC_FIELDS = PRE_REG_FIELDS | {"POWER_ANALYSIS", "SENSITIVITY_PLAN"}


@dataclass
class PreRegistration:
    task_id: str
    hypothesis: str = ""
    method: str = ""
    controls: str = ""
    expected_result: str = ""
    confounds: str = ""
    stat_test: str = ""
    sample_size: str = ""
    power_analysis: str = ""
    sensitivity_plan: str = ""
    approved_by: str = ""
    deviations: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return all([self.hypothesis, self.method, self.controls,
                    self.expected_result, self.stat_test, self.sample_size])

    @property
    def is_scientific_complete(self) -> bool:
        return self.is_complete and bool(self.power_analysis) and bool(self.sensitivity_plan)


def parse_pre_registration(notes: str) -> PreRegistration:
    pre_reg = PreRegistration(task_id="")
    for line in notes.split("\n"):
        line = line.strip()
        if not line.startswith("PRE_REG"):
            continue
        for fld in ["HYPOTHESIS", "METHOD", "CONTROLS", "EXPECTED_RESULT",
                     "CONFOUNDS", "STAT_TEST", "SAMPLE_SIZE"]:
            m = re.search(rf"{fld}\s*=\s*\[([^\]]+)\]", line)
            if m:
                setattr(pre_reg, fld.lower(), m.group(1).strip())
        if "POWER" in line:
            m = re.search(r"EFFECT_SIZE=\[([^\]]+)\]", line)
            if m:
                pre_reg.power_analysis = m.group(1).strip()
        if "SENSITIVITY" in line and "PRE_REG_SENSITIVITY" in line:
            pre_reg.sensitivity_plan = line.split("PRE_REG_SENSITIVITY:")[-1].strip()
        if "PRE_REG_DEVIATION" in line:
            pre_reg.deviations.append(line.split("PRE_REG_DEVIATION:")[-1].strip())
    return pre_reg


def validate_pre_registration(task_notes: str, rigor: str) -> tuple[bool, list[str]]:
    pre_reg = parse_pre_registration(task_notes)
    missing = [fld.upper() for fld in ["hypothesis", "method", "controls",
               "expected_result", "stat_test", "sample_size"]
               if not getattr(pre_reg, fld)]
    if rigor in ("scientific", "experimental"):
        if not pre_reg.power_analysis:
            missing.append("POWER_ANALYSIS")
        if not pre_reg.sensitivity_plan:
            missing.append("SENSITIVITY_PLAN")
    return len(missing) == 0, missing


@dataclass
class PreRegComplianceResult:
    compliant: bool
    deviations: list[str] = field(default_factory=list)
    undocumented_deviations: list[str] = field(default_factory=list)
    message: str = ""


def audit_pre_registration_compliance(task_notes: str) -> PreRegComplianceResult:
    pre_reg = parse_pre_registration(task_notes)
    deviations = pre_reg.deviations
    issues: list[str] = []
    actual_valence = extract_field(task_notes, "VALENCE")
    if pre_reg.expected_result and actual_valence:
        expected_positive = any(w in pre_reg.expected_result.lower()
                                for w in ("higher", "better", "increase", "outperform",
                                          "improve", "greater", "more"))
        if expected_positive and actual_valence.lower() in ("negative", "inconclusive") and not deviations:
            issues.append("Result contradicts expected outcome but no PRE_REG_DEVIATION documented")
    planned_n, actual_n = pre_reg.sample_size, extract_field(task_notes, "N")
    if planned_n and actual_n:
        try:
            p = int(re.sub(r'[^\d]', '', planned_n))
            a = int(re.sub(r'[^\d]', '', actual_n))
            if p > 0 and abs(a - p) / p > 0.2:
                if not any("sample" in d.lower() or "N " in d for d in deviations):
                    issues.append(f"Sample size changed from {p} to {a} without PRE_REG_DEVIATION")
        except (ValueError, ZeroDivisionError):
            pass
    return PreRegComplianceResult(
        compliant=len(issues) == 0, deviations=deviations,
        undocumented_deviations=issues,
        message="; ".join(issues) if issues else "Pre-registration compliance OK",
    )


# ===================================================================
# Gate checks
# ===================================================================

def check_dispatch_gates(task: dict, workspace: Path, rigor: str) -> tuple[bool, list[str]]:
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
                    if status not in ("converged", "pass", "passed") and not gate_data.get("converged", False):
                        blockers.append(f"GATE not passing: {gate} (status={status})")
            except (json.JSONDecodeError, OSError):
                blockers.append(f"GATE file unreadable: {gate}")
    task_type = extract_field(notes, "TASK_TYPE")
    if task_type == "investigation" and rigor in ("scientific", "experimental"):
        mr = extract_field(notes, "METHODOLOGIST_REVIEW")
        if not mr:
            blockers.append("Methodologist review required (Scientific+ investigation)")
        elif mr == "REJECTED":
            blockers.append("Methodologist REJECTED this design")
        elif mr == "CONDITIONAL":
            blockers.append("Methodologist review CONDITIONAL — conditions not yet met")
    if task_type == "investigation" and rigor in ("analytical", "scientific", "experimental"):
        valid, missing = validate_pre_registration(notes, rigor)
        if not valid:
            blockers.append(f"Pre-registration incomplete: {', '.join(missing)}")
    return len(blockers) == 0, blockers


def check_merge_gates(task: dict, workspace: Path, rigor: str) -> tuple[bool, list[str]]:
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
        sr = extract_field(notes, "STAT_REVIEW")
        if not sr:
            blockers.append("Finding needs Statistician review")
        elif sr == "REJECTED":
            blockers.append("Statistician REJECTED this finding")
    if "FINDING" in title.upper() and rigor in ("scientific", "experimental"):
        cr = extract_field(notes, "CRITIC_REVIEW")
        if not cr:
            blockers.append("Finding needs Critic review")
        elif cr == "REJECTED":
            blockers.append("Critic REJECTED this finding")
    if "FINDING" in title.upper() and rigor in ("analytical", "scientific", "experimental"):
        fab = verify_finding_against_data(workspace, notes, str(task.get("id", "")))
        for flag in fab.critical_flags:
            blockers.append(f"FABRICATION_CHECK: {flag.message}")
    task_type = extract_field(notes, "TASK_TYPE")
    if task_type == "investigation" and rigor in ("analytical", "scientific", "experimental"):
        eva = extract_field(notes, "EVA")
        if not eva:
            blockers.append("EVA not recorded — run Experimental Validity Audit before merge")
        elif eva.upper().startswith("FAIL"):
            blockers.append("EVA FAILED — experiment design invalid, fix before merge")
    return len(blockers) == 0, blockers


# ===================================================================
# Invariants
# ===================================================================

@dataclass
class Invariant:
    id: str
    description: str
    check_type: str
    params: dict = field(default_factory=dict)


def load_invariants(workspace: Path) -> list[Invariant]:
    path = workspace / ".swarm" / "invariants.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            return []
        return [Invariant(id=i.get("id", ""), description=i.get("description", ""),
                          check_type=i.get("check_type", "custom"), params=i.get("params", {}))
                for i in data if isinstance(i, dict) and i.get("id")]
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load invariants: %s", e)
        return []


def save_invariants(workspace: Path, invariants: list[Invariant]) -> None:
    path = workspace / ".swarm" / "invariants.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(inv) for inv in invariants], indent=2))


def format_invariants_for_prompt(invariants: list[Invariant]) -> str:
    if not invariants:
        return ""
    lines = ["## Investigation Invariants — MANDATORY\n",
             "These constraints apply to ALL agents. Violations are structural failures.\n"]
    lines.extend(f"- **{inv.id}**: {inv.description}" for inv in invariants)
    return "\n".join(lines)


@dataclass
class InvariantCheckResult:
    passed: bool
    violations: list[str] = field(default_factory=list)


def check_invariants(invariants: list[Invariant], context: str) -> InvariantCheckResult:
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
    violations: list[str] = []
    for inv in invariants:
        if inv.check_type != "min_csv_rows":
            continue
        min_rows = int(inv.params.get("min_rows", 0))
        glob_pattern = inv.params.get("glob", "**/*.csv")
        if min_rows <= 0:
            continue
        for csv_file in workspace.glob(glob_pattern):
            try:
                with open(csv_file) as f:
                    reader = csv_mod.reader(f)
                    if next(reader, None) is None:
                        violations.append(f"{inv.id}: {csv_file.relative_to(workspace)} has no rows")
                        continue
                    row_count = sum(1 for _ in reader)
                if row_count < min_rows:
                    violations.append(f"{inv.id}: {csv_file.relative_to(workspace)} has {row_count} data rows, minimum is {min_rows}")
            except (OSError, StopIteration):
                violations.append(f"{inv.id}: {csv_file.relative_to(workspace)} could not be read")
    return InvariantCheckResult(passed=len(violations) == 0, violations=violations)


# ===================================================================
# Calibration & REVISE
# ===================================================================

@dataclass
class CalibrationResult:
    passed: bool
    metric_name: str
    actual_value: float
    target_lo: float
    target_hi: float
    message: str


def check_calibration(task_notes: str) -> list[CalibrationResult]:
    results: list[CalibrationResult] = []
    targets: dict[str, tuple[float, float]] = {}
    actuals: dict[str, float] = {}
    for line in task_notes.split("\n"):
        line = line.strip()
        t = re.search(r"CALIBRATION_TARGET\s*:\s*(\w+)\s*=\s*\[([\d.]+)\s*,\s*([\d.]+)\]", line, re.I)
        if t:
            targets[t.group(1)] = (float(t.group(2)), float(t.group(3)))
        a = re.search(r"CALIBRATION_ACTUAL\s*:\s*(\w+)\s*=\s*([\d.]+)", line, re.I)
        if a:
            actuals[a.group(1)] = float(a.group(2))
    for metric, (lo, hi) in targets.items():
        actual = actuals.get(metric)
        if actual is None:
            results.append(CalibrationResult(False, metric, 0.0, lo, hi, f"{metric}: no actual value reported"))
        elif lo <= actual <= hi:
            results.append(CalibrationResult(True, metric, actual, lo, hi, f"{metric}: {actual:.2f} within [{lo}, {hi}]"))
        else:
            results.append(CalibrationResult(False, metric, actual, lo, hi, f"{metric}: {actual:.2f} outside [{lo}, {hi}]"))
    return results


def parse_revise_context(task_notes: str) -> dict:
    ctx: dict = {}
    for key in ("REVISE_OF", "PRIOR_RESULT", "FAILURE_DIAGNOSIS", "REVISED_PARAMS"):
        val = extract_field(task_notes, key)
        if val:
            ctx[key.lower()] = val
    return ctx


# ===================================================================
# Replication
# ===================================================================

@dataclass
class ReplicationNeed:
    finding_id: str
    title: str
    reason: str


def find_replication_needs(workspace: Path) -> list[ReplicationNeed]:
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
        reasons = []
        ci = extract_field(notes, "CI_95")
        if ci:
            try:
                nums = re.findall(r'[-+]?\d*\.?\d+', ci)
                if len(nums) >= 2:
                    effect = extract_field(notes, "EFFECT_SIZE")
                    if effect:
                        eff_val = abs(float(re.findall(r'[-+]?\d*\.?\d+', effect)[0]))
                        if eff_val > 0 and (float(nums[1]) - float(nums[0])) / eff_val > 0.6:
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
            needs.append(ReplicationNeed(finding_id=task.get("id", ""), title=title, reason=reasons[0]))
    return needs
