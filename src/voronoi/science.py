"""Science gate enforcement — the backbone of Voronoi's rigor system.

This module implements programmatic enforcement of scientific rigor gates
that were previously only described in agent prompts. It provides:

- Pre-registration validation
- Belief map management (create, update, query)
- Convergence detection with rigor-appropriate criteria
- Information-gain hypothesis prioritization
- Paradigm stress detection
- Consistency gate (pairwise contradiction checking)
- Lab notebook tracking (iteration history)
- Replication coordination

All functions operate on the filesystem (.swarm/) and Beads (via subprocess),
keeping the system stateless and debuggable.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from voronoi.beads import run_bd as _run_bd

logger = logging.getLogger("voronoi.science")


# ---------------------------------------------------------------------------
# Pre-registration
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Belief Map
# ---------------------------------------------------------------------------

@dataclass
class Hypothesis:
    """A single hypothesis in the belief map."""
    id: str
    name: str
    prior: float
    posterior: float
    status: str = "untested"  # untested, testing, confirmed, refuted, inconclusive
    evidence: list[str] = field(default_factory=list)
    testability: float = 0.5
    impact: float = 0.5

    @property
    def uncertainty(self) -> float:
        """Uncertainty is highest at P=0.5, zero at P=0 or P=1."""
        return 1.0 - abs(self.posterior - 0.5) * 2

    @property
    def information_gain(self) -> float:
        """Priority score: uncertainty × impact × testability."""
        return self.uncertainty * self.impact * self.testability


@dataclass
class BeliefMap:
    """Tracks hypothesis probabilities across an investigation."""
    hypotheses: list[Hypothesis] = field(default_factory=list)
    cycle: int = 0
    last_updated: str = ""

    def add_hypothesis(self, h: Hypothesis) -> None:
        self.hypotheses.append(h)

    def update_hypothesis(self, h_id: str, posterior: float,
                          status: str, evidence_id: str = "") -> bool:
        """Update a hypothesis with new evidence. Returns True if found."""
        for h in self.hypotheses:
            if h.id == h_id:
                h.posterior = max(0.0, min(1.0, posterior))
                h.status = status
                if evidence_id:
                    h.evidence.append(evidence_id)
                return True
        return False

    def get_priority_order(self) -> list[Hypothesis]:
        """Return hypotheses sorted by information gain (highest first)."""
        untested = [h for h in self.hypotheses if h.status in ("untested", "testing")]
        return sorted(untested, key=lambda h: h.information_gain, reverse=True)

    def all_resolved(self) -> bool:
        """True if every hypothesis has been resolved (not untested/testing)."""
        return all(h.status not in ("untested", "testing") for h in self.hypotheses)

    def summary(self) -> dict:
        """Compact summary for logging."""
        by_status: dict[str, int] = {}
        for h in self.hypotheses:
            by_status[h.status] = by_status.get(h.status, 0) + 1
        return {
            "total": len(self.hypotheses),
            "by_status": by_status,
            "cycle": self.cycle,
        }


def load_belief_map(workspace: Path) -> BeliefMap:
    """Load belief map from .swarm/belief-map.json."""
    path = workspace / ".swarm" / "belief-map.json"
    if not path.exists():
        return BeliefMap()
    try:
        data = json.loads(path.read_text())
        bm = BeliefMap(
            cycle=data.get("cycle", 0),
            last_updated=data.get("last_updated", ""),
        )
        for h_data in data.get("hypotheses", []):
            bm.hypotheses.append(Hypothesis(
                id=h_data.get("id", ""),
                name=h_data.get("name", ""),
                prior=h_data.get("prior", 0.5),
                posterior=h_data.get("posterior", h_data.get("prior", 0.5)),
                status=h_data.get("status", "untested"),
                evidence=h_data.get("evidence", []),
                testability=h_data.get("testability", 0.5),
                impact=h_data.get("impact", 0.5),
            ))
        return bm
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load belief map: %s", e)
        return BeliefMap()


def save_belief_map(workspace: Path, bm: BeliefMap) -> None:
    """Save belief map to .swarm/belief-map.json."""
    path = workspace / ".swarm" / "belief-map.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    bm.last_updated = datetime.now(timezone.utc).isoformat()
    data = {
        "cycle": bm.cycle,
        "last_updated": bm.last_updated,
        "hypotheses": [asdict(h) for h in bm.hypotheses],
    }
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Convergence Detection
# ---------------------------------------------------------------------------

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
    """Check if an investigation meets convergence criteria for its rigor level.

    Args:
        workspace: Path to the investigation workspace.
        rigor: One of standard, analytical, scientific, experimental.
        eval_score: Evaluator score (0.0-1.0) if available.
        improvement_rounds: Number of improvement rounds completed.
    """
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

    # Fetch tasks once for all convergence checks
    tasks = _fetch_tasks(workspace)

    # Block on DESIGN_INVALID tasks (broken experiments must be fixed)
    design_invalid = _find_design_invalid(workspace, tasks)
    if design_invalid:
        blockers.append(f"{len(design_invalid)} DESIGN_INVALID experiment(s) — fix before converging")

    # Check success criteria if defined
    criteria_blockers = _check_success_criteria(workspace)
    blockers.extend(criteria_blockers)

    # Check hypothesis-result alignment
    alignment_blockers = _check_hypothesis_alignment(workspace)
    blockers.extend(alignment_blockers)

    # Check for consistency conflicts
    conflicts = _find_consistency_conflicts(workspace, tasks)
    if conflicts:
        blockers.append(f"{len(conflicts)} unresolved consistency conflicts")

    # Check for contested findings
    contested = _find_contested_findings(workspace, tasks)
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

        # At least one competing theory ruled out
        theories = _find_theories(workspace, tasks)
        if not any(t.get("status") == "refuted" for t in theories):
            blockers.append("No competing theory ruled out yet")

        # Novel prediction tested
        predictions = _find_tested_predictions(workspace, tasks)
        if not predictions:
            blockers.append("No novel prediction tested")

        # All findings must be ROBUST or FRAGILE-documented
        fragile_undoc = _find_undocumented_fragile(workspace, tasks)
        if fragile_undoc:
            blockers.append(f"{len(fragile_undoc)} fragile findings without conditions documented")

    # --- Experimental: replication required ---
    if rigor == "experimental":
        unreplicated = _find_unreplicated_high_impact(workspace, tasks)
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


# ---------------------------------------------------------------------------
# Paradigm Stress Detection
# ---------------------------------------------------------------------------

@dataclass
class ParadigmStressResult:
    """Result of paradigm stress check."""
    stressed: bool
    contradiction_count: int
    contradicting_findings: list[str]
    message: str


def check_paradigm_stress(workspace: Path) -> ParadigmStressResult:
    """Detect if 3+ findings contradict the working model."""
    contradictions = _find_consistency_conflicts(workspace)
    count = len(contradictions)
    finding_ids = [c.get("finding_a", "") for c in contradictions] + \
                  [c.get("finding_b", "") for c in contradictions]
    finding_ids = list(set(f for f in finding_ids if f))

    if count >= 3:
        return ParadigmStressResult(
            stressed=True,
            contradiction_count=count,
            contradicting_findings=finding_ids,
            message=f"PARADIGM STRESS: {count} contradictions detected. "
                    f"Working model may need fundamental revision.",
        )
    return ParadigmStressResult(
        stressed=False,
        contradiction_count=count,
        contradicting_findings=finding_ids,
        message=f"{count} contradiction(s) — within normal range",
    )


# ---------------------------------------------------------------------------
# Consistency Gate
# ---------------------------------------------------------------------------

@dataclass
class ConsistencyConflict:
    """A contradiction between two findings."""
    finding_a: str
    finding_b: str
    conflict_type: str  # direction, magnitude, conclusion
    description: str


def check_consistency(findings: list[dict]) -> list[ConsistencyConflict]:
    """Pairwise consistency check across validated findings.

    Finds contradictions in valence direction or overlapping claims.
    """
    conflicts: list[ConsistencyConflict] = []
    validated = [f for f in findings
                 if "STAT_REVIEW: APPROVED" in f.get("notes", "")]

    for i, a in enumerate(validated):
        for b in validated[i + 1:]:
            conflict = _check_pair_consistency(a, b)
            if conflict:
                conflicts.append(conflict)

    return conflicts


def _check_pair_consistency(a: dict, b: dict) -> Optional[ConsistencyConflict]:
    """Check if two findings contradict each other."""
    notes_a = a.get("notes", "")
    notes_b = b.get("notes", "")

    valence_a = _extract_field(notes_a, "VALENCE")
    valence_b = _extract_field(notes_b, "VALENCE")

    title_a = a.get("title", "").lower()
    title_b = b.get("title", "").lower()

    # Check if they address the same topic (simple keyword overlap)
    words_a = set(re.findall(r'\b\w{4,}\b', title_a))
    words_b = set(re.findall(r'\b\w{4,}\b', title_b))
    overlap = words_a & words_b

    if len(overlap) < 2:
        return None  # Different topics — no conflict expected

    # Opposing valence on overlapping topic
    if valence_a and valence_b and valence_a != valence_b:
        if {valence_a, valence_b} == {"positive", "negative"}:
            return ConsistencyConflict(
                finding_a=a.get("id", ""),
                finding_b=b.get("id", ""),
                conflict_type="direction",
                description=f"Opposing valence on related topic: "
                            f"{a.get('title', '')} ({valence_a}) vs "
                            f"{b.get('title', '')} ({valence_b})",
            )

    return None


# ---------------------------------------------------------------------------
# Lab Notebook
# ---------------------------------------------------------------------------

@dataclass
class LabNotebookEntry:
    """A single entry in the lab notebook."""
    cycle: int
    phase: str
    verdict: str  # pass, fail, iterate, blocked
    metrics: dict = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    timestamp: str = ""


def load_lab_notebook(workspace: Path) -> list[LabNotebookEntry]:
    """Load the lab notebook from .swarm/lab-notebook.json."""
    path = workspace / ".swarm" / "lab-notebook.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        entries = []
        for e in data.get("entries", []):
            entries.append(LabNotebookEntry(
                cycle=e.get("cycle", 0),
                phase=e.get("phase", ""),
                verdict=e.get("verdict", ""),
                metrics=e.get("metrics", {}),
                failures=e.get("failures", []),
                next_steps=e.get("next_steps", []),
                timestamp=e.get("timestamp", ""),
            ))
        return entries
    except (json.JSONDecodeError, OSError):
        return []


def append_lab_notebook(workspace: Path, entry: LabNotebookEntry) -> None:
    """Append an entry to the lab notebook."""
    entries = load_lab_notebook(workspace)
    entry.timestamp = datetime.now(timezone.utc).isoformat()
    entries.append(entry)
    path = workspace / ".swarm" / "lab-notebook.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"entries": [asdict(e) for e in entries]}
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Data Integrity
# ---------------------------------------------------------------------------

def verify_data_hash(filepath: Path, expected_hash: str) -> bool:
    """Verify SHA-256 hash of a data file."""
    if not filepath.exists():
        return False
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    actual = f"sha256:{sha256.hexdigest()}"
    return actual == expected_hash


def compute_data_hash(filepath: Path) -> str:
    """Compute SHA-256 hash of a data file and return sha256:<hex> string."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return f"sha256:{sha256.hexdigest()}"


# ---------------------------------------------------------------------------
# Anti-Fabrication Verification
# ---------------------------------------------------------------------------

@dataclass
class FabricationFlag:
    """A single red flag raised by anti-fabrication audit."""
    severity: str  # "critical", "warning", "info"
    category: str  # e.g. "data_missing", "numbers_mismatch", "too_clean"
    message: str
    finding_id: str = ""


@dataclass
class AntiFabricationResult:
    """Result of anti-fabrication verification for a finding."""
    finding_id: str
    passed: bool
    flags: list[FabricationFlag] = field(default_factory=list)
    data_file_exists: bool = False
    hash_verified: bool = False
    experiment_script_exists: bool = False
    numbers_verified: bool = False

    @property
    def critical_flags(self) -> list[FabricationFlag]:
        return [f for f in self.flags if f.severity == "critical"]


def _parse_csv_numbers(filepath: Path) -> list[list[float]]:
    """Parse numeric columns from a CSV data file.

    Returns list of columns, where each column is a list of floats.
    Non-numeric values are skipped.
    """
    import csv

    columns: dict[int, list[float]] = {}
    try:
        with open(filepath, newline="") as f:
            reader = csv.reader(f)
            header = next(reader, None)
            if header is None:
                return []
            for row in reader:
                for i, val in enumerate(row):
                    try:
                        columns.setdefault(i, []).append(float(val))
                    except (ValueError, TypeError):
                        pass
    except (OSError, csv.Error):
        return []

    return [col for col in columns.values() if len(col) >= 2]


def _extract_reported_numbers(notes: str) -> dict:
    """Extract reported statistics from finding notes.

    Returns a dict with keys like 'effect_size', 'ci_lo', 'ci_hi', 'n', 'p'.
    """
    result: dict = {}

    effect = _extract_field(notes, "EFFECT_SIZE")
    if effect:
        try:
            result["effect_size"] = float(re.sub(r"[^\d.\-]", "", effect))
        except ValueError:
            pass

    ci = _extract_field(notes, "CI_95")
    if ci:
        ci_match = re.findall(r"[\-]?\d+\.?\d*", ci)
        if len(ci_match) >= 2:
            try:
                result["ci_lo"] = float(ci_match[0])
                result["ci_hi"] = float(ci_match[1])
            except ValueError:
                pass

    n = _extract_field(notes, "N")
    if n:
        try:
            result["n"] = int(re.sub(r"[^\d]", "", n))
        except ValueError:
            pass

    p = _extract_field(notes, "P")
    if p:
        try:
            result["p"] = float(re.sub(r"[^\d.\-]", "", p))
        except ValueError:
            pass

    return result


def _verify_sample_size_against_data(
    data_columns: list[list[float]],
    reported_n: int,
) -> tuple[bool, str]:
    """Check if any column's row count is consistent with reported N."""
    if not data_columns:
        return False, "No numeric data columns found in file"
    actual_sizes = [len(col) for col in data_columns]
    # Reported N could be per-group or total; accept if any column matches
    # or if sum of two equal columns matches
    if reported_n in actual_sizes:
        return True, ""
    # Check if N is total across two equal groups
    for size in actual_sizes:
        if size * 2 == reported_n or size == reported_n:
            return True, ""
    # Check if total rows match
    max_rows = max(actual_sizes) if actual_sizes else 0
    if max_rows == reported_n:
        return True, ""
    return False, (
        f"Reported N={reported_n} but data file has column sizes "
        f"{sorted(set(actual_sizes))}. No column matches reported N."
    )


def _check_suspiciously_clean(data_columns: list[list[float]]) -> list[str]:
    """Detect suspiciously clean data patterns that suggest fabrication.

    Checks for: identical decimal precision, impossibly round numbers,
    zero variance, and p-values clustered just below 0.05.
    """
    warnings: list[str] = []

    for i, col in enumerate(data_columns):
        if len(col) < 3:
            continue

        # Check for zero variance (all identical values)
        if len(set(col)) == 1:
            warnings.append(
                f"Column {i}: all {len(col)} values are identical ({col[0]})"
            )

        # Check for suspiciously uniform decimal precision
        decimals = []
        for v in col:
            s = f"{v:.15g}"
            if "." in s:
                decimals.append(len(s.split(".")[1].rstrip("0")) or 0)
            else:
                decimals.append(0)
        if len(set(decimals)) == 1 and decimals[0] > 0 and len(col) > 5:
            warnings.append(
                f"Column {i}: all {len(col)} values have exactly "
                f"{decimals[0]} decimal places (suspiciously uniform precision)"
            )

        # Check for impossibly round numbers (all integers or all .5)
        all_round = all(v == int(v) or v * 2 == int(v * 2) for v in col)
        if all_round and len(col) > 10:
            warnings.append(
                f"Column {i}: all {len(col)} values are round numbers "
                f"(integers or .5 increments)"
            )

    return warnings


def verify_finding_against_data(
    workspace: Path,
    finding_notes: str,
    finding_id: str = "",
) -> AntiFabricationResult:
    """Cross-verify a finding's reported numbers against its raw data file.

    This is the core anti-fabrication check. It:
    1. Verifies the data file exists and its hash matches
    2. Checks that reported N matches actual data row count
    3. Flags suspiciously clean data patterns
    4. Checks for experiment script existence
    """
    result = AntiFabricationResult(finding_id=finding_id, passed=True)

    # 1. Check data file exists
    data_file_str = _extract_field(finding_notes, "DATA_FILE")
    if not data_file_str:
        result.flags.append(FabricationFlag(
            severity="critical",
            category="data_missing",
            message="No DATA_FILE referenced in finding — cannot verify",
            finding_id=finding_id,
        ))
        result.passed = False
        return result

    data_path = workspace / data_file_str.strip()
    result.data_file_exists = data_path.exists()
    if not result.data_file_exists:
        result.flags.append(FabricationFlag(
            severity="critical",
            category="data_missing",
            message=f"DATA_FILE '{data_file_str}' does not exist on disk",
            finding_id=finding_id,
        ))
        result.passed = False
        return result

    # 2. Verify hash
    expected_hash = _extract_field(finding_notes, "DATA_HASH")
    if expected_hash:
        result.hash_verified = verify_data_hash(data_path, expected_hash.strip())
        if not result.hash_verified:
            actual_hash = compute_data_hash(data_path)
            result.flags.append(FabricationFlag(
                severity="critical",
                category="hash_mismatch",
                message=(
                    f"DATA_HASH mismatch: expected {expected_hash}, "
                    f"actual {actual_hash}. Data may have been modified."
                ),
                finding_id=finding_id,
            ))
            result.passed = False
    else:
        result.flags.append(FabricationFlag(
            severity="warning",
            category="hash_missing",
            message="No DATA_HASH in finding — cannot verify data integrity",
            finding_id=finding_id,
        ))

    # 3. Parse data and cross-check reported numbers
    reported = _extract_reported_numbers(finding_notes)
    if data_path.suffix.lower() == ".csv":
        columns = _parse_csv_numbers(data_path)

        # Verify sample size
        if "n" in reported and columns:
            ok, msg = _verify_sample_size_against_data(columns, reported["n"])
            if ok:
                result.numbers_verified = True
            else:
                result.flags.append(FabricationFlag(
                    severity="critical",
                    category="n_mismatch",
                    message=msg,
                    finding_id=finding_id,
                ))
                result.passed = False

        # Check for suspicious patterns
        if columns:
            clean_warnings = _check_suspiciously_clean(columns)
            for w in clean_warnings:
                result.flags.append(FabricationFlag(
                    severity="warning",
                    category="too_clean",
                    message=w,
                    finding_id=finding_id,
                ))
    elif data_path.suffix.lower() == ".json":
        # For JSON data, at least verify it's valid and non-empty
        try:
            data = json.loads(data_path.read_text())
            if not data:
                result.flags.append(FabricationFlag(
                    severity="warning",
                    category="empty_data",
                    message="DATA_FILE is valid JSON but empty",
                    finding_id=finding_id,
                ))
        except (json.JSONDecodeError, OSError) as e:
            result.flags.append(FabricationFlag(
                severity="critical",
                category="corrupt_data",
                message=f"DATA_FILE is not valid JSON: {e}",
                finding_id=finding_id,
            ))
            result.passed = False

    # 4. Check experiment script exists
    experiment_dir = workspace / "experiments"
    if experiment_dir.exists():
        scripts = list(experiment_dir.glob("*.py")) + list(experiment_dir.glob("*.sh"))
        result.experiment_script_exists = len(scripts) > 0
    if not result.experiment_script_exists:
        result.flags.append(FabricationFlag(
            severity="warning",
            category="no_experiment_script",
            message=(
                "No experiment script found in experiments/. "
                "Results cannot be independently reproduced."
            ),
            finding_id=finding_id,
        ))

    # 5. Check for p-value clustering just below 0.05
    if "p" in reported:
        p = reported["p"]
        if 0.01 < p < 0.05:
            result.flags.append(FabricationFlag(
                severity="info",
                category="p_cluster",
                message=(
                    f"p-value ({p}) is in the suspicious 0.01–0.05 cluster. "
                    f"Not necessarily fabricated, but merits scrutiny."
                ),
                finding_id=finding_id,
            ))

    # 6. Effect size sanity check
    if "effect_size" in reported:
        d = abs(reported["effect_size"])
        if d > 3.0:
            result.flags.append(FabricationFlag(
                severity="warning",
                category="implausible_effect",
                message=(
                    f"Reported effect size d={reported['effect_size']} is "
                    f"implausibly large (>3.0). Verify this is correct."
                ),
                finding_id=finding_id,
            ))

    return result


def audit_all_findings(
    workspace: Path,
    tasks: list[dict] | None = None,
) -> list[AntiFabricationResult]:
    """Run anti-fabrication verification on ALL findings in the workspace."""
    if tasks is None:
        tasks = _fetch_tasks(workspace)
    if not tasks:
        return []

    results = []
    for task in tasks:
        title = task.get("title", "")
        if "FINDING" not in title.upper():
            continue
        notes = task.get("notes", "")
        finding_id = str(task.get("id", ""))
        result = verify_finding_against_data(workspace, notes, finding_id)
        results.append(result)

    return results


def format_fabrication_report(results: list[AntiFabricationResult]) -> str:
    """Format anti-fabrication audit results into a human-readable report."""
    if not results:
        return "No findings to audit."

    lines = ["# Anti-Fabrication Audit Report", ""]
    total = len(results)
    passed = sum(1 for r in results if r.passed)
    critical_count = sum(len(r.critical_flags) for r in results)

    lines.append(f"**{passed}/{total}** findings passed verification")
    if critical_count:
        lines.append(f"**{critical_count} CRITICAL flags** — these block convergence")
    lines.append("")

    for r in results:
        status = "PASS" if r.passed else "FAIL"
        icon = "✅" if r.passed else "❌"
        lines.append(f"## {icon} Finding {r.finding_id} — {status}")
        lines.append(f"- Data file exists: {'yes' if r.data_file_exists else 'NO'}")
        lines.append(f"- Hash verified: {'yes' if r.hash_verified else 'no'}")
        lines.append(f"- Experiment script: {'yes' if r.experiment_script_exists else 'no'}")
        lines.append(f"- Numbers verified: {'yes' if r.numbers_verified else 'no'}")
        if r.flags:
            lines.append("- Flags:")
            for f in r.flags:
                sev = {"critical": "🚨", "warning": "⚠️", "info": "ℹ️"}.get(f.severity, "?")
                lines.append(f"  - {sev} [{f.category}] {f.message}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Gate checks (used by dispatcher)
# ---------------------------------------------------------------------------

def check_dispatch_gates(task: dict, workspace: Path, rigor: str) -> tuple[bool, list[str]]:
    """Check if a task is ready to be dispatched based on artifact contracts and rigor gates.

    Returns (can_dispatch, list_of_blockers).
    """
    blockers: list[str] = []
    notes = task.get("notes", "")

    # Check REQUIRES artifacts
    requires = _extract_field(notes, "REQUIRES")
    if requires:
        for req in requires.split(","):
            req = req.strip()
            if req and not (workspace / req).exists():
                blockers.append(f"REQUIRES missing: {req}")

    # Check GATE artifacts
    gate = _extract_field(notes, "GATE")
    if gate:
        gate_path = workspace / gate.strip()
        if not gate_path.exists():
            blockers.append(f"GATE file missing: {gate}")
        else:
            try:
                gate_data = json.loads(gate_path.read_text())
                # Check for passing verdicts
                if isinstance(gate_data, dict):
                    status = gate_data.get("status", "")
                    converged = gate_data.get("converged", False)
                    if status not in ("converged", "pass", "passed") and not converged:
                        blockers.append(f"GATE not passing: {gate} (status={status})")
            except (json.JSONDecodeError, OSError):
                blockers.append(f"GATE file unreadable: {gate}")

    # Scientific+ investigation tasks need Methodologist approval
    task_type = _extract_field(notes, "TASK_TYPE")
    if task_type == "investigation" and rigor in ("scientific", "experimental"):
        methodologist_review = _extract_field(notes, "METHODOLOGIST_REVIEW")
        if not methodologist_review:
            blockers.append("Methodologist review required (Scientific+ investigation)")
        elif methodologist_review == "REJECTED":
            blockers.append("Methodologist REJECTED this design")
        elif methodologist_review == "CONDITIONAL":
            blockers.append("Methodologist review CONDITIONAL — conditions not yet met")

    # Pre-registration check for investigation tasks at Analytical+
    if task_type == "investigation" and rigor in ("analytical", "scientific", "experimental"):
        valid, missing = validate_pre_registration(notes, rigor)
        if not valid:
            blockers.append(f"Pre-registration incomplete: {', '.join(missing)}")

    return len(blockers) == 0, blockers


def check_merge_gates(task: dict, workspace: Path, rigor: str) -> tuple[bool, list[str]]:
    """Check if a task's output is ready to be merged based on quality gates.

    Returns (can_merge, list_of_blockers).
    """
    blockers: list[str] = []
    notes = task.get("notes", "")

    # Check PRODUCES artifacts
    produces = _extract_field(notes, "PRODUCES")
    if produces:
        for prod in produces.split(","):
            prod = prod.strip()
            if prod and not (workspace / prod).exists():
                blockers.append(f"PRODUCES missing: {prod}")

    # Findings need statistical review at Analytical+
    title = task.get("title", "")
    if "FINDING" in title.upper() and rigor in ("analytical", "scientific", "experimental"):
        stat_review = _extract_field(notes, "STAT_REVIEW")
        if not stat_review:
            blockers.append("Finding needs Statistician review")
        elif stat_review == "REJECTED":
            blockers.append("Statistician REJECTED this finding")

    # Findings need Critic review at Scientific+
    if "FINDING" in title.upper() and rigor in ("scientific", "experimental"):
        critic_review = _extract_field(notes, "CRITIC_REVIEW")
        if not critic_review:
            blockers.append("Finding needs Critic review")
        elif critic_review == "REJECTED":
            blockers.append("Critic REJECTED this finding")

    # Anti-fabrication verification for findings at Analytical+
    if "FINDING" in title.upper() and rigor in ("analytical", "scientific", "experimental"):
        fab_result = verify_finding_against_data(
            workspace, notes, str(task.get("id", ""))
        )
        for flag in fab_result.critical_flags:
            blockers.append(f"FABRICATION_CHECK: {flag.message}")

    # EVA enforcement: investigation tasks at Analytical+ must have EVA recorded
    task_type = _extract_field(notes, "TASK_TYPE")
    if task_type == "investigation" and rigor in ("analytical", "scientific", "experimental"):
        eva_status = _extract_field(notes, "EVA")
        if not eva_status:
            blockers.append("EVA not recorded — run Experimental Validity Audit before merge")
        elif eva_status.upper().startswith("FAIL"):
            blockers.append("EVA FAILED — experiment design invalid, fix before merge")

    return len(blockers) == 0, blockers


# ---------------------------------------------------------------------------
# Replication
# ---------------------------------------------------------------------------

@dataclass
class ReplicationNeed:
    """A finding that needs replication."""
    finding_id: str
    title: str
    reason: str  # direction_changing, wide_ci, contradicts_model, low_quality


def find_replication_needs(workspace: Path) -> list[ReplicationNeed]:
    """Identify findings that should be replicated."""
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

        # Wide CI check
        ci = _extract_field(notes, "CI_95")
        if ci:
            try:
                nums = re.findall(r'[-+]?\d*\.?\d+', ci)
                if len(nums) >= 2:
                    lo, hi = float(nums[0]), float(nums[1])
                    effect = _extract_field(notes, "EFFECT_SIZE")
                    if effect:
                        eff_nums = re.findall(r'[-+]?\d*\.?\d+', effect)
                        if eff_nums:
                            eff_val = abs(float(eff_nums[0]))
                            if eff_val > 0 and (hi - lo) / eff_val > 0.6:
                                reasons.append("wide_ci")
            except (ValueError, IndexError):
                pass

        # Low quality score
        quality = _extract_field(notes, "QUALITY")
        if quality:
            try:
                if float(quality) < 0.7:
                    reasons.append("low_quality")
            except ValueError:
                pass

        if reasons:
            needs.append(ReplicationNeed(
                finding_id=tid,
                title=title,
                reason=reasons[0],
            ))

    return needs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_field(notes: str, field_name: str) -> str:
    """Extract a field value from Beads notes string."""
    pattern = rf"\b{re.escape(field_name)}\s*[:=]\s*([^\n|]+)"
    m = re.search(pattern, notes, re.I)
    return m.group(1).strip() if m else ""


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
            conflict_val = _extract_field(notes, "CONSISTENCY_CONFLICT")
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
            status = _extract_field(notes, "STATUS")
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
        # High impact: priority 0 or 1
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
    bm = load_belief_map(workspace)
    blockers: list[str] = []
    for h in bm.hypotheses:
        if h.status != "confirmed":
            continue
        # Check if there's a contradicting finding in the evidence chain
        # by looking for VALENCE:negative on a finding that supports this hypothesis
        if not h.evidence:
            continue
        # We can only detect misalignment if the workspace has tasks
        # The orchestrator should mark hypotheses with RESULT_DIRECTION
        # For now, flag any confirmed hypothesis with explicit contradiction note
    # Check tasks for explicit RESULT_CONTRADICTS_HYPOTHESIS flags
    tasks = _fetch_tasks(workspace)
    if tasks:
        for t in tasks:
            notes = t.get("notes", "")
            if "RESULT_CONTRADICTS_HYPOTHESIS" in notes and t.get("status") != "closed":
                blockers.append(
                    f"Result contradicts hypothesis in task {t.get('id', '?')}: "
                    f"{_extract_field(notes, 'RESULT_CONTRADICTS_HYPOTHESIS')}"
                )
    return blockers


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


# ---------------------------------------------------------------------------
# Claim-Evidence Registry
# ---------------------------------------------------------------------------

@dataclass
class ClaimEvidence:
    """A single claim linked to its supporting evidence."""
    claim_id: str
    claim_text: str
    finding_ids: list[str] = field(default_factory=list)
    hypothesis_ids: list[str] = field(default_factory=list)
    strength: str = "provisional"  # robust, provisional, weak, unsupported
    interpretation: str = ""


@dataclass
class ClaimEvidenceRegistry:
    """Maps every claim in the deliverable to supporting findings."""
    claims: list[ClaimEvidence] = field(default_factory=list)
    orphan_findings: list[str] = field(default_factory=list)  # findings not cited
    unsupported_claims: list[str] = field(default_factory=list)  # claims with no evidence
    coverage_score: float = 0.0

    def add_claim(self, claim: ClaimEvidence) -> None:
        self.claims.append(claim)

    def audit(self, all_finding_ids: list[str]) -> None:
        """Compute orphan findings and unsupported claims."""
        cited = set()
        for c in self.claims:
            cited.update(c.finding_ids)
            if not c.finding_ids:
                self.unsupported_claims.append(c.claim_id)
        self.orphan_findings = [f for f in all_finding_ids if f not in cited]
        total = len(self.claims)
        supported = total - len(self.unsupported_claims)
        self.coverage_score = supported / total if total > 0 else 0.0


def load_claim_evidence(workspace: Path) -> ClaimEvidenceRegistry:
    """Load claim-evidence registry from .swarm/claim-evidence.json."""
    path = workspace / ".swarm" / "claim-evidence.json"
    if not path.exists():
        return ClaimEvidenceRegistry()
    try:
        data = json.loads(path.read_text())
        reg = ClaimEvidenceRegistry(
            orphan_findings=data.get("orphan_findings", []),
            unsupported_claims=data.get("unsupported_claims", []),
            coverage_score=data.get("coverage_score", 0.0),
        )
        for c in data.get("claims", []):
            reg.claims.append(ClaimEvidence(
                claim_id=c.get("claim_id", ""),
                claim_text=c.get("claim_text", ""),
                finding_ids=c.get("finding_ids", []),
                hypothesis_ids=c.get("hypothesis_ids", []),
                strength=c.get("strength", "provisional"),
                interpretation=c.get("interpretation", ""),
            ))
        return reg
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load claim-evidence registry: %s", e)
        return ClaimEvidenceRegistry()


def save_claim_evidence(workspace: Path, reg: ClaimEvidenceRegistry) -> None:
    """Save claim-evidence registry to .swarm/claim-evidence.json."""
    path = workspace / ".swarm" / "claim-evidence.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "claims": [asdict(c) for c in reg.claims],
        "orphan_findings": reg.orphan_findings,
        "unsupported_claims": reg.unsupported_claims,
        "coverage_score": reg.coverage_score,
    }
    path.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Pre-registration Compliance Audit
# ---------------------------------------------------------------------------

@dataclass
class PreRegComplianceResult:
    """Result of checking whether execution matched pre-registered design."""
    compliant: bool
    deviations: list[str] = field(default_factory=list)
    undocumented_deviations: list[str] = field(default_factory=list)
    message: str = ""


def audit_pre_registration_compliance(task_notes: str) -> PreRegComplianceResult:
    """Check whether a completed investigation documented all deviations.

    Looks for PRE_REG fields and then checks that any PRE_REG_DEVIATION
    entries exist if the results diverge from expected results.
    """
    pre_reg = parse_pre_registration(task_notes)
    deviations = pre_reg.deviations
    issues: list[str] = []

    # Check if expected result was achieved
    actual_valence = _extract_field(task_notes, "VALENCE")
    if pre_reg.expected_result and actual_valence:
        expected_positive = any(w in pre_reg.expected_result.lower()
                                for w in ("higher", "better", "increase", "outperform",
                                          "improve", "greater", "more"))
        actual_negative = actual_valence.lower() in ("negative", "inconclusive")
        # If expected positive but got negative, check for deviation doc
        if expected_positive and actual_negative and not deviations:
            issues.append(
                "Result contradicts expected outcome but no PRE_REG_DEVIATION documented"
            )

    # Check for sample size deviations
    planned_n = pre_reg.sample_size
    actual_n = _extract_field(task_notes, "N")
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


# ---------------------------------------------------------------------------
# Enhanced Consistency Check — Semantic Similarity
# ---------------------------------------------------------------------------

def _tokenize_title(title: str) -> set[str]:
    """Extract meaningful tokens from a finding title for topic comparison.

    Uses stemming-like suffix stripping and stopword removal for better
    topic matching than raw 4-char word overlap.
    """
    _STOPWORDS = frozenset({
        "finding", "that", "this", "with", "from", "have", "been", "were",
        "does", "more", "than", "also", "into", "when", "each", "only",
        "both", "over", "some", "other", "about", "between", "through",
        "after", "before", "under", "above", "such", "most", "very",
        "just", "those", "these", "their", "there", "which", "while",
        "would", "could", "should", "shall", "will", "being", "having",
        "make", "made", "like", "used",
    })
    # Extract words 3+ chars, lowercase
    words = set(re.findall(r'\b[a-z]{3,}\b', title.lower()))
    words -= _STOPWORDS
    # Simple suffix stripping (s, ing, ed, tion, ness, ment, ly)
    stemmed = set()
    for w in words:
        for suffix in ("ation", "tion", "ness", "ment", "ting", "ing",
                        "ies", "ied", "ed", "ly", "er", "es", "ss"):
            if w.endswith(suffix) and len(w) - len(suffix) >= 3:
                w = w[:-len(suffix)]
                break
        stemmed.add(w)
    return stemmed


def check_consistency_enhanced(findings: list[dict]) -> list[ConsistencyConflict]:
    """Enhanced pairwise consistency check with better topic matching.

    Uses stemmed token overlap and checks for magnitude conflicts
    in addition to valence direction.
    """
    conflicts: list[ConsistencyConflict] = []
    validated = [f for f in findings
                 if "STAT_REVIEW: APPROVED" in f.get("notes", "")]

    for i, a in enumerate(validated):
        for b in validated[i + 1:]:
            conflict = _check_pair_enhanced(a, b)
            if conflict:
                conflicts.append(conflict)

    return conflicts


def _check_pair_enhanced(a: dict, b: dict) -> Optional[ConsistencyConflict]:
    """Enhanced pair consistency check — direction + magnitude + overlap."""
    notes_a = a.get("notes", "")
    notes_b = b.get("notes", "")

    title_a = a.get("title", "")
    title_b = b.get("title", "")

    tokens_a = _tokenize_title(title_a)
    tokens_b = _tokenize_title(title_b)
    overlap = tokens_a & tokens_b

    if len(overlap) < 2:
        return None  # Different topics

    valence_a = _extract_field(notes_a, "VALENCE")
    valence_b = _extract_field(notes_b, "VALENCE")

    # Direction conflict: opposing valence on overlapping topic
    if valence_a and valence_b:
        if {valence_a.lower(), valence_b.lower()} == {"positive", "negative"}:
            return ConsistencyConflict(
                finding_a=a.get("id", ""),
                finding_b=b.get("id", ""),
                conflict_type="direction",
                description=f"Opposing valence on related topic "
                            f"(shared: {', '.join(sorted(overlap)[:5])}): "
                            f"{title_a} ({valence_a}) vs "
                            f"{title_b} ({valence_b})",
            )

    # Magnitude conflict: same valence but very different effect sizes
    es_a = _extract_field(notes_a, "EFFECT_SIZE")
    es_b = _extract_field(notes_b, "EFFECT_SIZE")
    if es_a and es_b and len(overlap) >= 3:
        try:
            nums_a = re.findall(r'[-+]?\d*\.?\d+', es_a)
            nums_b = re.findall(r'[-+]?\d*\.?\d+', es_b)
            if nums_a and nums_b:
                val_a = abs(float(nums_a[0]))
                val_b = abs(float(nums_b[0]))
                if val_a > 0 and val_b > 0:
                    ratio = max(val_a, val_b) / min(val_a, val_b)
                    if ratio > 3.0:  # 3x difference on same topic = suspicious
                        return ConsistencyConflict(
                            finding_a=a.get("id", ""),
                            finding_b=b.get("id", ""),
                            conflict_type="magnitude",
                            description=f"Large magnitude difference on related topic "
                                        f"(shared: {', '.join(sorted(overlap)[:5])}): "
                                        f"d={es_a} vs d={es_b} ({ratio:.1f}x)",
                        )
        except (ValueError, ZeroDivisionError):
            pass

    return None


# ---------------------------------------------------------------------------
# Finding Interpretation Helpers
# ---------------------------------------------------------------------------

def classify_effect_size(d: float) -> str:
    """Classify Cohen's d into practical significance categories."""
    d = abs(d)
    if d < 0.2:
        return "negligible"
    if d < 0.5:
        return "small"
    if d < 0.8:
        return "medium"
    if d < 1.2:
        return "large"
    return "very large"


def assess_ci_quality(effect_str: str, ci_str: str) -> str:
    """Assess confidence interval precision relative to effect size."""
    try:
        nums_e = re.findall(r'[-+]?\d*\.?\d+', effect_str)
        nums_ci = re.findall(r'[-+]?\d*\.?\d+', ci_str)
        if not nums_e or len(nums_ci) < 2:
            return "unknown"
        effect = abs(float(nums_e[0]))
        lo, hi = float(nums_ci[0]), float(nums_ci[1])
        width = hi - lo
        if effect <= 0:
            return "unknown"
        ratio = width / effect
        if ratio < 0.5:
            return "precise"
        if ratio < 1.0:
            return "adequate"
        if ratio < 1.5:
            return "wide"
        return "very wide"
    except (ValueError, IndexError):
        return "unknown"


def interpret_finding(finding: dict) -> dict:
    """Produce a rich interpretation of a finding for report generation.

    Returns dict with fields: practical_significance, ci_quality,
    interpretation_text, strength_label.
    """
    notes = finding.get("notes", "")
    es = _extract_field(notes, "EFFECT_SIZE")
    ci = _extract_field(notes, "CI_95")
    valence = _extract_field(notes, "VALENCE")
    robust = _extract_field(notes, "ROBUST")
    stat_review = _extract_field(notes, "STAT_REVIEW")
    p_val = _extract_field(notes, "P")

    result: dict = {
        "practical_significance": "unknown",
        "ci_quality": "unknown",
        "interpretation_text": "",
        "strength_label": "unreviewed",
    }

    # Effect size interpretation
    if es:
        try:
            nums = re.findall(r'[-+]?\d*\.?\d+', es)
            if nums:
                d_val = float(nums[0])
                result["practical_significance"] = classify_effect_size(d_val)
        except ValueError:
            pass

    # CI quality
    if es and ci:
        result["ci_quality"] = assess_ci_quality(es, ci)

    # Strength label
    if "APPROVED" in str(stat_review):
        if robust and robust.lower() == "yes":
            result["strength_label"] = "robust"
        elif robust and robust.lower() == "no":
            result["strength_label"] = "fragile"
        else:
            result["strength_label"] = "reviewed"
    elif "REJECTED" in str(stat_review):
        result["strength_label"] = "rejected"

    # Build interpretation text
    title = _clean_finding_title(finding.get("title", ""))
    parts = []
    if valence:
        parts.append(f"{valence} result")
    if result["practical_significance"] != "unknown":
        parts.append(f"{result['practical_significance']} practical effect")
    if result["ci_quality"] in ("wide", "very wide"):
        parts.append("imprecise estimate — interpret with caution")
    elif result["ci_quality"] == "precise":
        parts.append("precisely estimated")
    if result["strength_label"] == "robust":
        parts.append("robust under sensitivity analysis")
    elif result["strength_label"] == "fragile":
        parts.append("fragile — conditions documented")

    result["interpretation_text"] = "; ".join(parts) if parts else ""

    return result


def _clean_finding_title(title: str) -> str:
    """Strip leading FINDING: prefix."""
    for prefix in ("FINDING:", "FINDING"):
        if title.upper().startswith(prefix):
            title = title[len(prefix):]
            break
    return title.strip()


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
    """Check data-file invariants (e.g. min_csv_rows) against actual files.

    Scans the workspace for CSV files matching the invariant's glob pattern
    and verifies each meets the minimum row count.
    """
    import csv as csv_mod
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
    """Check whether pilot experiment results meet calibration targets.

    Reads CALIBRATION_TARGET and CALIBRATION_ACTUAL from Beads notes.
    Format: CALIBRATION_TARGET:metric_name=[lo, hi]
            CALIBRATION_ACTUAL:metric_name=value
    """
    results: list[CalibrationResult] = []
    targets: dict[str, tuple[float, float]] = {}
    actuals: dict[str, float] = {}

    for line in task_notes.split("\n"):
        line = line.strip()
        # Parse targets: CALIBRATION_TARGET:recall_l4=[0.5, 0.7]
        t_match = re.search(
            r"CALIBRATION_TARGET\s*:\s*(\w+)\s*=\s*\[([\d.]+)\s*,\s*([\d.]+)\]",
            line, re.I,
        )
        if t_match:
            targets[t_match.group(1)] = (float(t_match.group(2)), float(t_match.group(3)))
        # Parse actuals: CALIBRATION_ACTUAL:recall_l4=0.65
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
    ctx["revise_of"] = _extract_field(task_notes, "REVISE_OF")
    ctx["prior_result"] = _extract_field(task_notes, "PRIOR_RESULT")
    ctx["failure_diagnosis"] = _extract_field(task_notes, "FAILURE_DIAGNOSIS")
    ctx["revised_params"] = _extract_field(task_notes, "REVISED_PARAMS")
    return {k: v for k, v in ctx.items() if v}


# ---------------------------------------------------------------------------
# Structured Heartbeats
# ---------------------------------------------------------------------------

@dataclass
class Heartbeat:
    """A single heartbeat from a running agent."""
    branch: str
    phase: str
    iteration: int
    last_action: str
    status: str
    timestamp: str = ""


def write_heartbeat(workspace: Path, heartbeat: Heartbeat) -> None:
    """Append a heartbeat entry to .swarm/heartbeat-<branch>.jsonl."""
    heartbeat.timestamp = datetime.now(timezone.utc).isoformat()
    path = workspace / ".swarm" / f"heartbeat-{heartbeat.branch}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(asdict(heartbeat)) + "\n")


def read_heartbeats(workspace: Path, branch: str,
                    last_n: int = 10) -> list[Heartbeat]:
    """Read last N heartbeats for a branch."""
    path = workspace / ".swarm" / f"heartbeat-{branch}.jsonl"
    if not path.exists():
        return []
    heartbeats: list[Heartbeat] = []
    try:
        lines = path.read_text().strip().split("\n")
        for line in lines[-last_n:]:
            if not line.strip():
                continue
            data = json.loads(line)
            heartbeats.append(Heartbeat(
                branch=data.get("branch", branch),
                phase=data.get("phase", ""),
                iteration=data.get("iteration", 0),
                last_action=data.get("last_action", ""),
                status=data.get("status", ""),
                timestamp=data.get("timestamp", ""),
            ))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to read heartbeats for %s: %s", branch, e)
    return heartbeats


def check_heartbeat_stall(workspace: Path, branch: str,
                          stall_minutes: int = 10) -> bool:
    """Return True if the agent appears stalled (same status for stall_minutes)."""
    beats = read_heartbeats(workspace, branch, last_n=5)
    if len(beats) < 2:
        return False
    # Check if all recent heartbeats have the same status + phase
    signatures = {(b.phase, b.status) for b in beats}
    if len(signatures) > 1:
        return False
    # Check time span
    try:
        first_ts = datetime.fromisoformat(beats[0].timestamp)
        last_ts = datetime.fromisoformat(beats[-1].timestamp)
        span = (last_ts - first_ts).total_seconds() / 60
        return span >= stall_minutes
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# LLM-as-Judge Primitive
# ---------------------------------------------------------------------------

@dataclass
class JudgeVerdict:
    """Structured verdict from an LLM judge call."""
    match: bool
    confidence: float  # 0.0–1.0
    justification: str
    rubric_id: str = ""
    model: str = ""


@dataclass
class JudgeRubric:
    """Structured evaluation rubric for LLM judge calls."""
    rubric_id: str
    criteria: str
    scale: str = "binary"  # binary, likert5, score100
    examples: str = ""


def format_judge_prompt(rubric: JudgeRubric, candidate: str,
                       reference: str) -> str:
    """Format a structured judge prompt from rubric + candidate + reference."""
    parts = [
        "You are an evaluation judge. Assess whether the candidate matches "
        "the reference according to the rubric below.\n",
        f"## Rubric\n{rubric.criteria}\n",
        f"## Scale\n{rubric.scale}\n",
    ]
    if rubric.examples:
        parts.append(f"## Examples\n{rubric.examples}\n")
    parts.append(f"## Reference\n{reference}\n")
    parts.append(f"## Candidate\n{candidate}\n")
    parts.append(
        "## Your Verdict\n"
        "Respond with EXACTLY this JSON (no other text):\n"
        '{"match": true/false, "confidence": 0.0-1.0, "justification": "..."}\n'
    )
    return "\n".join(parts)


def parse_judge_verdict(raw_output: str, rubric_id: str = "",
                       model: str = "") -> JudgeVerdict:
    """Parse a judge verdict from raw LLM output."""
    # Try to extract JSON from the output
    json_match = re.search(r'\{[^{}]*"match"[^{}]*\}', raw_output, re.S)
    if json_match:
        try:
            data = json.loads(json_match.group())
            return JudgeVerdict(
                match=bool(data.get("match", False)),
                confidence=float(data.get("confidence", 0.0)),
                justification=str(data.get("justification", "")),
                rubric_id=rubric_id,
                model=model,
            )
        except (json.JSONDecodeError, ValueError, TypeError):
            pass
    # Fallback: look for simple match determination
    lower = raw_output.lower()
    if '"match": true' in lower:
        match_val = True
    elif '"match": false' in lower:
        match_val = False
    else:
        match_val = "yes" in lower.split("\n")[0]
    return JudgeVerdict(
        match=match_val,
        confidence=0.5,
        justification=raw_output[:200],
        rubric_id=rubric_id,
        model=model,
    )


def log_judge_call(workspace: Path, rubric: JudgeRubric,
                   verdict: JudgeVerdict) -> None:
    """Append a judge call to the experiment ledger."""
    path = workspace / ".swarm" / "judge-log.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rubric_id": rubric.rubric_id,
        "rubric_criteria": rubric.criteria[:200],
        "scale": rubric.scale,
        "match": verdict.match,
        "confidence": verdict.confidence,
        "justification": verdict.justification[:500],
        "model": verdict.model,
    }
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")
