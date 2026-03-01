"""Multimodal encoding layer for the coupled-decisions framework.

Transforms heterogeneous knowledge sources into reasoning-ready
representations:

* ``statistical_profile`` — quantitative data → StatisticalProfile
* ``constraint_vector``   — policy rules     → ConstraintVector
* ``temporal_belief``     — expert judgments  → TemporalBelief
* ``cross_encoder``       — joint reasoning   → ReasoningResult
"""

from .statistical_profile import encode_quantitative, encode_quantitative_from_config
from .constraint_vector import (
    encode_policy,
    encode_policies,
    compute_feasible_region,
    detect_conflicts,
)
from .temporal_belief import (
    encode_expert,
    encode_expert_from_config,
    encode_experts,
    flag_conflicts_with_data,
    basis_quality,
)
from .cross_encoder import cross_query, cross_query_from_config

__all__ = [
    # statistical profile
    "encode_quantitative",
    "encode_quantitative_from_config",
    # constraint vector
    "encode_policy",
    "encode_policies",
    "compute_feasible_region",
    "detect_conflicts",
    # temporal belief
    "encode_expert",
    "encode_expert_from_config",
    "encode_experts",
    "flag_conflicts_with_data",
    "basis_quality",
    # cross encoder
    "cross_query",
    "cross_query_from_config",
]
