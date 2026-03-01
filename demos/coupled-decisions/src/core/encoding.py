"""Multimodal encoding layer — function signatures and lightweight implementations.

Transforms each knowledge type into a reasoning-ready representation:
    quantitative  → StatisticalProfile
    policy        → ConstraintVector
    expert        → TemporalBelief

Also provides cross_query for joint reasoning across encoded types.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from scipy import stats as sp_stats

from .types import (
    ConstraintHardness,
    ConstraintVector,
    Direction,
    EvidencePacket,
    ExpertBasis,
    ReasoningResult,
    StatisticalProfile,
    TemporalBelief,
)


# ---------------------------------------------------------------------------
# encode_quantitative
# ---------------------------------------------------------------------------

def encode_quantitative(
    data: "np.ndarray",
    *,
    ci_level: float = 0.95,
    seasonality_period: int = 52,
) -> StatisticalProfile:
    """Encode a 1-D numeric array into a StatisticalProfile.

    Parameters
    ----------
    data : np.ndarray
        1-D array of observations (e.g. weekly sales for one SKU).
    ci_level : float
        Confidence interval level (default 0.95).
    seasonality_period : int
        Expected seasonality period in observations (default 52 weeks).

    Returns
    -------
    StatisticalProfile
    """
    data = np.asarray(data, dtype=np.float64).ravel()
    n = len(data)
    if n == 0:
        return StatisticalProfile()

    mean = float(np.mean(data))
    std = float(np.std(data, ddof=1)) if n > 1 else 0.0
    skew = float(sp_stats.skew(data, bias=False)) if n > 2 else 0.0
    kurtosis = float(sp_stats.kurtosis(data, bias=False)) if n > 3 else 0.0

    # Confidence interval (t-distribution)
    if n > 1 and std > 0:
        alpha = 1.0 - ci_level
        t_crit = float(sp_stats.t.ppf(1.0 - alpha / 2, df=n - 1))
        margin = t_crit * std / math.sqrt(n)
        ci_lower = mean - margin
        ci_upper = mean + margin
    else:
        ci_lower = mean
        ci_upper = mean

    # Trend: simple centred moving average (window = seasonality_period or n//4)
    window = min(seasonality_period, max(3, n // 4))
    if n >= window:
        kernel = np.ones(window) / window
        trend = np.convolve(data, kernel, mode="same").tolist()
    else:
        trend = data.tolist()

    # Seasonality: residual from trend, then average per cycle position
    trend_arr = np.array(trend)
    detrended = data - trend_arr
    if n >= seasonality_period:
        season = np.zeros(seasonality_period)
        counts = np.zeros(seasonality_period)
        for i in range(n):
            idx = i % seasonality_period
            season[idx] += detrended[i]
            counts[idx] += 1
        counts[counts == 0] = 1
        season = (season / counts).tolist()
    else:
        season = detrended.tolist()

    residual = (data - trend_arr - np.tile(
        np.array(season[:seasonality_period]),
        (n // seasonality_period) + 1,
    )[:n]).tolist()

    # Structural breaks: simple CUSUM-like detection
    breaks: List[int] = []
    if n > 10:
        cusum = np.cumsum(data - mean)
        cusum_std = np.std(cusum) if np.std(cusum) > 0 else 1.0
        for i in range(1, n):
            if abs(cusum[i] - cusum[i - 1]) > 2.0 * cusum_std:
                breaks.append(i)

    return StatisticalProfile(
        mean=mean,
        std=std,
        skew=skew,
        kurtosis=kurtosis,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        ci_level=ci_level,
        trend=trend,
        seasonality=season,
        residual=residual,
        structural_breaks=breaks,
        n_observations=n,
    )


# ---------------------------------------------------------------------------
# encode_policy
# ---------------------------------------------------------------------------

def encode_policy(rule: Dict[str, Any]) -> ConstraintVector:
    """Encode a policy rule dict into a ConstraintVector.

    Expected *rule* keys (matching data/policies.json schema):
        rule_id, type ("hard"|"soft"), lever, scope, threshold, rationale
    Optional: direction, interactions.
    """
    hardness = ConstraintHardness.HARD if rule.get("type") == "hard" else ConstraintHardness.SOFT
    return ConstraintVector(
        rule_id=str(rule.get("rule_id", "")),
        lever=str(rule.get("lever", "")),
        direction=str(rule.get("direction", ">=")),
        bound=float(rule.get("threshold", 0.0)),
        hardness=hardness,
        scope=rule.get("scope", {}),
        interactions=rule.get("interactions", []),
        rationale=str(rule.get("rationale", "")),
    )


# ---------------------------------------------------------------------------
# encode_expert
# ---------------------------------------------------------------------------

def encode_expert(
    belief: Dict[str, Any],
    *,
    reference_date: Optional[str] = None,
    decay_rate: float = 0.05,
) -> TemporalBelief:
    """Encode an expert belief dict into a TemporalBelief.

    Expected *belief* keys (matching data/expert_beliefs.json schema):
        statement, confidence, recency, domain, basis
    Optional: lever_direction, lever_magnitude.
    """
    basis_str = belief.get("basis", "experience")
    try:
        basis = ExpertBasis(basis_str)
    except ValueError:
        basis = ExpertBasis.EXPERIENCE

    confidence = float(belief.get("confidence", 0.5))

    # Compute current confidence with decay
    recency = belief.get("recency", "")
    current_confidence = confidence
    if recency and reference_date:
        try:
            d_belief = datetime.fromisoformat(recency)
            d_ref = datetime.fromisoformat(reference_date)
            weeks_elapsed = (d_ref - d_belief).days / 7.0
            if weeks_elapsed > 0:
                current_confidence = confidence * math.exp(-decay_rate * weeks_elapsed)
        except (ValueError, TypeError):
            pass

    return TemporalBelief(
        statement=str(belief.get("statement", "")),
        confidence=confidence,
        recency=recency,
        domain=belief.get("domain", []),
        basis=basis,
        decay_rate=decay_rate,
        current_confidence=current_confidence,
        lever_direction=belief.get("lever_direction"),
        lever_magnitude=belief.get("lever_magnitude"),
        conflicts_with_data=bool(belief.get("conflicts_with_data", False)),
    )


# ---------------------------------------------------------------------------
# cross_query
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
          "quantitative" -> list[StatisticalProfile]
          "policy"       -> list[ConstraintVector]
          "expert"       -> list[TemporalBelief]
    lever_filter : str, optional
        If given, restrict reasoning to this lever.

    Returns
    -------
    ReasoningResult
    """
    profiles: List[StatisticalProfile] = encoded_sources.get("quantitative", [])
    constraints: List[ConstraintVector] = encoded_sources.get("policy", [])
    beliefs: List[TemporalBelief] = encoded_sources.get("expert", [])

    # Filter by lever if requested
    if lever_filter:
        constraints = [c for c in constraints if c.lever == lever_filter]
        beliefs = [b for b in beliefs if lever_filter in b.domain]

    # Collect evidence packets from each source
    evidence: List[EvidencePacket] = []
    conflicts: List[Dict[str, Any]] = []
    concordances: List[Dict[str, Any]] = []

    # Quantitative evidence
    for i, prof in enumerate(profiles):
        if prof.n_observations > 0:
            direction = Direction.INCREASE if prof.trend and prof.trend[-1] > prof.mean else Direction.DECREASE
            evidence.append(EvidencePacket(
                agent_id="cross_encoder",
                lever=lever_filter or "",
                direction=direction,
                magnitude=abs(prof.mean),
                confidence=1.0 - (prof.std / (abs(prof.mean) + 1e-9)),
                mechanism="Statistical trend in quantitative data",
                source_types=["quantitative"],
                data={"profile_index": i, "mean": prof.mean, "std": prof.std},
            ))

    # Policy evidence
    for cv in constraints:
        evidence.append(EvidencePacket(
            agent_id="cross_encoder",
            lever=cv.lever,
            direction=Direction.MAINTAIN,
            magnitude=cv.bound,
            confidence=1.0 if cv.hardness == ConstraintHardness.HARD else 0.7,
            mechanism=f"Policy constraint: {cv.rationale}",
            source_types=["policy"],
            data={"rule_id": cv.rule_id, "hardness": cv.hardness.value},
        ))

    # Expert evidence
    for tb in beliefs:
        dir_map = {"increase": Direction.INCREASE, "decrease": Direction.DECREASE}
        direction = dir_map.get(tb.lever_direction or "", Direction.MAINTAIN)
        evidence.append(EvidencePacket(
            agent_id="cross_encoder",
            lever=lever_filter or "",
            related_levers=tb.domain,
            direction=direction,
            magnitude=tb.lever_magnitude or 0.0,
            confidence=tb.current_confidence,
            mechanism=f"Expert belief: {tb.statement[:80]}",
            source_types=["expert"],
            data={"basis": tb.basis.value, "conflicts_with_data": tb.conflicts_with_data},
        ))

    # Detect conflicts: expert vs quantitative direction mismatch
    for ep_quant in [e for e in evidence if "quantitative" in e.source_types]:
        for ep_expert in [e for e in evidence if "expert" in e.source_types]:
            if (
                ep_quant.direction != Direction.MAINTAIN
                and ep_expert.direction != Direction.MAINTAIN
                and ep_quant.direction != ep_expert.direction
            ):
                conflicts.append({
                    "type": "direction_mismatch",
                    "quantitative_direction": ep_quant.direction.value,
                    "expert_direction": ep_expert.direction.value,
                    "expert_statement": ep_expert.mechanism,
                })

    # Detect conflicts: expert vs policy
    for ep_policy in [e for e in evidence if "policy" in e.source_types]:
        for ep_expert in [e for e in evidence if "expert" in e.source_types]:
            if ep_expert.lever == ep_policy.lever or ep_policy.lever in ep_expert.related_levers:
                if ep_expert.direction != Direction.MAINTAIN and ep_expert.confidence < 0.5:
                    conflicts.append({
                        "type": "low_confidence_vs_policy",
                        "policy_rule": ep_policy.data.get("rule_id"),
                        "expert_confidence": ep_expert.confidence,
                    })

    # Detect concordances: same direction across types
    directions_by_type = {}
    for ep in evidence:
        for st in ep.source_types:
            if ep.direction != Direction.MAINTAIN:
                directions_by_type.setdefault(st, []).append(ep.direction)

    dir_sets = {st: set(dirs) for st, dirs in directions_by_type.items()}
    if len(dir_sets) >= 2:
        type_list = list(dir_sets.keys())
        for i in range(len(type_list)):
            for j in range(i + 1, len(type_list)):
                overlap = dir_sets[type_list[i]] & dir_sets[type_list[j]]
                if overlap:
                    concordances.append({
                        "types": [type_list[i], type_list[j]],
                        "agreed_directions": [d.value for d in overlap],
                    })

    # Aggregate confidence
    if evidence:
        agg_confidence = float(np.mean([e.confidence for e in evidence]))
    else:
        agg_confidence = 0.0

    answer = (
        f"Cross-type analysis yielded {len(evidence)} evidence items, "
        f"{len(conflicts)} conflict(s), {len(concordances)} concordance(s)."
    )

    return ReasoningResult(
        query=query,
        answer=answer,
        confidence=agg_confidence,
        evidence=evidence,
        conflicts=conflicts,
        concordances=concordances,
    )
