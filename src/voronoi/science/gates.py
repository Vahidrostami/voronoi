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
    expected_direction: str = ""   # e.g. "higher_is_better", "L4_A < L4_D"

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
                     "CONFOUNDS", "STAT_TEST", "SAMPLE_SIZE",
                     "EXPECTED_DIRECTION"]:
            m = re.search(rf"{fld}\s*=\s*\[([^\]]+)\]", line)
            if m:
                setattr(pre_reg, fld.lower(), m.group(1).strip())
        if "POWER" in line:
            m = re.search(r"POWER=\[([^\]]+)\]", line)
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
# Plan Review Gate
# ===================================================================

#: Mapping from rigor level to the set of roles that review the plan.
PLAN_REVIEW_REVIEWERS: dict[str, list[str]] = {
    "standard": [],
    "analytical": ["critic"],
    "adaptive": ["critic"],
    "scientific": ["critic", "theorist"],
    "experimental": ["critic", "theorist", "methodologist"],
}


@dataclass
class PlanReviewResult:
    """Result of reading .swarm/plan-review.json."""
    exists: bool
    verdict: str = ""          # APPROVED | REVISE | RESTRUCTURE | ""
    reviewer: str = ""
    issues: dict = field(default_factory=dict)


def check_plan_review_gate(workspace: Path, rigor: str) -> tuple[bool, PlanReviewResult]:
    """Check whether plan review gate is satisfied.

    Returns ``(gate_passed, result)`` where *gate_passed* is ``True`` when:
    - rigor is 'standard' (no review needed), OR
    - ``.swarm/plan-review.json`` exists with verdict ``APPROVED`` or ``REVISE``
      (REVISE means orchestrator will adjust but may proceed).

    A ``RESTRUCTURE`` verdict means the gate is NOT passed — the orchestrator
    must re-decompose before dispatching.
    """
    reviewers = PLAN_REVIEW_REVIEWERS.get(rigor, [])
    if not reviewers:
        return True, PlanReviewResult(exists=False)

    gate_path = workspace / ".swarm" / "plan-review.json"
    if not gate_path.exists():
        return False, PlanReviewResult(exists=False)

    try:
        data = json.loads(gate_path.read_text())
    except (json.JSONDecodeError, OSError):
        return False, PlanReviewResult(exists=True, verdict="ERROR")

    verdict = data.get("verdict", "").upper()
    result = PlanReviewResult(
        exists=True,
        verdict=verdict,
        reviewer=data.get("reviewer", ""),
        issues={
            k: data[k]
            for k in ("coverage", "granularity", "dependencies", "missing",
                       "redundant", "strategic")
            if k in data
        },
    )

    if verdict in ("APPROVED", "REVISE"):
        return True, result
    # RESTRUCTURE or unknown → gate not passed
    return False, result


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
    if task_type == "investigation" and rigor in ("adaptive", "scientific", "experimental"):
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
    if "FINDING" in title.upper() and rigor in ("adaptive", "scientific", "experimental"):
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
    if "FINDING" in title.upper() and rigor in ("adaptive", "scientific", "experimental"):
        fab = verify_finding_against_data(workspace, notes, str(task.get("id", "")))
        for flag in fab.critical_flags:
            blockers.append(f"FABRICATION_CHECK: {flag.message}")
    task_type = extract_field(notes, "TASK_TYPE")
    if task_type == "investigation" and rigor in ("adaptive", "scientific", "experimental"):
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


# ===================================================================
# Experiment Sentinel — contract-based structural validation
# ===================================================================

@dataclass
class ManipulationCheck:
    """A single check that the independent variable was actually varied."""
    check_type: str  # hash_distinct | value_range | file_diff | metric_range
    target: str      # file path relative to workspace
    params: dict = field(default_factory=dict)


@dataclass
class DegeneracyCheck:
    """Detects experiments that run but measure nothing."""
    check_type: str  # not_identical | min_variance | min_distinct_values
    target: str      # file path relative to workspace
    params: dict = field(default_factory=dict)


@dataclass
class PhaseGate:
    """Conditions that must hold before crossing to the next phase."""
    from_phase: str
    to_phase: str
    checks: list[dict] = field(default_factory=list)  # each is a ManipulationCheck or DegeneracyCheck as dict


@dataclass
class ExperimentContract:
    """Machine-readable declaration of what makes an experiment valid.

    Written by orchestrator to ``.swarm/experiment-contract.json``.
    Validated by the dispatcher sentinel at each audit trigger.
    """
    experiment_id: str
    independent_variable: str
    conditions: list[str] = field(default_factory=list)
    manipulation_checks: list[ManipulationCheck] = field(default_factory=list)
    required_outputs: list[dict] = field(default_factory=list)  # [{path, description}]
    degeneracy_checks: list[DegeneracyCheck] = field(default_factory=list)
    phase_gates: list[PhaseGate] = field(default_factory=list)


@dataclass
class SentinelCheckResult:
    """Result of a single sentinel check."""
    check_name: str
    passed: bool
    message: str = ""
    actual_value: str = ""
    expected: str = ""


@dataclass
class SentinelAuditResult:
    """Result of a full sentinel audit."""
    passed: bool
    trigger: str  # what event triggered this audit
    timestamp: str = ""
    checks: list[SentinelCheckResult] = field(default_factory=list)
    critical_failures: list[str] = field(default_factory=list)

    @property
    def failure_summary(self) -> str:
        if not self.critical_failures:
            return ""
        return "; ".join(self.critical_failures)


_CONTRACT_RECOGNIZED_KEYS = frozenset({
    "experiment_id",
    "independent_variable",
    "conditions",
    "manipulation_checks",
    "required_outputs",
    "degeneracy_checks",
    "phase_gates",
})


def load_experiment_contract(workspace: Path) -> ExperimentContract | None:
    """Load experiment contract from ``.swarm/experiment-contract.json``.

    Returns ``None`` if the file is missing, malformed, or has an unknown
    top-level schema (none of the recognized keys present). The unknown-schema
    case is logged as a warning so the dispatcher's sentinel can report it as
    a critical failure rather than silently treating the contract as empty —
    which would otherwise produce a false-positive "pass" audit (see
    SCIENCE.md §10, "Unknown-Schema Handling").
    """
    path = workspace / ".swarm" / "experiment-contract.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load experiment contract: %s", exc)
        return None
    if not isinstance(data, dict):
        logger.warning(
            "Experiment contract at %s is not a JSON object (got %s); ignoring",
            path, type(data).__name__,
        )
        return None
    if not (set(data.keys()) & _CONTRACT_RECOGNIZED_KEYS):
        logger.warning(
            "Experiment contract at %s has unknown schema "
            "(no recognized top-level keys). Keys present: %s. "
            "Expected any of: %s. Treating as invalid contract.",
            path, sorted(data.keys()), sorted(_CONTRACT_RECOGNIZED_KEYS),
        )
        return None
    return ExperimentContract(
        experiment_id=data.get("experiment_id", ""),
        independent_variable=data.get("independent_variable", ""),
        conditions=data.get("conditions", []),
        manipulation_checks=[
            ManipulationCheck(**c) for c in data.get("manipulation_checks", [])
            if isinstance(c, dict) and "check_type" in c
        ],
        required_outputs=data.get("required_outputs", []),
        degeneracy_checks=[
            DegeneracyCheck(**c) for c in data.get("degeneracy_checks", [])
            if isinstance(c, dict) and "check_type" in c
        ],
        phase_gates=[
            PhaseGate(
                from_phase=g.get("from_phase", ""),
                to_phase=g.get("to_phase", ""),
                checks=g.get("checks", []),
            )
            for g in data.get("phase_gates", [])
            if isinstance(g, dict)
        ],
    )


def save_experiment_contract(workspace: Path, contract: ExperimentContract) -> None:
    """Write experiment contract to ``.swarm/experiment-contract.json``."""
    path = workspace / ".swarm" / "experiment-contract.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "experiment_id": contract.experiment_id,
        "independent_variable": contract.independent_variable,
        "conditions": contract.conditions,
        "manipulation_checks": [asdict(c) for c in contract.manipulation_checks],
        "required_outputs": contract.required_outputs,
        "degeneracy_checks": [asdict(c) for c in contract.degeneracy_checks],
        "phase_gates": [
            {"from_phase": g.from_phase, "to_phase": g.to_phase, "checks": g.checks}
            for g in contract.phase_gates
        ],
    }
    path.write_text(json.dumps(data, indent=2))


def validate_experiment_contract(
    workspace: Path,
    contract: ExperimentContract | None = None,
    trigger: str = "periodic",
) -> SentinelAuditResult:
    """Run all sentinel checks declared in the experiment contract.

    Returns a :class:`SentinelAuditResult` with per-check details.  Called
    by the dispatcher at event-driven audit points and on a periodic timer.
    """
    from datetime import datetime, timezone  # noqa: F811 — local to avoid top-level cycle

    now = datetime.now(timezone.utc).isoformat()
    contract_file = workspace / ".swarm" / "experiment-contract.json"
    if contract is None:
        contract = load_experiment_contract(workspace)
    if contract is None:
        # Distinguish "no contract file" (legitimately nothing to validate)
        # from "contract file exists but was rejected" (schema error — must
        # fail loud so the sentinel does not silently pass with zero checks).
        if contract_file.exists():
            failure = SentinelCheckResult(
                check_name="contract_schema",
                passed=False,
                message=(
                    "experiment-contract.json exists but has an unknown or "
                    "invalid schema (see dispatcher log for details). The "
                    "sentinel cannot validate this experiment until the "
                    "contract is rewritten in the documented shape."
                ),
            )
            audit = SentinelAuditResult(
                passed=False, trigger=trigger, timestamp=now,
                checks=[failure],
                critical_failures=[
                    "CONTRACT_SCHEMA: experiment-contract.json unparseable or unknown shape"
                ],
            )
            audit_path = workspace / ".swarm" / "sentinel-audit.json"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                audit_path.write_text(json.dumps(asdict(audit), indent=2))
            except OSError:
                pass
            return audit
        return SentinelAuditResult(passed=True, trigger=trigger, timestamp=now,
                                   checks=[], critical_failures=[])

    results: list[SentinelCheckResult] = []
    critical: list[str] = []

    # --- Manipulation checks ---
    for mc in contract.manipulation_checks:
        res = _run_manipulation_check(workspace, mc, contract.conditions)
        results.append(res)
        if not res.passed:
            critical.append(f"MANIPULATION: {res.message}")

    # --- Degeneracy checks ---
    for dc in contract.degeneracy_checks:
        res = _run_degeneracy_check(workspace, dc, contract.conditions)
        results.append(res)
        if not res.passed:
            critical.append(f"DEGENERACY: {res.message}")

    # --- Required outputs ---
    for ro in contract.required_outputs:
        rel_path = ro.get("path", "")
        if rel_path and not (workspace / rel_path).exists():
            r = SentinelCheckResult(
                check_name=f"output_exists:{rel_path}", passed=False,
                message=f"Required output missing: {rel_path}",
            )
            results.append(r)
            critical.append(f"MISSING_OUTPUT: {rel_path}")
        elif rel_path:
            results.append(SentinelCheckResult(
                check_name=f"output_exists:{rel_path}", passed=True))

    passed = len(critical) == 0
    audit = SentinelAuditResult(
        passed=passed, trigger=trigger, timestamp=now,
        checks=results, critical_failures=critical,
    )

    # Persist audit result
    audit_path = workspace / ".swarm" / "sentinel-audit.json"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        audit_path.write_text(json.dumps(asdict(audit), indent=2))
    except OSError:
        pass

    return audit


def validate_phase_gate(
    workspace: Path,
    contract: ExperimentContract,
    from_phase: str,
    to_phase: str,
) -> SentinelAuditResult:
    """Validate the phase gate checks for a specific phase transition."""
    from datetime import datetime, timezone  # noqa: F811

    now = datetime.now(timezone.utc).isoformat()
    results: list[SentinelCheckResult] = []
    critical: list[str] = []

    gate = None
    for g in contract.phase_gates:
        if g.from_phase == from_phase and g.to_phase == to_phase:
            gate = g
            break

    if gate is None:
        return SentinelAuditResult(passed=True, trigger=f"phase_gate:{from_phase}->{to_phase}",
                                   timestamp=now, checks=[], critical_failures=[])

    for check_dict in gate.checks:
        ct = check_dict.get("check_type", "")
        target = check_dict.get("target", "")
        params = check_dict.get("params", {})
        if ct in ("hash_distinct", "value_range", "metric_range", "file_diff"):
            mc = ManipulationCheck(check_type=ct, target=target, params=params)
            res = _run_manipulation_check(workspace, mc, contract.conditions)
        else:
            dc = DegeneracyCheck(check_type=ct, target=target, params=params)
            res = _run_degeneracy_check(workspace, dc, contract.conditions)
        results.append(res)
        if not res.passed:
            critical.append(f"PHASE_GATE({from_phase}->{to_phase}): {res.message}")

    return SentinelAuditResult(
        passed=len(critical) == 0,
        trigger=f"phase_gate:{from_phase}->{to_phase}",
        timestamp=now, checks=results, critical_failures=critical,
    )


# --- Internal check runners ---

def _resolve_json_field(data: dict | list, field_path: str):
    """Resolve a dot-separated field path like ``per_cell.*.decision_regret``.

    If a path segment is ``*``, collects values across all keys at that level.
    Returns a list of resolved values.
    """
    parts = field_path.split(".")
    current: list = [data]
    for part in parts:
        nxt: list = []
        for node in current:
            if part == "*":
                if isinstance(node, dict):
                    nxt.extend(node.values())
                elif isinstance(node, list):
                    nxt.extend(node)
            else:
                if isinstance(node, dict) and part in node:
                    nxt.append(node[part])
        current = nxt
    return current


def _run_manipulation_check(
    workspace: Path,
    check: ManipulationCheck,
    conditions: list[str],
) -> SentinelCheckResult:
    """Run a single manipulation check."""
    name = f"manipulation:{check.check_type}:{check.target}"
    target_path = workspace / check.target

    if not target_path.exists():
        return SentinelCheckResult(
            check_name=name, passed=True,
            message=f"Target {check.target} not yet produced — skipping (pre-execution)",
        )

    try:
        data = json.loads(target_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return SentinelCheckResult(
            check_name=name, passed=False,
            message=f"Cannot read {check.target}: {exc}",
        )

    if check.check_type == "hash_distinct":
        return _check_hash_distinct(name, data, check.params, conditions)
    elif check.check_type == "value_range":
        return _check_value_range(name, data, check.params)
    elif check.check_type == "metric_range":
        return _check_metric_range(name, data, check.params)
    else:
        return SentinelCheckResult(
            check_name=name, passed=True,
            message=f"Unknown check_type '{check.check_type}' — skipped",
        )


def _check_hash_distinct(
    name: str, data: dict, params: dict, conditions: list[str],
) -> SentinelCheckResult:
    """Verify that a field has distinct values across conditions."""
    field_name = params.get("field", "sha256")
    across = params.get("across", "conditions")

    if across == "conditions" and isinstance(data, dict):
        values = []
        for cond in conditions:
            node = data.get(cond) or data.get("scenarios", {}).get(cond, {})
            if isinstance(node, dict):
                val = node.get(field_name, "")
                if val:
                    values.append(val)
        if len(values) >= 2 and len(set(values)) < 2:
            return SentinelCheckResult(
                check_name=name, passed=False,
                message=f"All conditions have identical {field_name} — manipulation collapsed",
                actual_value=str(values[0])[:80],
            )
        if len(values) >= 2:
            return SentinelCheckResult(
                check_name=name, passed=True,
                message=f"{len(set(values))} distinct {field_name} values across {len(values)} conditions",
            )

    # Fallback: check across top-level keys that look like scenario/condition data
    all_hashes: list[str] = []
    if isinstance(data, dict):
        for key, val in data.items():
            if isinstance(val, dict):
                for cond_key, cond_val in val.items():
                    if isinstance(cond_val, dict) and field_name in cond_val:
                        all_hashes.append(str(cond_val[field_name]))
    if len(all_hashes) >= 2 and len(set(all_hashes)) < 2:
        return SentinelCheckResult(
            check_name=name, passed=False,
            message=f"All {field_name} values identical across data — manipulation collapsed",
        )
    return SentinelCheckResult(check_name=name, passed=True)


def _check_value_range(
    name: str, data: dict | list, params: dict,
) -> SentinelCheckResult:
    """Verify a field's values fall within [min, max]."""
    field_path = params.get("field", "")
    min_val = params.get("min")
    max_val = params.get("max")

    values = _resolve_json_field(data, field_path)
    numeric_vals = []
    for v in values:
        try:
            numeric_vals.append(float(v))
        except (TypeError, ValueError):
            pass

    if not numeric_vals:
        # Distinguish "file doesn't exist yet" (handled by caller) from
        # "file exists but field path resolves to nothing" (likely a contract error).
        raw_values = _resolve_json_field(data, field_path)
        if raw_values:
            # Values exist but aren't numeric — warn
            return SentinelCheckResult(
                check_name=name, passed=True,
                message=f"Values at {field_path} are not numeric — skipping",
            )
        # No values at all — likely field path mismatch or data not yet populated
        return SentinelCheckResult(
            check_name=name, passed=True,
            message=f"No values resolved at {field_path} — field path may be wrong or data not yet produced",
        )

    violations = []
    for v in numeric_vals:
        if min_val is not None and v < float(min_val):
            violations.append(v)
        if max_val is not None and v > float(max_val):
            violations.append(v)

    if violations:
        return SentinelCheckResult(
            check_name=name, passed=False,
            message=(
                f"{len(violations)}/{len(numeric_vals)} values outside "
                f"[{min_val}, {max_val}] at {field_path}"
            ),
            actual_value=f"min={min(numeric_vals):.4f}, max={max(numeric_vals):.4f}",
            expected=f"[{min_val}, {max_val}]",
        )
    return SentinelCheckResult(
        check_name=name, passed=True,
        message=f"All {len(numeric_vals)} values within [{min_val}, {max_val}]",
    )


def _check_metric_range(
    name: str, data: dict | list, params: dict,
) -> SentinelCheckResult:
    """Verify metric values have sufficient variance (not degenerate)."""
    field_path = params.get("field", "")
    min_std = params.get("min_std", 0.001)

    values = _resolve_json_field(data, field_path)
    numeric_vals = []
    for v in values:
        try:
            numeric_vals.append(float(v))
        except (TypeError, ValueError):
            pass

    if len(numeric_vals) < 2:
        # Check if the field path resolved to anything at all
        raw_values = _resolve_json_field(data, field_path)
        if raw_values and len(raw_values) >= 2:
            return SentinelCheckResult(
                check_name=name, passed=True,
                message=f"Values at {field_path} are not numeric — skipping",
            )
        return SentinelCheckResult(
            check_name=name, passed=True,
            message=f"Fewer than 2 numeric values at {field_path} — skipping",
        )

    import statistics
    std = statistics.stdev(numeric_vals)
    if std < float(min_std):
        return SentinelCheckResult(
            check_name=name, passed=False,
            message=f"Metric std={std:.6f} < min_std={min_std} at {field_path} — degenerate",
            actual_value=f"std={std:.6f}",
            expected=f"std >= {min_std}",
        )
    return SentinelCheckResult(
        check_name=name, passed=True,
        message=f"Metric std={std:.4f} at {field_path} (healthy)",
    )


def _run_degeneracy_check(
    workspace: Path,
    check: DegeneracyCheck,
    conditions: list[str],
) -> SentinelCheckResult:
    """Run a single degeneracy check."""
    name = f"degeneracy:{check.check_type}:{check.target}"
    target_path = workspace / check.target

    if not target_path.exists():
        return SentinelCheckResult(
            check_name=name, passed=True,
            message=f"Target {check.target} not yet produced — skipping",
        )

    try:
        data = json.loads(target_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        return SentinelCheckResult(
            check_name=name, passed=False,
            message=f"Cannot read {check.target}: {exc}",
        )

    if check.check_type == "not_identical":
        return _check_not_identical(name, data, check.params, conditions)
    elif check.check_type == "min_variance":
        return _check_metric_range(name, data, check.params)
    elif check.check_type == "min_distinct_values":
        return _check_min_distinct(name, data, check.params)
    else:
        return SentinelCheckResult(
            check_name=name, passed=True,
            message=f"Unknown check_type '{check.check_type}' — skipped",
        )


def _check_not_identical(
    name: str, data: dict | list, params: dict, conditions: list[str],
) -> SentinelCheckResult:
    """Verify that values differ across conditions (not all identical)."""
    field_path = params.get("field", "")
    across = params.get("across", "conditions")

    values = _resolve_json_field(data, field_path)
    str_values = [str(v) for v in values if v is not None]

    if len(str_values) < 2:
        return SentinelCheckResult(
            check_name=name, passed=True,
            message=f"Fewer than 2 values at {field_path} — skipping",
        )

    if len(set(str_values)) == 1:
        return SentinelCheckResult(
            check_name=name, passed=False,
            message=f"All {len(str_values)} values identical at {field_path} — experiment degenerate",
            actual_value=str_values[0][:80],
        )
    return SentinelCheckResult(
        check_name=name, passed=True,
        message=f"{len(set(str_values))} distinct values across {len(str_values)} observations",
    )


def _check_min_distinct(
    name: str, data: dict | list, params: dict,
) -> SentinelCheckResult:
    """Verify at least N distinct values exist."""
    field_path = params.get("field", "")
    min_count = params.get("min", 2)

    values = _resolve_json_field(data, field_path)
    str_values = [str(v) for v in values if v is not None]
    distinct = len(set(str_values))

    if distinct < int(min_count):
        return SentinelCheckResult(
            check_name=name, passed=False,
            message=f"Only {distinct} distinct values at {field_path}, need >= {min_count}",
        )
    return SentinelCheckResult(
        check_name=name, passed=True,
        message=f"{distinct} distinct values at {field_path}",
    )
