"""Joint reasoning engine across encoded knowledge sources.

Takes a query and all encoded representations (StatisticalProfile,
ConstraintVector, TemporalBelief) and produces a ReasoningResult with:
  * Relevant evidence identification per query
  * Cross-source conflict detection
  * Cross-source concordance detection
  * Evidence trail and aggregated confidence

Only depends on stdlib + numpy.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from ..core.types import (
    ConstraintHardness,
    ConstraintVector,
    Direction,
    EvidencePacket,
    ReasoningResult,
    StatisticalProfile,
    TemporalBelief,
)
from ..core.config import Config


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def cross_query(
    query: str,
    encoded_sources: Dict[str, Any],
    *,
    lever_filter: Optional[str] = None,
) -> ReasoningResult:
    """Joint reasoning across multiple encoded knowledge types.

    Parameters
    ----------
    query : str
        Natural-language or structured query.
    encoded_sources : dict
        Mapping with optional keys:
          ``"quantitative"`` → list[StatisticalProfile]
          ``"policy"``       → list[ConstraintVector]
          ``"expert"``       → list[TemporalBelief]
    lever_filter : str, optional
        If given, restrict reasoning to this lever.

    Returns
    -------
    ReasoningResult
    """
    profiles: List[StatisticalProfile] = encoded_sources.get("quantitative", [])
    constraints: List[ConstraintVector] = encoded_sources.get("policy", [])
    beliefs: List[TemporalBelief] = encoded_sources.get("expert", [])

    # --- Filter by lever ---
    if lever_filter:
        constraints = [c for c in constraints if c.lever == lever_filter]
        beliefs = [b for b in beliefs if lever_filter in b.domain]

    # --- Filter by query relevance ---
    query_levers = _extract_levers_from_query(query)
    if query_levers and not lever_filter:
        constraints = [
            c for c in constraints
            if c.lever in query_levers or not query_levers
        ]
        beliefs = [
            b for b in beliefs
            if any(d in query_levers for d in b.domain) or not query_levers
        ]

    # --- Build evidence packets ---
    evidence: List[EvidencePacket] = []

    # Quantitative evidence
    for i, prof in enumerate(profiles):
        if prof.n_observations > 0:
            direction = _profile_direction(prof)
            trend_confidence = _profile_confidence(prof)
            evidence.append(EvidencePacket(
                agent_id="cross_encoder",
                lever=lever_filter or "",
                direction=direction,
                magnitude=abs(prof.mean),
                confidence=trend_confidence,
                mechanism="Statistical trend in quantitative data",
                source_types=["quantitative"],
                data={
                    "profile_index": i,
                    "mean": prof.mean,
                    "std": prof.std,
                    "n_observations": prof.n_observations,
                    "structural_breaks": len(prof.structural_breaks),
                },
            ))

    # Policy evidence
    for cv in constraints:
        evidence.append(EvidencePacket(
            agent_id="cross_encoder",
            lever=cv.lever,
            direction=Direction.MAINTAIN,
            magnitude=cv.bound,
            confidence=1.0 if cv.hardness == ConstraintHardness.HARD else 0.7,
            mechanism=f"Policy constraint: {cv.rationale[:80]}",
            source_types=["policy"],
            data={
                "rule_id": cv.rule_id,
                "hardness": cv.hardness.value,
                "direction": cv.direction,
                "bound": cv.bound,
            },
        ))

    # Expert evidence
    for tb in beliefs:
        dir_map = {"increase": Direction.INCREASE, "decrease": Direction.DECREASE}
        direction = dir_map.get(tb.lever_direction or "", Direction.MAINTAIN)
        evidence.append(EvidencePacket(
            agent_id="cross_encoder",
            lever=lever_filter or "",
            related_levers=list(tb.domain),
            direction=direction,
            magnitude=tb.lever_magnitude or 0.0,
            confidence=tb.current_confidence,
            mechanism=f"Expert belief: {tb.statement[:80]}",
            source_types=["expert"],
            data={
                "basis": tb.basis.value,
                "conflicts_with_data": tb.conflicts_with_data,
                "original_confidence": tb.confidence,
                "decay_rate": tb.decay_rate,
            },
        ))

    # --- Detect conflicts ---
    conflicts = _detect_conflicts(evidence)

    # --- Detect concordances ---
    concordances = _detect_concordances(evidence)

    # --- Aggregate confidence ---
    if evidence:
        agg_confidence = float(np.mean([e.confidence for e in evidence]))
        # Penalise for conflicts
        conflict_penalty = min(0.3, 0.05 * len(conflicts))
        agg_confidence = max(0.0, agg_confidence - conflict_penalty)
    else:
        agg_confidence = 0.0

    answer = _build_answer(evidence, conflicts, concordances)

    return ReasoningResult(
        query=query,
        answer=answer,
        confidence=agg_confidence,
        evidence=evidence,
        conflicts=conflicts,
        concordances=concordances,
        metadata={
            "lever_filter": lever_filter,
            "n_profiles": len(profiles),
            "n_constraints": len(constraints),
            "n_beliefs": len(beliefs),
        },
    )


def cross_query_from_config(
    query: str,
    encoded_sources: Dict[str, Any],
    config: Config,
    *,
    lever_filter: Optional[str] = None,
) -> ReasoningResult:
    """Convenience wrapper that accepts a Config (for future extensions)."""
    return cross_query(query, encoded_sources, lever_filter=lever_filter)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_LEVER_NAMES = {
    "pricing", "promotion", "assortment", "distribution", "pack_price",
}
_LEVER_PATTERN = re.compile(
    r"\b(" + "|".join(_LEVER_NAMES) + r")\b", re.IGNORECASE,
)


def _extract_levers_from_query(query: str) -> List[str]:
    """Extract lever names mentioned in the query."""
    return list({m.group(1).lower() for m in _LEVER_PATTERN.finditer(query)})


def _profile_direction(prof: StatisticalProfile) -> Direction:
    """Determine the dominant direction from a profile's trend."""
    if prof.trend and len(prof.trend) >= 2:
        slope = prof.trend[-1] - prof.trend[0]
        if slope > 0:
            return Direction.INCREASE
        elif slope < 0:
            return Direction.DECREASE
    return Direction.MAINTAIN


def _profile_confidence(prof: StatisticalProfile) -> float:
    """Compute a confidence score for a profile based on data quality."""
    if prof.n_observations == 0:
        return 0.0
    # Higher observations → higher confidence, capped at 1.0
    obs_factor = min(1.0, prof.n_observations / 52.0)
    # Lower relative std → higher confidence
    if abs(prof.mean) > 1e-9:
        cv = prof.std / abs(prof.mean)
        precision_factor = max(0.0, 1.0 - cv)
    else:
        precision_factor = 0.5
    return 0.6 * obs_factor + 0.4 * precision_factor


def _detect_conflicts(evidence: List[EvidencePacket]) -> List[Dict[str, Any]]:
    """Detect cross-source directional and confidence conflicts."""
    conflicts: List[Dict[str, Any]] = []

    quant = [e for e in evidence if "quantitative" in e.source_types]
    expert = [e for e in evidence if "expert" in e.source_types]
    policy = [e for e in evidence if "policy" in e.source_types]

    # Expert vs quantitative direction mismatch
    for eq in quant:
        for ee in expert:
            if (
                eq.direction != Direction.MAINTAIN
                and ee.direction != Direction.MAINTAIN
                and eq.direction != ee.direction
            ):
                conflicts.append({
                    "type": "direction_mismatch",
                    "source_a": "quantitative",
                    "source_b": "expert",
                    "direction_a": eq.direction.value,
                    "direction_b": ee.direction.value,
                    "detail": ee.mechanism,
                })

    # Expert vs policy tension (low confidence expert contradicts policy)
    for ep in policy:
        for ee in expert:
            if ee.lever == ep.lever or ep.lever in ee.related_levers:
                if ee.direction != Direction.MAINTAIN and ee.confidence < 0.5:
                    conflicts.append({
                        "type": "low_confidence_vs_policy",
                        "policy_rule": ep.data.get("rule_id"),
                        "expert_confidence": ee.confidence,
                        "detail": f"Expert belief with confidence {ee.confidence:.2f} "
                                  f"conflicts with policy {ep.data.get('rule_id')}",
                    })

    # Expert beliefs that are flagged as conflicting with data
    for ee in expert:
        if ee.data.get("conflicts_with_data"):
            conflicts.append({
                "type": "expert_data_conflict_flagged",
                "source": "expert",
                "detail": ee.mechanism,
                "expert_confidence": ee.confidence,
            })

    return conflicts


def _detect_concordances(
    evidence: List[EvidencePacket],
) -> List[Dict[str, Any]]:
    """Detect cross-source agreements (same direction across types)."""
    concordances: List[Dict[str, Any]] = []

    directions_by_type: Dict[str, set] = {}
    for ep in evidence:
        for st in ep.source_types:
            if ep.direction != Direction.MAINTAIN:
                directions_by_type.setdefault(st, set()).add(ep.direction)

    type_list = list(directions_by_type.keys())
    for i in range(len(type_list)):
        for j in range(i + 1, len(type_list)):
            overlap = directions_by_type[type_list[i]] & directions_by_type[type_list[j]]
            if overlap:
                concordances.append({
                    "types": [type_list[i], type_list[j]],
                    "agreed_directions": [d.value for d in overlap],
                })

    return concordances


def _build_answer(
    evidence: List[EvidencePacket],
    conflicts: List[Dict[str, Any]],
    concordances: List[Dict[str, Any]],
) -> str:
    """Build a human-readable answer summary."""
    parts = [
        f"Cross-type analysis yielded {len(evidence)} evidence items, "
        f"{len(conflicts)} conflict(s), {len(concordances)} concordance(s).",
    ]

    if conflicts:
        conflict_types = set(c["type"] for c in conflicts)
        parts.append(f"Conflict types: {', '.join(sorted(conflict_types))}.")

    if concordances:
        for c in concordances:
            parts.append(
                f"Agreement between {' and '.join(c['types'])} "
                f"on direction(s): {', '.join(c['agreed_directions'])}."
            )

    return " ".join(parts)
