"""Synthetic data generation for the BevCo coupled-decisions scenario.

Modules
-------
ground_truth : Planted interaction effects and multi-collinearity matrix.
generator    : Master data generator (sales, elasticities, market share).
policies     : Business-rule / constraint generation.
experts      : Expert-judgment statement generation.
"""

from __future__ import annotations

from .ground_truth import (
    COLLINEARITY_MATRIX,
    EFFECT_BY_ID,
    GROUND_TRUTH_EFFECTS,
    InteractionEffect,
    LEVER_NAMES,
    LOW_VELOCITY_SKU_IDS,
    PREMIUM_SKUS_WITH_HEADROOM,
    collinearity_for_pair,
    get_effect_by_lever_pair,
)
from .generator import BevCoGenerator
from .policies import generate_policies, write_policies
from .experts import (
    generate_agent_facing_beliefs,
    generate_expert_beliefs,
    write_expert_beliefs,
)

__all__ = [
    # ground_truth
    "GROUND_TRUTH_EFFECTS",
    "EFFECT_BY_ID",
    "COLLINEARITY_MATRIX",
    "LEVER_NAMES",
    "InteractionEffect",
    "LOW_VELOCITY_SKU_IDS",
    "PREMIUM_SKUS_WITH_HEADROOM",
    "collinearity_for_pair",
    "get_effect_by_lever_pair",
    # generator
    "BevCoGenerator",
    # policies
    "generate_policies",
    "write_policies",
    # experts
    "generate_expert_beliefs",
    "generate_agent_facing_beliefs",
    "write_expert_beliefs",
]
