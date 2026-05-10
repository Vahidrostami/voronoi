"""Validation helpers for MCP tool inputs.

All validation is done at the tool boundary — if a tool call reaches the
Beads/filesystem layer, its inputs are guaranteed well-formed.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path, PureWindowsPath
from typing import Any


class ValidationError(Exception):
    """Raised when MCP tool input fails validation."""


# ---------------------------------------------------------------------------
# Claim statement validator (delegates to science.claims)
# ---------------------------------------------------------------------------

def require_claim_statement(value: str, field: str = "statement") -> str:
    """Validate a Claim Ledger statement shape at the MCP tool boundary.

    Rejects bare-imperative task directives (e.g. "Analyze pricing dataset").
    Delegates to :func:`voronoi.science.claims.validate_claim_statement`
    for shape validation only. See docs/SCIENCE.md §17.

    Note: duplicate detection is NOT performed here because this function
    has no access to the current ledger. Duplicates are caught by
    ``ClaimLedger.add_claim()`` which passes all existing claims to the
    same validator.
    """
    from voronoi.science.claims import validate_claim_statement

    ok, reason = validate_claim_statement(value, ())
    if not ok:
        raise ValidationError(f"{field}: {reason}")
    return value


# ---------------------------------------------------------------------------
# Enum validators
# ---------------------------------------------------------------------------

VALID_VALENCES = frozenset({"positive", "negative", "inconclusive"})
VALID_PRACTICAL_SIGNIFICANCE = frozenset({
    "negligible", "small", "medium", "large", "very_large",
})
VALID_STAT_REVIEW_VERDICTS = frozenset({"APPROVED", "REJECTED"})
VALID_EXPERIMENT_STATUSES = frozenset({"keep", "discard", "crash", "running"})
VALID_CHECKPOINT_PHASES = frozenset({
    "starting", "scouting", "planning", "investigating",
    "reviewing", "synthesizing", "converging", "complete",
})


def require_enum(value: str, valid: frozenset[str], field: str) -> str:
    """Validate that *value* is one of the allowed enum values."""
    if value not in valid:
        raise ValidationError(
            f"{field} must be one of {sorted(valid)}, got {value!r}"
        )
    return value


# ---------------------------------------------------------------------------
# Numeric validators
# ---------------------------------------------------------------------------

def require_positive_int(value: Any, field: str) -> int:
    """Validate that *value* is a positive integer."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a positive integer, got {value!r}")
    if n <= 0:
        raise ValidationError(f"{field} must be positive, got {n}")
    return n


def require_probability(value: Any, field: str) -> float:
    """Validate 0.0 <= value <= 1.0."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValidationError(f"{field} must be a number 0.0–1.0, got {value!r}")
    if not (0.0 <= f <= 1.0):
        raise ValidationError(f"{field} must be 0.0–1.0, got {f}")
    return f


# ---------------------------------------------------------------------------
# Effect size / CI validators
# ---------------------------------------------------------------------------

_EFFECT_SIZE_RE = re.compile(r"^[dr]=-?\d+\.\d+$")


def require_effect_size(value: str, field: str = "effect_size") -> str:
    """Validate effect size format like ``d=0.82`` or ``r=0.45``."""
    value = value.strip()
    if not _EFFECT_SIZE_RE.match(value):
        raise ValidationError(
            f"{field} must be in format 'd=X.XX' or 'r=X.XX', got {value!r}"
        )
    return value


def require_ci(value: Any, field: str = "ci_95") -> list[float]:
    """Validate a 2-element confidence interval."""
    if isinstance(value, str):
        # Parse "[0.61, 1.03]" format
        value = value.strip().strip("[]")
        parts = [p.strip() for p in value.split(",")]
    elif isinstance(value, (list, tuple)):
        parts = value
    else:
        raise ValidationError(f"{field} must be a 2-element list, got {type(value).__name__}")

    if len(parts) != 2:
        raise ValidationError(f"{field} must have exactly 2 elements, got {len(parts)}")

    try:
        lo, hi = float(parts[0]), float(parts[1])
    except (TypeError, ValueError):
        raise ValidationError(f"{field} elements must be numbers, got {parts}")

    if lo > hi:
        raise ValidationError(f"{field} lower bound ({lo}) > upper bound ({hi})")

    return [lo, hi]


# ---------------------------------------------------------------------------
# File / hash validators
# ---------------------------------------------------------------------------

def require_file_exists(path: str, workspace: str, field: str = "data_file") -> Path:
    """Validate that a file exists relative to the workspace."""
    candidate = Path(path)
    if candidate.is_absolute() or PureWindowsPath(path).is_absolute():
        raise ValidationError(f"{field}: path must be relative to workspace: {path}")
    ws = Path(workspace).resolve()
    full = (ws / candidate).resolve()
    if not full.is_relative_to(ws):
        raise ValidationError(f"{field}: path escapes workspace: {path}")
    if not full.is_file():
        raise ValidationError(f"{field}: file not found: {path}")
    return full


def compute_sha256(file_path: Path) -> str:
    """Compute SHA-256 hash of a file. Returns 'sha256:<hex>'."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return f"sha256:{h.hexdigest()}"


def verify_data_hash(file_path: Path, claimed_hash: str) -> None:
    """Verify a claimed hash matches the actual file content."""
    actual = compute_sha256(file_path)
    if actual != claimed_hash:
        raise ValidationError(
            f"Data hash mismatch for {file_path.name}: "
            f"claimed {claimed_hash}, actual {actual}"
        )


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------

def require_non_empty(value: Any, field: str) -> str:
    """Validate that a string value is non-empty."""
    if not value or not str(value).strip():
        raise ValidationError(f"{field} is required and cannot be empty")
    return str(value).strip()


def require_fields(data: dict[str, Any], required: list[str]) -> None:
    """Validate that all required fields are present and non-empty."""
    missing = [f for f in required if not data.get(f) or not str(data[f]).strip()]
    if missing:
        raise ValidationError(f"Missing required fields: {', '.join(missing)}")


def sanitize_tsv_field(value: str) -> str:
    """Remove tabs and newlines from a string to prevent TSV injection."""
    return str(value).replace("\t", " ").replace("\n", " ").replace("\r", "")
