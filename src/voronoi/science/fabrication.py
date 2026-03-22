"""Anti-fabrication verification and simulation bypass detection."""

from __future__ import annotations

import csv
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from voronoi.utils import extract_field

from voronoi.science._helpers import _fetch_tasks

logger = logging.getLogger("voronoi.science")


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
    category: str
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
    """Parse numeric columns from a CSV data file."""
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
    """Extract reported statistics from finding notes."""
    result: dict = {}

    effect = extract_field(notes, "EFFECT_SIZE")
    if effect:
        try:
            result["effect_size"] = float(re.sub(r"[^\d.\-]", "", effect))
        except ValueError:
            pass

    ci = extract_field(notes, "CI_95")
    if ci:
        ci_match = re.findall(r"[\-]?\d+\.?\d*", ci)
        if len(ci_match) >= 2:
            try:
                result["ci_lo"] = float(ci_match[0])
                result["ci_hi"] = float(ci_match[1])
            except ValueError:
                pass

    n = extract_field(notes, "N")
    if n:
        try:
            result["n"] = int(re.sub(r"[^\d]", "", n))
        except ValueError:
            pass

    p = extract_field(notes, "P")
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
    if reported_n in actual_sizes:
        return True, ""
    for size in actual_sizes:
        if size * 2 == reported_n or size == reported_n:
            return True, ""
    max_rows = max(actual_sizes) if actual_sizes else 0
    if max_rows == reported_n:
        return True, ""
    return False, (
        f"Reported N={reported_n} but data file has column sizes "
        f"{sorted(set(actual_sizes))}. No column matches reported N."
    )


def _check_suspiciously_clean(data_columns: list[list[float]]) -> list[str]:
    """Detect suspiciously clean data patterns that suggest fabrication."""
    warnings: list[str] = []

    for i, col in enumerate(data_columns):
        if len(col) < 3:
            continue

        if len(set(col)) == 1:
            warnings.append(
                f"Column {i}: all {len(col)} values are identical ({col[0]})"
            )

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
    """Cross-verify a finding's reported numbers against its raw data file."""
    result = AntiFabricationResult(finding_id=finding_id, passed=True)

    # 1. Check data file exists
    data_file_str = extract_field(finding_notes, "DATA_FILE")
    if not data_file_str:
        result.flags.append(FabricationFlag(
            severity="critical", category="data_missing",
            message="No DATA_FILE referenced in finding — cannot verify",
            finding_id=finding_id,
        ))
        result.passed = False
        return result

    data_path = workspace / data_file_str.strip()
    result.data_file_exists = data_path.exists()
    if not result.data_file_exists:
        result.flags.append(FabricationFlag(
            severity="critical", category="data_missing",
            message=f"DATA_FILE '{data_file_str}' does not exist on disk",
            finding_id=finding_id,
        ))
        result.passed = False
        return result

    # 2. Verify hash
    expected_hash = extract_field(finding_notes, "DATA_HASH")
    if expected_hash:
        result.hash_verified = verify_data_hash(data_path, expected_hash.strip())
        if not result.hash_verified:
            actual_hash = compute_data_hash(data_path)
            result.flags.append(FabricationFlag(
                severity="critical", category="hash_mismatch",
                message=(
                    f"DATA_HASH mismatch: expected {expected_hash}, "
                    f"actual {actual_hash}. Data may have been modified."
                ),
                finding_id=finding_id,
            ))
            result.passed = False
    else:
        result.flags.append(FabricationFlag(
            severity="warning", category="hash_missing",
            message="No DATA_HASH in finding — cannot verify data integrity",
            finding_id=finding_id,
        ))

    # 3. Parse data and cross-check reported numbers
    reported = _extract_reported_numbers(finding_notes)
    if data_path.suffix.lower() == ".csv":
        columns = _parse_csv_numbers(data_path)

        if "n" in reported and columns:
            ok, msg = _verify_sample_size_against_data(columns, reported["n"])
            if ok:
                result.numbers_verified = True
            else:
                result.flags.append(FabricationFlag(
                    severity="critical", category="n_mismatch",
                    message=msg, finding_id=finding_id,
                ))
                result.passed = False

        if columns:
            clean_warnings = _check_suspiciously_clean(columns)
            for w in clean_warnings:
                result.flags.append(FabricationFlag(
                    severity="warning", category="too_clean",
                    message=w, finding_id=finding_id,
                ))
    elif data_path.suffix.lower() == ".json":
        try:
            data = json.loads(data_path.read_text())
            if not data:
                result.flags.append(FabricationFlag(
                    severity="warning", category="empty_data",
                    message="DATA_FILE is valid JSON but empty",
                    finding_id=finding_id,
                ))
        except (json.JSONDecodeError, OSError) as e:
            result.flags.append(FabricationFlag(
                severity="critical", category="corrupt_data",
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
            severity="warning", category="no_experiment_script",
            message="No experiment script found in experiments/.",
            finding_id=finding_id,
        ))

    # 5. Check for p-value clustering just below 0.05
    if "p" in reported:
        p = reported["p"]
        if 0.01 < p < 0.05:
            result.flags.append(FabricationFlag(
                severity="info", category="p_cluster",
                message=f"p-value ({p}) is in the suspicious 0.01–0.05 cluster.",
                finding_id=finding_id,
            ))

    # 6. Effect size sanity check
    if "effect_size" in reported:
        d = abs(reported["effect_size"])
        if d > 3.0:
            result.flags.append(FabricationFlag(
                severity="warning", category="implausible_effect",
                message=f"Reported effect size d={reported['effect_size']} is implausibly large (>3.0).",
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
# Simulation / LLM-Bypass Detection
# ---------------------------------------------------------------------------

_SIMULATION_BYPASS_PATTERNS = [
    r"np\.random\.seed\(",
    r"random\.seed\(",
    r"simulate.*what.*(?:LLM|model|agent).*would",
    r"avoids?\s+(?:the\s+)?(?:infeasibility|running)\s+.*(?:copilot|LLM|CLI)\s+calls?",
    r"hardcoded.*(?:detection|probability|score)",
    r"Beta\s*\(\s*\d",
]

_SIMULATED_MODEL_MARKERS = [
    "simulated", "mock", "fake", "synthetic-model", "placeholder",
]


@dataclass
class SimulationBypassResult:
    """Result of simulation/LLM-bypass detection."""
    passed: bool
    flags: list[FabricationFlag] = field(default_factory=list)
    results_model: str = ""
    cache_entries: int = 0
    expected_min_cache: int = 0
    bypass_files: list[str] = field(default_factory=list)

    @property
    def critical_flags(self) -> list[FabricationFlag]:
        return [f for f in self.flags if f.severity == "critical"]


def detect_simulation_bypass(
    workspace: Path,
    expected_min_llm_calls: int = 0,
) -> SimulationBypassResult:
    """Detect if an agent substituted simulation for real LLM calls."""
    result = SimulationBypassResult(passed=True)

    # 1. Check results.json model field
    for results_path in _find_results_files(workspace):
        try:
            data = json.loads(results_path.read_text())
            model = ""
            if isinstance(data, dict):
                model = str(data.get("model", data.get("metadata", {}).get("model", "")))
            if model:
                result.results_model = model
                model_lower = model.lower()
                for marker in _SIMULATED_MODEL_MARKERS:
                    if marker in model_lower:
                        result.flags.append(FabricationFlag(
                            severity="critical", category="simulated_model",
                            message=(
                                f"results.json model='{model}' contains '{marker}' — "
                                f"results appear to come from simulation, not real LLM calls"
                            ),
                        ))
                        result.passed = False
                        break
        except (json.JSONDecodeError, OSError):
            continue

    # 2. Check .llm_cache/ entry count
    cache_dirs = list(workspace.rglob(".llm_cache"))
    total_cache = 0
    for cache_dir in cache_dirs:
        if cache_dir.is_dir():
            total_cache += sum(1 for f in cache_dir.iterdir() if f.is_file())
    result.cache_entries = total_cache
    result.expected_min_cache = expected_min_llm_calls

    if expected_min_llm_calls > 0 and total_cache < expected_min_llm_calls:
        severity = "critical" if total_cache < expected_min_llm_calls // 4 else "warning"
        result.flags.append(FabricationFlag(
            severity=severity, category="insufficient_cache",
            message=(
                f"LLM cache has {total_cache} entries but experiment design "
                f"requires ≥{expected_min_llm_calls} real LLM calls."
            ),
        ))
        if severity == "critical":
            result.passed = False

    # 3. Scan source files for simulation-bypass patterns
    src_dirs = [workspace / "src", workspace / "demos"]
    src_files: list[Path] = list(workspace.glob("*.py"))
    for src_dir in src_dirs:
        if src_dir.is_dir():
            src_files.extend(src_dir.rglob("*.py"))

    compiled_patterns = [re.compile(p, re.IGNORECASE) for p in _SIMULATION_BYPASS_PATTERNS]

    for py_file in src_files:
        try:
            content = py_file.read_text(errors="replace")
        except OSError:
            continue

        for pattern in compiled_patterns:
            matches = pattern.findall(content)
            if matches:
                rel_path = str(py_file.relative_to(workspace))
                fname_lower = py_file.stem.lower()
                is_suspect_file = any(
                    kw in fname_lower
                    for kw in ("sim", "mock", "fake", "stub", "synthetic")
                )
                if is_suspect_file:
                    result.bypass_files.append(rel_path)
                    result.flags.append(FabricationFlag(
                        severity="critical", category="simulation_bypass",
                        message=(
                            f"File '{rel_path}' appears to be a simulation substitute "
                            f"for real LLM calls (matched: {pattern.pattern!r})"
                        ),
                    ))
                    result.passed = False
                    break
                else:
                    # Flag simulation patterns even in non-suspect filenames
                    result.flags.append(FabricationFlag(
                        severity="warning", category="simulation_pattern",
                        message=(
                            f"File '{rel_path}' contains simulation-like code "
                            f"(matched: {pattern.pattern!r}) — verify this is not "
                            f"replacing real LLM calls"
                        ),
                    ))
                    break

    # 4. Check for alternative runner scripts
    run_files = list(workspace.glob("run_*.py")) + list(workspace.glob("run*.py"))
    for demo_dir in workspace.glob("demos/*/"):
        run_files.extend(demo_dir.glob("run_*.py"))
        run_files.extend(demo_dir.glob("run*.py"))
    for sub_dir in workspace.glob("submissions/*/"):
        run_files.extend(sub_dir.glob("run_*.py"))
        run_files.extend(sub_dir.glob("run*.py"))

    for rf in run_files:
        fname_lower = rf.stem.lower()
        if any(kw in fname_lower for kw in ("sim", "mock", "fake")):
            rel_path = str(rf.relative_to(workspace))
            result.bypass_files.append(rel_path)
            result.flags.append(FabricationFlag(
                severity="critical", category="simulation_runner",
                message=(
                    f"Simulation runner '{rel_path}' exists alongside the mandated "
                    f"entry point — results may come from simulation, not real LLM calls"
                ),
            ))
            result.passed = False

    # 5. Check results.json provenance
    for results_path in _find_results_files(workspace):
        try:
            data = json.loads(results_path.read_text())
            if not isinstance(data, dict):
                continue
            runner = str(data.get("runner", data.get("entry_point", "")))
            if runner:
                runner_lower = runner.lower()
                if any(kw in runner_lower for kw in ("sim", "mock", "fake")):
                    result.flags.append(FabricationFlag(
                        severity="critical", category="simulated_provenance",
                        message=(
                            f"results.json runner='{runner}' indicates simulation "
                            f"provenance — not produced by real experiments"
                        ),
                    ))
                    result.passed = False
        except (json.JSONDecodeError, OSError):
            continue

    return result


def _find_results_files(workspace: Path) -> list[Path]:
    """Find results.json files in the workspace."""
    results: list[Path] = []
    for p in workspace.rglob("results.json"):
        parts = p.parts
        if any(part.startswith(".") and part != "." for part in parts):
            if ".swarm" not in str(p):
                continue
        results.append(p)
    return results
