"""Locked Claim — domain-general claim schema for PROVE-mode question locking.

In PROVE mode the user's scientific question is the contract. Voronoi's existing
gates (pre-registration, claim ledger, fabrication, citation coverage) ensure the
*evidence* the agents produce is honest — but none of them compares the *question*
the agents executed against the *question* the user asked. This is the silent
**claim-substitution** failure mode (see SCIENCE.md §24, INV-59).

The locked claim captures the user's intended scientific contract in five slots,
chosen to be minimally sufficient across domains (clinical, ML, physics, etc.)
and machine-comparable slot-by-slot:

  - ``claim``        — the falsifiable proposition (subject, contrast, measure,
                        relation, effect-size, direction collapsed into one line).
  - ``scope``        — boundary conditions / inclusion criteria.
  - ``decision_rule``— predicate that determines support / refute / inconclusive
                        (e.g. ``"Δ ≥ 0.05 AND p < 0.0033 AND both models agree"``).
  - ``falsifier``    — what observation would refute the claim.
  - ``preconditions``— data preconditions that MUST hold for the test to be valid
                        (e.g. ``"T-type labels available for ≥20 cells per type"``);
                        a violated precondition triggers STOP-and-escalate rather
                        than silent rescoping.

Comparable to EviBound's acceptance contract (Chen, arXiv:2511.05524), but
complementary: EviBound binds claims to *artifacts*; ``LockedClaim`` binds claims
to the *scientific question* the artifacts answer.

Persistence:
  - ``.swarm/locked-claim.json``   — written at intake, immutable for the run.
  - ``.swarm/executed-claim.json`` — written by the agents from the ledger at
                                     merge time; compared to the locked claim by
                                     the fidelity gate (see SCIENCE.md §23.3).

This module is the substrate. Intake extraction (LLM-driven) and the dispatcher
merge-gate hookup are follow-up PRs; this stub exposes the dataclass, JSON I/O,
and a deterministic slot-by-slot comparator with an injectable equivalence
function so a future LLM-based equivalence check can be plugged in without
touching call sites.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger("voronoi.science.locked_claim")

LOCKED_CLAIM_FILENAME = "locked-claim.json"
EXECUTED_CLAIM_FILENAME = "executed-claim.json"
LOCKED_CLAIM_SCHEMA_VERSION = 1

SLOT_NAMES: tuple[str, ...] = (
    "claim",
    "scope",
    "decision_rule",
    "falsifier",
    "preconditions",
)


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class LockedClaim:
    """Five-slot claim schema. All slot fields are free text; equivalence at
    compare-time is delegated to an injectable function (default: normalized
    string equality)."""

    claim: str = ""
    scope: str = ""
    decision_rule: str = ""
    falsifier: str = ""
    preconditions: str = ""

    # Provenance metadata (not compared by the fidelity gate).
    locked_at: str = ""           # ISO 8601 UTC timestamp
    locked_by: str = ""           # "user" | "gateway-extractor" | agent id
    source_prompt: str = ""       # original free-text user message (or hash)
    schema_version: int = LOCKED_CLAIM_SCHEMA_VERSION

    @property
    def is_complete(self) -> bool:
        """True iff every claim slot has non-empty content. Metadata slots are
        not required for completeness — extraction may persist the claim with
        empty provenance and fill it in later."""
        return all(getattr(self, s).strip() for s in SLOT_NAMES)

    def missing_slots(self) -> list[str]:
        return [s for s in SLOT_NAMES if not getattr(self, s).strip()]

    def to_dict(self) -> dict:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------------------
# JSON I/O
# ---------------------------------------------------------------------------

def save_locked_claim(claim: LockedClaim, workspace: Path,
                      filename: str = LOCKED_CLAIM_FILENAME) -> Path:
    """Persist a locked or executed claim to ``<workspace>/.swarm/<filename>``."""
    swarm = Path(workspace) / ".swarm"
    swarm.mkdir(parents=True, exist_ok=True)
    path = swarm / filename
    if not claim.locked_at:
        claim.locked_at = _now_iso()
    path.write_text(json.dumps(claim.to_dict(), indent=2, ensure_ascii=False))
    return path


def load_locked_claim(workspace: Path,
                      filename: str = LOCKED_CLAIM_FILENAME) -> Optional[LockedClaim]:
    """Load a claim from ``<workspace>/.swarm/<filename>`` or return ``None`` if
    the file does not exist."""
    path = Path(workspace) / ".swarm" / filename
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        logger.warning("Malformed %s: %s", path, exc)
        return None
    known = {f.name for f in LockedClaim.__dataclass_fields__.values()}
    return LockedClaim(**{k: v for k, v in data.items() if k in known})


# ---------------------------------------------------------------------------
# Fidelity comparison
# ---------------------------------------------------------------------------

@dataclass
class FidelityDiff:
    slot: str
    locked: str
    executed: str
    equivalent: bool
    reason: str = ""


@dataclass
class FidelityResult:
    passed: bool
    diffs: list[FidelityDiff] = field(default_factory=list)

    @property
    def divergent_slots(self) -> list[str]:
        return [d.slot for d in self.diffs if not d.equivalent]

    def summary(self) -> str:
        if self.passed:
            return "Locked claim fidelity: PASS (all slots equivalent)"
        return ("Locked claim fidelity: FAIL on slots: "
                + ", ".join(self.divergent_slots))


_WS_RE = re.compile(r"\s+")
_PUNCT_TAIL_RE = re.compile(r"[\s\.;,:!?]+$")


def _normalize(text: str) -> str:
    """Normalize a slot value for the deterministic equivalence check: lowercase,
    collapse whitespace, strip trailing punctuation. Intentionally conservative
    — semantic equivalence (paraphrasing, synonyms) is the LLM-based extension
    point and is NOT part of the default comparator."""
    text = _WS_RE.sub(" ", text or "").strip().lower()
    return _PUNCT_TAIL_RE.sub("", text)


def normalized_equivalence(a: str, b: str) -> bool:
    """Default equivalence: normalized strings match exactly. Empty strings are
    treated as ``equivalent`` only when both sides are empty (so missing
    declared-executed slots fail the gate)."""
    return _normalize(a) == _normalize(b)


EquivalenceFn = Callable[[str, str], bool]


def compare_claims(locked: LockedClaim, executed: LockedClaim, *,
                   equivalence_fn: EquivalenceFn = normalized_equivalence
                   ) -> FidelityResult:
    """Compare the five claim slots of ``locked`` against ``executed``. Returns
    a ``FidelityResult`` with one ``FidelityDiff`` per slot. ``passed`` is True
    iff every slot is equivalent under ``equivalence_fn``.

    Metadata fields (``locked_at``, ``locked_by``, ``source_prompt``,
    ``schema_version``) are intentionally NOT compared.
    """
    diffs: list[FidelityDiff] = []
    for slot in SLOT_NAMES:
        lv = getattr(locked, slot, "")
        ev = getattr(executed, slot, "")
        equivalent = equivalence_fn(lv, ev)
        reason = "" if equivalent else "normalized strings differ"
        diffs.append(FidelityDiff(slot=slot, locked=lv, executed=ev,
                                  equivalent=equivalent, reason=reason))
    return FidelityResult(passed=all(d.equivalent for d in diffs), diffs=diffs)


__all__ = [
    "LOCKED_CLAIM_FILENAME",
    "EXECUTED_CLAIM_FILENAME",
    "LOCKED_CLAIM_SCHEMA_VERSION",
    "SLOT_NAMES",
    "LockedClaim",
    "FidelityDiff",
    "FidelityResult",
    "EquivalenceFn",
    "normalized_equivalence",
    "save_locked_claim",
    "load_locked_claim",
    "compare_claims",
]
