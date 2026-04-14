"""Scientific interpretation layer — directional verification, triviality
screening, interpretation requests, tribunal verdicts, and continuation
proposals.

This module adds the *semantic judgment* that was missing from the existing
structural gates (EVA, Sentinel, metric contracts).  It answers: "Does this
result make scientific sense?" — not just "Did the experiment run correctly?"

Four mechanisms:
  1. **Directional Hypothesis Verification** — three-state classification
     (CONFIRMED / REFUTED_REVERSED / INCONCLUSIVE) comparing observed vs
     expected effect direction.
  2. **Triviality Screening** — classifies hypotheses as NOVEL / EXPECTED /
     TRIVIAL based on causal-model alignment and prior knowledge.
  3. **Interpretation Requests & Tribunal Verdicts** — structured triggers
     for the Judgment Loop when findings are surprising.
  4. **Continuation Proposals** — ranked follow-up experiment suggestions
     generated from self-critique and tribunal verdicts.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("voronoi.science")


# ===================================================================
# 1. Directional Hypothesis Verification
# ===================================================================

class DirectionMatch:
    """Three-state classification for hypothesis direction checking."""
    CONFIRMED = "confirmed"
    REFUTED_REVERSED = "refuted_reversed"
    INCONCLUSIVE = "inconclusive"

    _ALL = frozenset({CONFIRMED, REFUTED_REVERSED, INCONCLUSIVE})

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls._ALL


@dataclass
class DirectionResult:
    """Result of a directional hypothesis verification."""
    match: str            # DirectionMatch constant
    hypothesis_id: str
    expected_direction: str   # e.g. "L4_A < L4_D on regret" or "higher_is_better"
    observed_direction: str   # e.g. "L4_D < L4_A on regret"
    p_value: Optional[float] = None
    effect_size: Optional[float] = None
    explanation: str = ""


def classify_direction(
    expected_direction: str,
    observed_direction: str,
    significant: bool,
) -> str:
    """Classify observed vs expected direction into three states.

    Args:
        expected_direction: The pre-registered expected direction as free text,
            or one of "higher_is_better", "lower_is_better", "positive",
            "negative".
        observed_direction: The observed direction as free text, or same
            vocabulary as *expected_direction*.
        significant: Whether the result is statistically significant.

    Returns:
        One of DirectionMatch.CONFIRMED, REFUTED_REVERSED, INCONCLUSIVE.
    """
    if not significant:
        return DirectionMatch.INCONCLUSIVE

    expected_norm = _normalise_direction(expected_direction)
    observed_norm = _normalise_direction(observed_direction)

    if expected_norm == "unknown" or observed_norm == "unknown":
        # Cannot determine — fall back to text comparison
        if expected_direction.strip().lower() == observed_direction.strip().lower():
            return DirectionMatch.CONFIRMED
        return DirectionMatch.REFUTED_REVERSED

    if expected_norm == observed_norm:
        return DirectionMatch.CONFIRMED
    return DirectionMatch.REFUTED_REVERSED


def _normalise_direction(raw: str) -> str:
    """Normalise a direction string to 'positive', 'negative', or 'unknown'."""
    low = raw.strip().lower()
    positive_signals = {"higher_is_better", "positive", "increase", "larger",
                        "greater", "more", "higher", "better", "improves",
                        "outperforms", "gains"}
    negative_signals = {"lower_is_better", "negative", "decrease", "smaller",
                        "less", "lower", "worse", "reduces", "declines",
                        "underperforms"}
    pos_score = sum(1 for s in positive_signals if s in low)
    neg_score = sum(1 for s in negative_signals if s in low)
    if pos_score > neg_score:
        return "positive"
    if neg_score > pos_score:
        return "negative"
    return "unknown"


# ===================================================================
# 2. Triviality Screening
# ===================================================================

class TrivialityClass:
    """Classification of a hypothesis's novelty."""
    NOVEL = "novel"          # Outcome genuinely uncertain — full investigation
    EXPECTED = "expected"    # Outcome likely but confirmation useful — sanity check
    TRIVIAL = "trivial"      # Outcome obvious — skip or reframe

    _ALL = frozenset({NOVEL, EXPECTED, TRIVIAL})

    @classmethod
    def is_valid(cls, value: str) -> bool:
        return value in cls._ALL


@dataclass
class TrivialityResult:
    """Result of triviality screening for a hypothesis."""
    hypothesis_id: str
    classification: str     # TrivialityClass constant
    rationale: str          # Why this classification
    suggested_action: str   # "full_experiment" | "sanity_check" | "skip" | "reframe"


def screen_triviality(
    hypothesis_id: str,
    hypothesis_statement: str,
    *,
    causal_dag_summary: str = "",
    prior_knowledge: str = "",
) -> TrivialityResult:
    """Screen a hypothesis for triviality based on causal model and priors.

    This is a *heuristic* screen — the Theorist agent does the real judgment.
    This function provides a structured result format for the agent's output.
    When no strong signals are present, defaults to NOVEL (safe conservative).
    """
    low = hypothesis_statement.lower()

    # Obvious patterns that indicate trivial hypotheses
    trivial_signals = [
        "more data improves",
        "larger model performs better",
        "increasing sample size",
        "obvious", "trivially",
        "by definition",
    ]
    expected_signals = [
        "consistent with", "expected from",
        "follows from", "predicted by the model",
        "confirms prior", "replicates known",
        "sanity check", "baseline should",
    ]

    trivial_count = sum(1 for s in trivial_signals if s in low)
    expected_count = sum(1 for s in expected_signals if s in low)

    if trivial_count > 0:
        return TrivialityResult(
            hypothesis_id=hypothesis_id,
            classification=TrivialityClass.TRIVIAL,
            rationale=f"Hypothesis matches {trivial_count} triviality signal(s)",
            suggested_action="skip",
        )
    if expected_count > 0:
        return TrivialityResult(
            hypothesis_id=hypothesis_id,
            classification=TrivialityClass.EXPECTED,
            rationale=f"Hypothesis matches {expected_count} expected-outcome signal(s)",
            suggested_action="sanity_check",
        )
    return TrivialityResult(
        hypothesis_id=hypothesis_id,
        classification=TrivialityClass.NOVEL,
        rationale="No triviality signals detected — outcome genuinely uncertain",
        suggested_action="full_experiment",
    )


# ===================================================================
# 3. Interpretation Requests & Tribunal Verdicts
# ===================================================================

class TribunalVerdict:
    """Possible verdicts from a Judgment Tribunal session."""
    EXPLAINED = "explained"              # Coherent explanation found, testable
    ANOMALY_UNRESOLVED = "anomaly_unresolved"  # No satisfying explanation
    ARTIFACT = "artifact"                # Design flaw — DESIGN_INVALID
    TRIVIAL = "trivial"                  # Result is expected/obvious

    _ALL = frozenset({EXPLAINED, ANOMALY_UNRESOLVED, ARTIFACT, TRIVIAL})


@dataclass
class Explanation:
    """A competing explanation proposed by the Tribunal."""
    id: str                    # E1, E2, etc.
    theory: str                # What this explanation claims
    test: str                  # Minimal experiment to test it
    effort: str = "moderate"   # trivial | moderate | substantial
    tested: bool = False
    test_result: str = ""      # Filled after testing


@dataclass
class InterpretationRequest:
    """A structured trigger for the Judgment Tribunal."""
    finding_id: str
    trigger: str               # refuted_reversed | contradiction | surprising | pre_convergence
    hypothesis_id: str = ""
    expected: str = ""         # What was expected
    observed: str = ""         # What was observed
    causal_edges_violated: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


@dataclass
class TribunalResult:
    """Output of a Judgment Tribunal session."""
    finding_id: str
    verdict: str                        # TribunalVerdict constant
    explanations: list[Explanation] = field(default_factory=list)
    recommended_action: str = ""        # e.g. "test_E1_before_convergence"
    trivial_to_resolve: bool = False    # True if a follow-up can be done from existing data
    tribunal_agents: list[str] = field(default_factory=list)  # Who participated
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


def generate_interpretation_request(
    finding_id: str,
    trigger: str,
    *,
    hypothesis_id: str = "",
    expected: str = "",
    observed: str = "",
    causal_edges_violated: list[str] | None = None,
) -> InterpretationRequest:
    """Create a structured interpretation request for the Tribunal."""
    return InterpretationRequest(
        finding_id=finding_id,
        trigger=trigger,
        hypothesis_id=hypothesis_id,
        expected=expected,
        observed=observed,
        causal_edges_violated=causal_edges_violated or [],
    )


def check_tribunal_clear(workspace: Path) -> tuple[bool, list[str]]:
    """Check if all tribunal verdicts are resolved (no ANOMALY_UNRESOLVED).

    Returns (clear, list_of_blocker_descriptions).
    Used by convergence.py as a pre-convergence gate.
    """
    path = workspace / ".swarm" / "tribunal-verdicts.json"
    if not path.exists():
        return True, []

    try:
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            return True, []
    except (json.JSONDecodeError, OSError):
        return True, []

    blockers: list[str] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        verdict = entry.get("verdict", "")
        if verdict == TribunalVerdict.ANOMALY_UNRESOLVED:
            fid = entry.get("finding_id", "?")
            blockers.append(f"Tribunal: finding {fid} has unresolved anomaly")
        elif verdict == TribunalVerdict.ARTIFACT:
            fid = entry.get("finding_id", "?")
            blockers.append(f"Tribunal: finding {fid} flagged as artifact — DESIGN_INVALID")
    return len(blockers) == 0, blockers


def has_reversed_hypotheses(workspace: Path) -> tuple[bool, list[str]]:
    """Check if any hypotheses have REFUTED_REVERSED status without explanation.

    Reads belief-map.json and tribunal-verdicts.json. A reversed hypothesis
    is *explained* if a tribunal verdict for the corresponding finding is
    EXPLAINED or TRIVIAL.

    Returns (has_unresolved, list_of_descriptions).
    """
    bm_path = workspace / ".swarm" / "belief-map.json"
    if not bm_path.exists():
        return False, []

    try:
        bm_data = json.loads(bm_path.read_text())
        hypotheses = bm_data.get("hypotheses", [])
        if not isinstance(hypotheses, list):
            return False, []
    except (json.JSONDecodeError, OSError):
        return False, []

    # Collect explained finding IDs from tribunal verdicts
    explained_findings: set[str] = set()
    verdict_path = workspace / ".swarm" / "tribunal-verdicts.json"
    if verdict_path.exists():
        try:
            verdicts = json.loads(verdict_path.read_text())
            if isinstance(verdicts, list):
                for v in verdicts:
                    if isinstance(v, dict) and v.get("verdict") in (
                        TribunalVerdict.EXPLAINED, TribunalVerdict.TRIVIAL
                    ):
                        explained_findings.add(v.get("finding_id", ""))
        except (json.JSONDecodeError, OSError):
            pass

    unresolved: list[str] = []
    for h in hypotheses:
        if not isinstance(h, dict):
            continue
        status = h.get("status", "")
        if status == "refuted_reversed":
            h_id = h.get("id", "?")
            h_name = h.get("name", h_id)
            # Check if any evidence for this hypothesis has been explained
            evidence_ids = h.get("evidence", [])
            if any(eid in explained_findings for eid in evidence_ids):
                continue  # Explained — not a blocker
            unresolved.append(
                f"Hypothesis {h_id} ({h_name}) is directionally reversed without explanation"
            )
    return len(unresolved) > 0, unresolved


# ===================================================================
# 4. Continuation Proposals
# ===================================================================

@dataclass
class ContinuationProposal:
    """A structured follow-up experiment proposal."""
    id: str
    target_claim: str                  # Claim ID this addresses
    description: str                   # What to test
    rationale: str                     # Why this would help
    experiment_type: str = "targeted"  # targeted | replication | exploration
    information_gain: float = 0.5      # Estimated information gain [0, 1]
    effort: str = "moderate"           # trivial | moderate | substantial


def generate_continuation_proposals(
    ledger,  # ClaimLedger — not imported to avoid circular dep
    tribunal_results: list[TribunalResult] | None = None,
) -> list[ContinuationProposal]:
    """Generate ranked follow-up experiment proposals from weak claims and
    tribunal verdicts.

    Extends the self-critique in claims.py: instead of just identifying
    weaknesses, this generates *actionable proposals* ranked by information
    gain.
    """
    proposals: list[ContinuationProposal] = []
    pid = 1

    # 1. From tribunal verdicts — highest priority
    for result in (tribunal_results or []):
        for expl in result.explanations:
            if not expl.tested:
                proposals.append(ContinuationProposal(
                    id=f"P{pid}",
                    target_claim=result.finding_id,
                    description=f"Test explanation: {expl.theory}",
                    rationale=f"Tribunal proposed: {expl.test}",
                    experiment_type="targeted",
                    information_gain=0.9 if result.verdict == TribunalVerdict.ANOMALY_UNRESOLVED else 0.6,
                    effort=expl.effort,
                ))
                pid += 1

    # 2. From challenged claims
    for claim in ledger.get_challenged():
        pending = [o for o in claim.challenges
                   if o.status in ("pending", "investigating", "surfaced")]
        for obj in pending:
            proposals.append(ContinuationProposal(
                id=f"P{pid}",
                target_claim=claim.id,
                description=f"Address objection: {obj.concern}",
                rationale=f"Objection {obj.id} ({obj.objection_type}) is pending",
                experiment_type="targeted",
                information_gain=0.7,
                effort="moderate",
            ))
            pid += 1

    # 3. From single-evidence claims (replication needed)
    for claim in ledger.claims:
        if (claim.provenance == "run_evidence"
                and len(claim.supporting_findings) == 1
                and claim.status not in ("retired", "replicated", "challenged")):
            proposals.append(ContinuationProposal(
                id=f"P{pid}",
                target_claim=claim.id,
                description=f"Replicate: {claim.statement[:80]}",
                rationale="Based on single experiment — independent replication recommended",
                experiment_type="replication",
                information_gain=0.5,
                effort="moderate",
            ))
            pid += 1

    # Sort by information_gain descending
    proposals.sort(key=lambda p: p.information_gain, reverse=True)
    return proposals


# ===================================================================
# Persistence helpers
# ===================================================================

def save_interpretation_request(workspace: Path, request: InterpretationRequest) -> Path:
    """Write an interpretation request to .swarm/ for the Tribunal to pick up."""
    path = workspace / ".swarm" / "interpretation-request.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(request), indent=2))
    return path


def load_interpretation_request(workspace: Path) -> InterpretationRequest | None:
    """Load the current interpretation request, if any."""
    path = workspace / ".swarm" / "interpretation-request.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return InterpretationRequest(**data)
    except (json.JSONDecodeError, TypeError, OSError) as e:
        logger.warning("Failed to load interpretation request: %s", e)
        return None


def save_tribunal_result(workspace: Path, result: TribunalResult) -> Path:
    """Append a tribunal result to the verdict log."""
    path = workspace / ".swarm" / "tribunal-verdicts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: list[dict] = []
    if path.exists():
        try:
            data = json.loads(path.read_text())
            if isinstance(data, list):
                existing = data
        except (json.JSONDecodeError, OSError):
            pass
    existing.append(asdict(result))
    path.write_text(json.dumps(existing, indent=2))
    return path


def load_tribunal_results(workspace: Path) -> list[TribunalResult]:
    """Load all tribunal results from the verdict log."""
    path = workspace / ".swarm" / "tribunal-verdicts.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            return []
        results: list[TribunalResult] = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            explanations = [
                Explanation(**e) if isinstance(e, dict) else e
                for e in entry.pop("explanations", [])
            ]
            results.append(TribunalResult(explanations=explanations, **entry))
        return results
    except (json.JSONDecodeError, TypeError, OSError) as e:
        logger.warning("Failed to load tribunal results: %s", e)
        return []


def save_continuation_proposals(workspace: Path,
                                proposals: list[ContinuationProposal]) -> Path:
    """Save continuation proposals for PI review."""
    path = workspace / ".swarm" / "continuation-proposals.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(p) for p in proposals], indent=2))
    return path


def load_continuation_proposals(workspace: Path) -> list[ContinuationProposal]:
    """Load continuation proposals."""
    path = workspace / ".swarm" / "continuation-proposals.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            return []
        return [ContinuationProposal(**p) for p in data if isinstance(p, dict)]
    except (json.JSONDecodeError, TypeError, OSError) as e:
        logger.warning("Failed to load continuation proposals: %s", e)
        return []
