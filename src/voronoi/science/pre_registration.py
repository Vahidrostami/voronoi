"""Pre-registration validation and parsing."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from voronoi.utils import extract_field

PRE_REG_FIELDS = {
    "HYPOTHESIS", "METHOD", "CONTROLS", "EXPECTED_RESULT",
    "CONFOUNDS", "STAT_TEST", "SAMPLE_SIZE",
}

PRE_REG_SCIENTIFIC_FIELDS = PRE_REG_FIELDS | {
    "POWER_ANALYSIS", "SENSITIVITY_PLAN",
}


@dataclass
class PreRegistration:
    """A pre-registered experimental design."""
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
    approved_by: str = ""  # methodologist task ID
    deviations: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return all([self.hypothesis, self.method, self.controls,
                    self.expected_result, self.stat_test, self.sample_size])

    @property
    def is_scientific_complete(self) -> bool:
        return self.is_complete and bool(self.power_analysis) and bool(self.sensitivity_plan)


def parse_pre_registration(notes: str) -> PreRegistration:
    """Extract pre-registration fields from Beads notes."""
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
    """Check if a task's pre-registration is complete for its rigor level.

    Returns (is_valid, list_of_missing_fields).
    """
    pre_reg = parse_pre_registration(task_notes)
    missing = []

    for fld in ["hypothesis", "method", "controls", "expected_result",
                "stat_test", "sample_size"]:
        if not getattr(pre_reg, fld):
            missing.append(fld.upper())

    if rigor in ("scientific", "experimental"):
        if not pre_reg.power_analysis:
            missing.append("POWER_ANALYSIS")
        if not pre_reg.sensitivity_plan:
            missing.append("SENSITIVITY_PLAN")

    return len(missing) == 0, missing


@dataclass
class PreRegComplianceResult:
    """Result of checking whether execution matched pre-registered design."""
    compliant: bool
    deviations: list[str] = field(default_factory=list)
    undocumented_deviations: list[str] = field(default_factory=list)
    message: str = ""


def audit_pre_registration_compliance(task_notes: str) -> PreRegComplianceResult:
    """Check whether a completed investigation documented all deviations."""
    pre_reg = parse_pre_registration(task_notes)
    deviations = pre_reg.deviations
    issues: list[str] = []

    actual_valence = extract_field(task_notes, "VALENCE")
    if pre_reg.expected_result and actual_valence:
        expected_positive = any(w in pre_reg.expected_result.lower()
                                for w in ("higher", "better", "increase", "outperform",
                                          "improve", "greater", "more"))
        actual_negative = actual_valence.lower() in ("negative", "inconclusive")
        if expected_positive and actual_negative and not deviations:
            issues.append(
                "Result contradicts expected outcome but no PRE_REG_DEVIATION documented"
            )

    planned_n = pre_reg.sample_size
    actual_n = extract_field(task_notes, "N")
    if planned_n and actual_n:
        try:
            planned = int(re.sub(r'[^\d]', '', planned_n))
            actual = int(re.sub(r'[^\d]', '', actual_n))
            if planned > 0 and abs(actual - planned) / planned > 0.2:
                deviation_noted = any("sample" in d.lower() or "N " in d
                                      for d in deviations)
                if not deviation_noted:
                    issues.append(
                        f"Sample size changed from {planned} to {actual} "
                        f"without PRE_REG_DEVIATION"
                    )
        except (ValueError, ZeroDivisionError):
            pass

    return PreRegComplianceResult(
        compliant=len(issues) == 0,
        deviations=deviations,
        undocumented_deviations=issues,
        message="; ".join(issues) if issues else "Pre-registration compliance OK",
    )
