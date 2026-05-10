"""Beads task management tools — validated wrappers around ``bd`` CLI.

Each tool validates inputs, calls ``bd`` via ``voronoi.beads``, and returns
structured results.  Tools are registered with the MCP server in ``server.py``.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path, PureWindowsPath
from typing import Any

from voronoi.beads import run_bd, run_bd_json
from voronoi.mcp.validators import (
    ValidationError,
    compute_sha256,
    require_ci,
    require_effect_size,
    require_enum,
    require_file_exists,
    require_non_empty,
    require_positive_int,
    require_probability,
    verify_data_hash,
    VALID_STAT_REVIEW_VERDICTS,
    VALID_VALENCES,
)

logger = logging.getLogger("voronoi.mcp.tools_beads")

VALID_ROBUST_VALUES = frozenset({"yes", "no"})

# Task types whose closure represents a scientific work product. These MUST
# declare PRODUCES at create-time (INV-56) and MUST link a FINDING task or
# an honest FINDING:NULL rationale at close-time (INV-57).
EXPERIMENT_TASK_TYPES = frozenset({
    "experiment", "investigation", "evaluation",
})

# Task types that always need a non-empty PRODUCES contract (INV-56). Adds
# build/paper to the experiment set — a build task without an output
# artifact has nothing to integrate; a paper task without a manuscript
# file is a phantom completion.
PRODUCES_REQUIRED_TASK_TYPES = EXPERIMENT_TASK_TYPES | frozenset({
    "build", "paper",
})

# Shared filenames that workers historically clobber across tasks (each
# "Analyze business prompt" worker overwrote the previous answer). PRODUCES
# paths matching these basenames are rejected anywhere in the workspace
# (INV-56). Workers MUST namespace outputs under output/<task_id>/… or
# findings/<task_id>/… and use task-specific artifact basenames.
SHARED_PRODUCES_DENYLIST = frozenset({
    "answer.json", "FINAL_ANSWER.json", "final_answer.json",
    "output.json", "result.json", "results.json", "findings.json",
})

_FINDING_TITLE_RE = re.compile(r"^\s*FINDING\s*(?::|-|—)", re.IGNORECASE)

# Marker tokens that turn an imperative-shaped task title from a "ghost
# claim" into a concrete proposition. Mirrors science.claims._RELATIONAL_MARKERS.
_TITLE_RELATIONAL_MARKERS = (
    ">", "<", "=", "≥", "≤", "≠",
    " vs ", " versus ", " causes ", " predicts ", " correlates ",
    " increases ", " decreases ", " is ", " are ", " differs ",
    " exceeds ", " outperforms ", " beats ",
)


def _workspace() -> str:
    return os.environ.get("VORONOI_WORKSPACE", ".")


def _task_data(task_id: str, workspace: str) -> dict[str, Any] | None:
    """Load a Beads task record for note-preserving updates."""
    code, task_data = run_bd_json("show", task_id, "--json", cwd=workspace)
    if code != 0 or not isinstance(task_data, dict):
        return None
    return task_data


def _write_task_notes(task_id: str, notes: str, workspace: str) -> None:
    """Persist a complete note blob for a task."""
    code, stdout = run_bd("update", task_id, "--notes", notes, cwd=workspace)
    if code != 0:
        raise ValidationError(f"bd update failed: {stdout}")


@contextmanager
def _task_notes_lock(workspace: str):
    """Serialize read-modify-write updates to Beads notes within one workspace."""
    try:
        import fcntl  # Unix-only; Voronoi dispatch runs on Unix-like hosts.
    except ImportError:
        yield
        return

    lock_root = Path(tempfile.gettempdir()) / "voronoi-mcp-locks"
    lock_root.mkdir(parents=True, exist_ok=True)
    lock_key = str(Path(workspace).resolve()).encode("utf-8")
    lock_path = lock_root / f"{hashlib.sha256(lock_key).hexdigest()}.notes.lock"
    with lock_path.open("w") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _upsert_line_field(notes: str, field: str, line: str) -> tuple[str, bool]:
    """Replace a whole note line identified by *field*, or append it if absent."""
    pattern = re.compile(rf"(?im)^\s*{re.escape(field)}\s*[:=].*$")
    updated, count = pattern.subn(line, notes)
    if count:
        return updated, True
    if not notes.strip():
        return line, False
    return f"{notes.rstrip()}\n{line}", False


def _upsert_token_field(notes: str, field: str, token: str) -> tuple[str, bool]:
    """Replace a structured token without disturbing unrelated fields on the line."""
    pattern = re.compile(rf"(?im)(^|\|)\s*{re.escape(field)}\s*[:=]\s*[^\n|]*")

    def repl(match: re.Match[str]) -> str:
        prefix = match.group(1)
        return token if not prefix else f"{prefix} {token}"

    updated, count = pattern.subn(repl, notes)
    if count:
        return updated, True
    if not notes.strip():
        return token, False
    return f"{notes.rstrip()}\n{token}", False


def _upsert_task_fields(
    task_id: str,
    workspace: str,
    field_updates: list[tuple[str, str]],
    *,
    line_fields: set[str] | None = None,
    require_existing: bool = True,
) -> str:
    """Merge structured fields into existing Beads notes without clobbering other metadata."""
    with _task_notes_lock(workspace):
        task = _task_data(task_id, workspace)
        if task is None and require_existing:
            raise ValidationError(f"Cannot read task {task_id}")

        notes = task.get("notes", "") if task else ""
        line_fields = line_fields or set()
        for field, value in field_updates:
            if field in line_fields:
                notes, _ = _upsert_line_field(notes, field, value)
            else:
                notes, _ = _upsert_token_field(notes, field, value)

        _write_task_notes(task_id, notes, workspace)
        return notes


def _bracket_safe(value: str) -> str:
    """Normalize text used in bracket-parsed pre-registration fields."""
    return value.replace("[", "(").replace("]", ")").strip()


def _workspace_relative_path(path: str, workspace: str, field: str) -> Path:
    """Resolve a workspace-relative path and reject absolute/escaping paths."""
    path = require_non_empty(path, field)
    candidate = Path(path)
    if candidate.is_absolute() or PureWindowsPath(path).is_absolute():
        raise ValidationError(f"{field}: path must be relative to workspace: {path}")
    ws = Path(workspace).resolve()
    full = (ws / candidate).resolve()
    if not full.is_relative_to(ws):
        raise ValidationError(f"{field}: path escapes workspace: {path}")
    return full


def _iter_artifact_paths(paths: str) -> list[str]:
    """Split a comma-separated artifact path list and drop empty entries."""
    return [path.strip() for path in paths.split(",") if path.strip()]


def _validate_task_title(title: str) -> None:
    """Reject laundered imperative-verb titles at create-time (INV-55).

    Mirrors :func:`voronoi.science.claims.validate_claim_statement` but
    enforces the shape at the *task creation* boundary — so ghost tasks
    like "Analyze business prompt findings" never get dispatched in the
    first place. The Claim Ledger gate (INV-47) remains as defence in
    depth.
    """
    from voronoi.science.claims import _BANNED_PREFIX_RE  # type: ignore[attr-defined]
    stripped = title.strip()
    if not stripped:
        raise ValidationError("title must not be empty")
    m = _BANNED_PREFIX_RE.match(stripped)
    if m is None:
        return
    lower = stripped.lower()
    if any(marker in lower for marker in _TITLE_RELATIONAL_MARKERS):
        return
    raise ValidationError(
        f"title begins with imperative verb {m.group(1)!r} and contains "
        "no relational marker (>, <, vs, causes, predicts, …) — task "
        "titles MUST be concrete propositions or be prefixed with their "
        "type (e.g. 'FINDING:', 'THEORY:', 'BUILD:'). See INV-55."
    )


def _validate_produces_contract(
    task_type: str,
    produces: str,
    workspace: str,
) -> None:
    """Enforce PRODUCES required + denylist for experiment-type tasks (INV-56)."""
    type_key = task_type.strip().lower()
    artifact_paths = _iter_artifact_paths(produces) if produces else []

    if type_key in PRODUCES_REQUIRED_TASK_TYPES and not artifact_paths:
        raise ValidationError(
            f"task_type={type_key!r} MUST declare PRODUCES — declare at "
            "least one output file under output/<task_id>/… or "
            "findings/<task_id>/…. See INV-56."
        )

    for artifact in artifact_paths:
        normalized = artifact.strip().lstrip("./")
        basename = Path(normalized).name
        if basename in SHARED_PRODUCES_DENYLIST:
            raise ValidationError(
                f"PRODUCES path {artifact!r} uses shared artifact "
                f"basename {basename!r}; workers clobber each other's "
                "outputs at this name. Namespace under output/<task_id>/… "
                "or findings/<task_id>/… and use a task-specific filename "
                "such as experiment_metrics.json. See INV-56."
            )
        # Path-escape and absolute-path validation (existing).
        _workspace_relative_path(artifact, workspace, "produces")


def _resolve_created_by(explicit: str) -> str:
    """Resolve task provenance for the CREATED_BY note field (INV-55/56)."""
    if explicit:
        return explicit.strip()
    env = os.environ.get("VORONOI_AGENT_ROLE", "").strip()
    return env or "unknown"


def _is_finding_task_title(title: str) -> bool:
    return bool(_FINDING_TITLE_RE.match(title or ""))


def _has_finding_linkage(
    notes: str,
    workspace: str,
    current_task_id: str,
) -> tuple[bool, str]:
    """Check whether task notes carry FINDING_TASK_IDS or FINDING:NULL rationale."""
    text = notes or ""
    # Collect the line-blocks tagged with FINDING_TASK_IDS.
    for line in text.splitlines():
        s = line.strip()
        if s.upper().startswith("FINDING_TASK_IDS:"):
            payload = s.split(":", 1)[1].strip()
            ids = [tok.strip() for tok in payload.split(",") if tok.strip()]
            if ids:
                for finding_id in ids:
                    if finding_id == current_task_id:
                        return False, (
                            f"FINDING_TASK_IDS references closing task "
                            f"{finding_id}; link a sibling FINDING task instead"
                        )
                    finding_task = _task_data(finding_id, workspace)
                    if finding_task is None:
                        return False, (
                            f"FINDING_TASK_IDS references missing task "
                            f"{finding_id}"
                        )
                    title = str(finding_task.get("title", ""))
                    if not _is_finding_task_title(title):
                        return False, (
                            f"FINDING_TASK_IDS references {finding_id}, but "
                            "that task title does not start with FINDING:, "
                            "FINDING -, or FINDING —"
                        )
                return True, ""
    # FINDING:NULL must carry a rationale of >= 40 chars on the same line
    # (after the marker) or on the immediately following non-empty line.
    lines = [l.rstrip() for l in text.splitlines()]
    for idx, line in enumerate(lines):
        s = line.strip()
        upper = s.upper()
        if upper == "FINDING:NULL" or upper.startswith("FINDING:NULL "):
            inline = s[len("FINDING:NULL"):].strip(": -—\t ")
            if len(inline) >= 40:
                return True, ""
            for follow in lines[idx + 1:]:
                if follow.strip():
                    if len(follow.strip()) >= 40:
                        return True, ""
                    return False, "FINDING:NULL rationale is too short (<40 chars)"
            return False, "FINDING:NULL marker has no rationale"
    return False, (
        "experiment-type task closure requires either "
        "FINDING_TASK_IDS:bd-X[,bd-Y…] linking to FINDING tasks, or "
        "FINDING:NULL <rationale ≥40 chars> documenting an honest null "
        "result. See INV-57."
    )


def _extract_task_type(notes: str) -> str:
    pattern = re.compile(r"(?im)^\s*TASK_TYPE\s*[:=]\s*([A-Za-z_]+)")
    m = pattern.search(notes or "")
    return m.group(1).strip().lower() if m else ""


# ---------------------------------------------------------------------------
# voronoi_create_task
# ---------------------------------------------------------------------------

def create_task(
    title: str,
    task_type: str = "",
    parent: str = "",
    produces: str = "",
    requires: str = "",
    created_by: str = "",
) -> dict[str, Any]:
    """Create a new Beads task with validated artifact contracts.

    Parameters
    ----------
    title : str
        Task title (required). Rejected if it is a bare imperative-verb
        ghost task with no relational marker (INV-55).
    task_type : str
        Task type tag (e.g. 'build', 'investigation', 'scout'). For
        experiment-type values (build, experiment, investigation,
        evaluation, paper) PRODUCES is mandatory and must namespace
        outputs (INV-56).
    parent : str
        Parent task/epic ID for subtask creation.
    produces : str
        Comma-separated list of output files the task MUST create. Paths
        with shared-namespace basenames (answer.json, FINAL_ANSWER.json,
        …) are rejected to prevent worker-vs-worker clobbering.
    requires : str
        Comma-separated list of input files that must exist.
    created_by : str
        Provenance tag (e.g. ``orchestrator`` or ``worker:bd-42``). When
        empty, falls back to ``$VORONOI_AGENT_ROLE`` or ``"unknown"``.
    """
    title = require_non_empty(title, "title")
    _validate_task_title(title)

    ws = _workspace()

    # Validate REQUIRES files exist before creating task
    if requires:
        for req in requires.split(","):
            req = req.strip()
            if req:
                require_file_exists(req, ws, "requires")

    _validate_produces_contract(task_type, produces, ws)

    # Build bd create command
    args = ["create", title]
    if parent:
        args.extend(["--parent", parent])

    code, stdout = run_bd(*args, cwd=ws)
    if code != 0:
        raise ValidationError(f"bd create failed: {stdout}")

    # Extract task ID from output (bd create returns "Created task <id>")
    task_id = ""
    for word in stdout.split():
        if word.startswith("bd-") or word.isdigit():
            task_id = word
            break

    # Write structured notes
    notes_parts: list[str] = []
    if task_type:
        notes_parts.append(f"TASK_TYPE:{task_type}")
    if produces:
        notes_parts.append(f"PRODUCES:{produces}")
    if requires:
        notes_parts.append(f"REQUIRES:{requires}")
    notes_parts.append(f"CREATED_BY:{_resolve_created_by(created_by)}")

    if notes_parts and task_id:
        _upsert_task_fields(
            task_id,
            ws,
            [(line.split(":", 1)[0], line) for line in notes_parts],
            require_existing=False,
        )

    return {"task_id": task_id, "title": title, "status": "created"}


# ---------------------------------------------------------------------------
# voronoi_close_task
# ---------------------------------------------------------------------------

def close_task(task_id: str, reason: str = "") -> dict[str, Any]:
    """Close a task after validating PRODUCES artifacts exist.

    Parameters
    ----------
    task_id : str
        Beads task ID to close.
    reason : str
        Closing reason/summary.
    """
    task_id = require_non_empty(task_id, "task_id")
    ws = _workspace()

    # Check PRODUCES from task notes
    task_data = _task_data(task_id, ws)
    if task_data is None:
        raise ValidationError(f"Cannot read task {task_id}")

    notes = task_data.get("notes", "")
    for line in notes.split("\n"):
        line = line.strip()
        if line.startswith("PRODUCES:"):
            for artifact in line[len("PRODUCES:"):].split(","):
                artifact = artifact.strip()
                if not artifact:
                    continue
                artifact_path = _workspace_relative_path(artifact, ws, "produces")
                if not artifact_path.exists():
                    raise ValidationError(
                        f"Cannot close task: PRODUCES artifact missing: {artifact}"
                    )

    # INV-57: experiment/investigation/evaluation tasks MUST link a
    # FINDING task or carry a FINDING:NULL rationale before closing.
    task_type = _extract_task_type(notes)
    if task_type in EXPERIMENT_TASK_TYPES:
        ok, gate_reason = _has_finding_linkage(notes, ws, task_id)
        if not ok:
            raise ValidationError(f"Cannot close task: {gate_reason}")

    args = ["close", task_id]
    if reason:
        args.extend(["--reason", reason])

    code, stdout = run_bd(*args, cwd=ws)
    if code != 0:
        raise ValidationError(f"bd close failed: {stdout}")

    return {"task_id": task_id, "status": "closed", "reason": reason}


# ---------------------------------------------------------------------------
# voronoi_query_tasks
# ---------------------------------------------------------------------------

def query_tasks(filter_expr: str = "", fields: str = "") -> dict[str, Any]:
    """Query Beads tasks with a filter expression.

    Parameters
    ----------
    filter_expr : str
        Beads query expression (e.g. 'status!=closed AND updated>30m').
    fields : str
        Not used by bd CLI but reserved for future filtering.
    """
    ws = _workspace()

    if filter_expr:
        code, data = run_bd_json("query", filter_expr, "--json", cwd=ws)
    else:
        code, data = run_bd_json("list", "--json", cwd=ws)

    if code != 0:
        return {"tasks": [], "error": "query failed"}

    tasks = data if isinstance(data, list) else []
    return {"tasks": tasks, "count": len(tasks)}


# ---------------------------------------------------------------------------
# voronoi_record_finding
# ---------------------------------------------------------------------------

def record_finding(
    task_id: str,
    effect_size: str,
    ci_95: Any,
    n: Any,
    stat_test: str,
    valence: str,
    data_file: str,
    data_hash: str = "",
    p_value: str = "",
    confidence: Any = "",
    robust: str = "",
    interpretation: str = "",
) -> dict[str, Any]:
    """Record a scientific finding with validated metadata.

    ALL required fields are enforced. Data file existence is verified.
    If ``data_hash`` is provided, it is verified against the actual file;
    if omitted, it is computed automatically.

    Parameters
    ----------
    task_id : str
        Beads task ID.
    effect_size : str
        Effect size in format 'd=X.XX' or 'r=X.XX'.
    ci_95 : list or str
        95% confidence interval as [lo, hi].
    n : int
        Sample size (must be positive).
    stat_test : str
        Statistical test used (e.g. 'Welch t-test').
    valence : str
        One of: positive, negative, inconclusive.
    data_file : str
        Path to raw data file (relative to workspace).
    data_hash : str
        SHA-256 hash of data file. Computed if omitted.
    p_value : str
        P-value (optional).
    confidence : float
        Subjective confidence 0.0–1.0 (optional).
    robust : str
        'yes' or 'no' — sensitivity analysis result (optional).
    interpretation : str
        Practical interpretation of the finding (optional).
    """
    ws = _workspace()
    task_id = require_non_empty(task_id, "task_id")
    effect_size = require_effect_size(effect_size)
    ci = require_ci(ci_95)
    n_val = require_positive_int(n, "n")
    stat_test = require_non_empty(stat_test, "stat_test")
    valence = require_enum(valence, VALID_VALENCES, "valence")
    data_file = require_non_empty(data_file, "data_file")

    # Verify data file exists and hash matches
    file_path = require_file_exists(data_file, ws, "data_file")
    if data_hash:
        verify_data_hash(file_path, data_hash)
    else:
        data_hash = compute_sha256(file_path)

    # Upsert structured finding fields without removing unrelated note metadata.
    field_updates = [
        ("TYPE", "TYPE:finding"),
        ("EFFECT_SIZE", f"EFFECT_SIZE:{effect_size}"),
        ("CI_95", f"CI_95:{ci}"),
        ("N", f"N:{n_val}"),
        ("STAT_TEST", f"STAT_TEST:{stat_test}"),
        ("VALENCE", f"VALENCE:{valence}"),
        ("DATA_FILE", f"DATA_FILE:{data_file}"),
        ("DATA_HASH", f"DATA_HASH:{data_hash}"),
    ]
    if p_value:
        field_updates.append(("P", f"P:{p_value}"))
    if confidence is not None and confidence != "":
        conf = require_probability(confidence, "confidence")
        field_updates.append(("CONFIDENCE", f"CONFIDENCE:{conf}"))
    if robust:
        robust_value = require_enum(str(robust).strip().lower(),
                                    VALID_ROBUST_VALUES, "robust")
        field_updates.append(("ROBUST", f"ROBUST:{robust_value}"))
    if interpretation:
        field_updates.append(("INTERPRETATION", f"INTERPRETATION:{interpretation}"))

    _upsert_task_fields(task_id, ws, field_updates)

    return {
        "task_id": task_id,
        "effect_size": effect_size,
        "ci_95": ci,
        "n": n_val,
        "valence": valence,
        "data_hash": data_hash,
        "status": "recorded",
    }


# ---------------------------------------------------------------------------
# voronoi_stat_review
# ---------------------------------------------------------------------------

def stat_review(
    finding_id: str,
    verdict: str,
    interpretation: str = "",
    practical_significance: str = "",
) -> dict[str, Any]:
    """Record statistician review of a finding.

    Parameters
    ----------
    finding_id : str
        Beads task ID of the finding.
    verdict : str
        One of: APPROVED, REJECTED.
    interpretation : str
        Practical meaning of the finding.
    practical_significance : str
        One of: negligible, small, medium, large, very_large.
    """
    ws = _workspace()
    finding_id = require_non_empty(finding_id, "finding_id")
    verdict = require_enum(verdict, VALID_STAT_REVIEW_VERDICTS, "verdict")

    field_updates = [("STAT_REVIEW", f"STAT_REVIEW:{verdict}")]
    if interpretation:
        field_updates.append(("INTERPRETATION", f"INTERPRETATION:{interpretation}"))
    if practical_significance:
        from voronoi.mcp.validators import VALID_PRACTICAL_SIGNIFICANCE
        require_enum(practical_significance, VALID_PRACTICAL_SIGNIFICANCE,
                     "practical_significance")
        field_updates.append(("PRACTICAL_SIGNIFICANCE", f"PRACTICAL_SIGNIFICANCE:{practical_significance}"))

    _upsert_task_fields(finding_id, ws, field_updates)

    return {"finding_id": finding_id, "verdict": verdict, "status": "reviewed"}


# ---------------------------------------------------------------------------
# voronoi_pre_register
# ---------------------------------------------------------------------------

def pre_register(
    task_id: str,
    hypothesis: str,
    method: str,
    controls: str,
    expected_result: str,
    sample_size: Any,
    stat_test: str,
    effect_size: str,
    alpha: Any = 0.05,
    power: Any = 0.80,
    confounds: str = "",
    sensitivity_plan: str = "",
) -> dict[str, Any]:
    """Pre-register an experiment design before execution.

    All fields are required. This enforces INV-10 structurally.

    Parameters
    ----------
    task_id : str
        Beads task ID.
    hypothesis : str
        Expected outcome/prediction.
    method : str
        Experimental method/design.
    controls : str
        Control conditions.
    expected_result : str
        Concrete expected outcome used by pre-registration gates.
    sample_size : int
        Planned sample size.
    stat_test : str
        Planned statistical test.
    effect_size : str
        Planned effect size for power analysis (for example ``d=0.50``).
    alpha : float
        Significance level (default 0.05).
    power : float
        Statistical power target (default 0.80).
    confounds : str
        Known confounds or threats to validity.
    sensitivity_plan : str
        Parameter variations for sensitivity analysis.
    """
    ws = _workspace()
    task_id = require_non_empty(task_id, "task_id")
    hypothesis = require_non_empty(hypothesis, "hypothesis")
    method = require_non_empty(method, "method")
    controls = require_non_empty(controls, "controls")
    expected_result = require_non_empty(expected_result, "expected_result")
    n = require_positive_int(sample_size, "sample_size")
    stat_test = require_non_empty(stat_test, "stat_test")
    effect_size = require_effect_size(effect_size, "effect_size")
    alpha_val = require_probability(alpha, "alpha")
    power_val = require_probability(power, "power")

    pre_reg_parts = [
        f"HYPOTHESIS=[{_bracket_safe(hypothesis)}]",
        f"METHOD=[{_bracket_safe(method)}]",
        f"CONTROLS=[{_bracket_safe(controls)}]",
        f"EXPECTED_RESULT=[{_bracket_safe(expected_result)}]",
    ]
    if confounds:
        pre_reg_parts.append(f"CONFOUNDS=[{_bracket_safe(confounds)}]")
    pre_reg_parts.extend([
        f"STAT_TEST=[{_bracket_safe(stat_test)}]",
        f"SAMPLE_SIZE=[{n}]",
    ])

    field_updates = [
        ("PRE_REG", f"PRE_REG: {' | '.join(pre_reg_parts)}"),
        (
            "PRE_REG_POWER",
            f"PRE_REG_POWER: EFFECT_SIZE=[{effect_size}] | POWER=[{power_val:.2f}] | ALPHA=[{alpha_val:.2f}] | MIN_N=[{n}]",
        ),
    ]
    if sensitivity_plan:
        field_updates.append(("PRE_REG_SENSITIVITY", f"PRE_REG_SENSITIVITY: {sensitivity_plan.strip()}"))

    _upsert_task_fields(task_id, ws, field_updates, line_fields={"PRE_REG", "PRE_REG_POWER", "PRE_REG_SENSITIVITY"})

    return {
        "task_id": task_id,
        "hypothesis": hypothesis,
        "sample_size": n,
        "status": "pre_registered",
    }
