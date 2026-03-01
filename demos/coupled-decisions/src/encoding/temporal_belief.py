"""Encode expert judgments into TemporalBelief objects.

Transforms expert belief dicts into reasoning-ready temporal belief
representations with:
  * Parsed natural language → lever / direction / magnitude
  * Confidence with exponential decay from recency
  * Basis quality classification (analysis > experience > intuition)
  * Conflict detection against quantitative evidence

Only depends on stdlib + numpy.
"""

from __future__ import annotations

import math
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..core.types import (
    Direction,
    ExpertBasis,
    StatisticalProfile,
    TemporalBelief,
)
from ..core.config import Config


# ---------------------------------------------------------------------------
# Basis quality weights (analysis > experience > intuition)
# ---------------------------------------------------------------------------

_DEFAULT_BASIS_WEIGHTS: Dict[str, float] = {
    "analysis": 1.0,
    "experience": 0.7,
    "intuition": 0.4,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encode_expert(
    belief: Dict[str, Any],
    *,
    reference_date: Optional[str] = None,
    decay_rate: float = 0.05,
    basis_weights: Optional[Dict[str, float]] = None,
) -> TemporalBelief:
    """Encode an expert belief dict into a :class:`TemporalBelief`.

    Parameters
    ----------
    belief : dict
        Expected keys: statement, confidence, recency, domain, basis.
        Optional: lever_direction, lever_magnitude.
    reference_date : str, optional
        ISO-8601 date for computing temporal decay. If None, no decay.
    decay_rate : float
        Exponential decay rate per week.
    basis_weights : dict, optional
        Quality weights per basis type. Defaults to analysis=1.0,
        experience=0.7, intuition=0.4.

    Returns
    -------
    TemporalBelief
    """
    bw = basis_weights or _DEFAULT_BASIS_WEIGHTS

    # Parse basis
    basis_str = belief.get("basis", "experience")
    try:
        basis = ExpertBasis(basis_str)
    except ValueError:
        basis = ExpertBasis.EXPERIENCE

    confidence = float(belief.get("confidence", 0.5))
    recency = belief.get("recency", "")

    # Apply basis quality adjustment
    quality_factor = bw.get(basis.value, 0.5)
    adjusted_confidence = confidence * quality_factor

    # Compute temporal decay
    weeks_elapsed = 0.0
    current_confidence = adjusted_confidence
    if recency and reference_date:
        weeks_elapsed = _compute_weeks_elapsed(recency, reference_date)
        if weeks_elapsed > 0:
            current_confidence = adjusted_confidence * math.exp(
                -decay_rate * weeks_elapsed
            )

    # Parse lever direction and magnitude from statement
    lever_direction = belief.get("lever_direction")
    lever_magnitude = belief.get("lever_magnitude")
    if lever_direction is None:
        lever_direction, lever_magnitude = _parse_direction_magnitude(
            belief.get("statement", "")
        )

    return TemporalBelief(
        statement=str(belief.get("statement", "")),
        confidence=confidence,
        recency=recency,
        domain=belief.get("domain", []),
        basis=basis,
        decay_rate=decay_rate,
        current_confidence=current_confidence,
        lever_direction=lever_direction,
        lever_magnitude=lever_magnitude,
        conflicts_with_data=bool(belief.get("conflicts_with_data", False)),
        metadata={
            "basis_quality_factor": quality_factor,
            "weeks_elapsed": weeks_elapsed,
            "adjusted_confidence_before_decay": adjusted_confidence,
        },
    )


def encode_expert_from_config(
    belief: Dict[str, Any],
    config: Config,
    *,
    reference_date: Optional[str] = None,
) -> TemporalBelief:
    """Convenience wrapper using parameters from a :class:`Config`."""
    return encode_expert(
        belief,
        reference_date=reference_date,
        decay_rate=config.expert_decay_rate,
        basis_weights=config.basis_quality_weights,
    )


def encode_experts(
    beliefs: Sequence[Dict[str, Any]],
    *,
    reference_date: Optional[str] = None,
    decay_rate: float = 0.05,
    basis_weights: Optional[Dict[str, float]] = None,
) -> List[TemporalBelief]:
    """Encode a list of expert beliefs into TemporalBelief objects."""
    return [
        encode_expert(
            b,
            reference_date=reference_date,
            decay_rate=decay_rate,
            basis_weights=basis_weights,
        )
        for b in beliefs
    ]


def flag_conflicts_with_data(
    beliefs: Sequence[TemporalBelief],
    profiles: Sequence[StatisticalProfile],
    *,
    threshold: float = 1.0,
) -> List[Dict[str, Any]]:
    """Flag beliefs that conflict with quantitative evidence.

    A conflict is flagged when the belief's direction contradicts the
    quantitative trend, or when the belief's magnitude falls outside
    the confidence interval by more than *threshold* standard deviations.

    Returns a list of conflict descriptors and mutates the
    ``conflicts_with_data`` flag on affected beliefs.
    """
    conflicts: List[Dict[str, Any]] = []

    for belief in beliefs:
        direction = belief.lever_direction
        if direction is None:
            continue

        for i, prof in enumerate(profiles):
            if prof.n_observations < 2:
                continue

            # Determine data trend direction
            if prof.trend and len(prof.trend) >= 2:
                trend_slope = prof.trend[-1] - prof.trend[0]
            else:
                trend_slope = 0.0

            data_direction = (
                "increase" if trend_slope > 0
                else "decrease" if trend_slope < 0
                else None
            )

            # Direction conflict
            if (
                data_direction is not None
                and direction != data_direction
                and direction not in (None, "maintain")
            ):
                belief.conflicts_with_data = True
                conflicts.append({
                    "belief_statement": belief.statement[:80],
                    "belief_direction": direction,
                    "data_direction": data_direction,
                    "data_trend_slope": trend_slope,
                    "profile_index": i,
                    "type": "direction_conflict",
                })

            # Magnitude outlier
            if belief.lever_magnitude is not None and prof.std > 0:
                z = abs(belief.lever_magnitude - prof.mean) / prof.std
                if z > threshold:
                    belief.conflicts_with_data = True
                    conflicts.append({
                        "belief_statement": belief.statement[:80],
                        "belief_magnitude": belief.lever_magnitude,
                        "data_mean": prof.mean,
                        "data_std": prof.std,
                        "z_score": z,
                        "profile_index": i,
                        "type": "magnitude_outlier",
                    })

    return conflicts


def basis_quality(basis: ExpertBasis) -> float:
    """Return the quality weight for a given basis type."""
    return _DEFAULT_BASIS_WEIGHTS.get(basis.value, 0.4)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _compute_weeks_elapsed(recency: str, reference_date: str) -> float:
    """Compute weeks elapsed between recency and reference_date."""
    try:
        d_belief = datetime.fromisoformat(recency)
        d_ref = datetime.fromisoformat(reference_date)
        delta_days = (d_ref - d_belief).days
        return max(0.0, delta_days / 7.0)
    except (ValueError, TypeError):
        return 0.0


# Patterns for parsing direction and magnitude from natural language
_INCREASE_PATTERNS = re.compile(
    r"\b(increase|raise|lift|up|grow|expand|higher|aggressive.*price.*increase"
    r"|gain|improve|boost|trade.?up|accelerat)\b",
    re.IGNORECASE,
)
_DECREASE_PATTERNS = re.compile(
    r"\b(decrease|reduce|lower|cut|drop|decline|shrink|remove|less|fewer"
    r"|down|pull.?back|contract)\b",
    re.IGNORECASE,
)
_MAGNITUDE_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\s*%",
)


def _parse_direction_magnitude(
    statement: str,
) -> Tuple[Optional[str], Optional[float]]:
    """Parse lever direction and magnitude from a natural language statement."""
    direction: Optional[str] = None
    magnitude: Optional[float] = None

    inc = bool(_INCREASE_PATTERNS.search(statement))
    dec = bool(_DECREASE_PATTERNS.search(statement))

    if inc and not dec:
        direction = "increase"
    elif dec and not inc:
        direction = "decrease"
    elif inc and dec:
        # Ambiguous — look at last occurrence
        inc_pos = max(m.start() for m in _INCREASE_PATTERNS.finditer(statement))
        dec_pos = max(m.start() for m in _DECREASE_PATTERNS.finditer(statement))
        direction = "increase" if inc_pos > dec_pos else "decrease"

    mag_match = _MAGNITUDE_PATTERN.search(statement)
    if mag_match:
        magnitude = float(mag_match.group(1)) / 100.0

    return direction, magnitude
