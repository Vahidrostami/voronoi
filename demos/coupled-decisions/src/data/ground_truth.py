"""Ground-truth interaction effects and multi-collinearity structures.

Defines the 5 planted interaction effects and the lever correlation matrix
used for scoring. These are NEVER exposed to diagnostic agents — they exist
solely so the experiment runner can measure what the system discovers.
"""

from __future__ import annotations

import dataclasses
from typing import Dict, List, Tuple

import numpy as np


# ---------------------------------------------------------------------------
# Interaction effect specification
# ---------------------------------------------------------------------------

@dataclasses.dataclass(frozen=True)
class InteractionEffect:
    """A ground-truth interaction effect planted in the synthetic data."""

    effect_id: str
    name: str
    description: str
    levers: Tuple[str, ...]
    mechanism: str
    expected_impact: Dict[str, float]
    discoverable_from: Tuple[str, ...]
    categories: Tuple[str, ...]
    verification_query: str


# ---------------------------------------------------------------------------
# The 5 planted effects
# ---------------------------------------------------------------------------

PRICE_PROMOTION_TRAP = InteractionEffect(
    effect_id="GT-1",
    name="Price-Promotion Trap",
    description=(
        "Category A SKUs show positive ROI on 30% promotions when analyzed "
        "independently, but a 5% base-price reduction with no promotions "
        "yields 12% higher net revenue. The promotion effect is an artifact "
        "of price-insensitive loyal customers being subsidized."
    ),
    levers=("pricing", "promotion"),
    mechanism="loyal_customer_subsidy",
    expected_impact={
        "promo_only_revenue_delta": 0.03,    # +3% apparent (naive)
        "joint_optimal_revenue_delta": 0.12,  # +12% with base-price cut
        "base_price_reduction": -0.05,        # 5% cut
        "promo_depth_optimal": 0.0,           # eliminate promos
    },
    discoverable_from=("quantitative",),
    categories=("A",),
    verification_query=(
        "Compare Category A net revenue under (a) current promo cadence vs "
        "(b) 5% base-price reduction with no promos."
    ),
)

ASSORTMENT_DISTRIBUTION_SYNERGY = InteractionEffect(
    effect_id="GT-2",
    name="Assortment-Distribution Synergy",
    description=(
        "Removing 8 low-velocity SKUs frees shelf space that, when "
        "reallocated to top SKUs, increases category revenue by 9%. Neither "
        "lever alone produces this: assortment change alone loses 3%, "
        "distribution change alone gains only 2%."
    ),
    levers=("assortment", "distribution"),
    mechanism="shelf_space_reallocation",
    expected_impact={
        "assortment_only_delta": -0.03,
        "distribution_only_delta": 0.02,
        "combined_delta": 0.09,
    },
    discoverable_from=("quantitative",),
    categories=("C", "D"),
    verification_query=(
        "Simulate removing the 8 lowest-velocity SKUs and reallocating "
        "their facings to the top SKUs in those categories."
    ),
)

PACK_PRICE_CANNIBALIZATION_MASK = InteractionEffect(
    effect_id="GT-3",
    name="Pack-Price Cannibalization Mask",
    description=(
        "Introducing a 12-pack at $9.99 appears to grow volume +15% in "
        "isolation, but it cannibalizes the 6-pack at $5.99 by 22%, net "
        "destroying $0.43/unit margin. Only visible when pack-price and "
        "pricing data are analyzed jointly."
    ),
    levers=("pack_price", "pricing"),
    mechanism="intra_brand_cannibalization",
    expected_impact={
        "twelve_pack_volume_lift": 0.15,
        "six_pack_cannibalization": -0.22,
        "net_margin_per_unit_delta": -0.43,
    },
    discoverable_from=("quantitative",),
    categories=("D",),
    verification_query=(
        "Compare per-unit margin across the 6-pack and 12-pack portfolio "
        "before and after 12-pack introduction at week 52."
    ),
)

CROSS_SOURCE_SIGNAL = InteractionEffect(
    effect_id="GT-4",
    name="Cross-Source Signal",
    description=(
        "Quantitative data shows declining Category B sales. Policy mandates "
        "min 30% shelf share for B. Expert judgment says decline is seasonal "
        "and will reverse in Q3. The correct intervention requires "
        "synthesising all three sources: maintain shelf share (policy), "
        "don't panic-promote (expert), shift mix toward higher-margin "
        "B SKUs (data)."
    ),
    levers=("assortment", "promotion", "pricing"),
    mechanism="cross_source_synthesis",
    expected_impact={
        "maintain_shelf_share": True,
        "avoid_panic_promo": True,
        "shift_to_high_margin_skus": True,
    },
    discoverable_from=("quantitative", "policy", "expert"),
    categories=("B",),
    verification_query=(
        "Does the system correctly identify that Category B decline is "
        "seasonal, respect the shelf-share policy, and recommend mix shift "
        "rather than blanket promotion?"
    ),
)

CONSTRAINT_COUPLING_CONFLICT = InteractionEffect(
    effect_id="GT-5",
    name="Constraint-Coupling Conflict",
    description=(
        "An expert suggests aggressive pricing on premium SKUs. Policy "
        "constrains minimum margin at 25%. The expert signal is "
        "directionally correct but must be scoped to only 3 of 12 premium "
        "SKUs where margin headroom exists."
    ),
    levers=("pricing",),
    mechanism="margin_constraint_scoping",
    expected_impact={
        "eligible_premium_skus": 3,
        "total_premium_skus": 12,
        "min_margin_constraint": 0.25,
    },
    discoverable_from=("quantitative", "policy", "expert"),
    categories=("E",),
    verification_query=(
        "Does the system identify that aggressive premium pricing is viable "
        "for only 3 of 12 premium SKUs due to the 25% margin floor?"
    ),
)

# Ordered list for iteration
GROUND_TRUTH_EFFECTS: List[InteractionEffect] = [
    PRICE_PROMOTION_TRAP,
    ASSORTMENT_DISTRIBUTION_SYNERGY,
    PACK_PRICE_CANNIBALIZATION_MASK,
    CROSS_SOURCE_SIGNAL,
    CONSTRAINT_COUPLING_CONFLICT,
]

EFFECT_BY_ID: Dict[str, InteractionEffect] = {e.effect_id: e for e in GROUND_TRUTH_EFFECTS}


# ---------------------------------------------------------------------------
# Multi-collinearity ground-truth correlation matrix
# ---------------------------------------------------------------------------
# Lever ordering: [price, promotion, display, assortment_breadth,
#                  facings_per_sku, pack_size_per_unit_price]
# These are the *true* pairwise correlations planted into the data generator.
# Agents that naively use raw correlations will conflate collinearity with
# causal effects; correct agents will partial-out or flag these.

LEVER_NAMES = (
    "price",
    "promotion_depth",
    "display",
    "assortment_breadth",
    "facings_per_sku",
    "pack_size_per_unit_price",
)

# Target correlations from the spec (ρ-approximate values):
#   Price-Promotion     ρ ≈ −0.60
#   Promotion-Display   ρ ≈  0.70
#   Assortment-Facings  ρ ≈  0.50
#   Pack-Size-Price     ρ ≈  0.85
#
# The raw target matrix is *not* positive semi-definite because the
# price-promo and pack-price constraints are jointly too tight.  We project
# to the nearest PSD correlation matrix so Cholesky decomposition works in
# the generator.  The resulting values stay within ~0.08 of the targets.

_TARGET = np.array(
    [
        #  price  promo  disp   assort facings pack
        [1.00, -0.60, 0.00,  0.00,  0.00,  0.85],   # price
        [-0.60, 1.00, 0.70,  0.00,  0.00,  0.00],   # promotion_depth
        [0.00,  0.70, 1.00,  0.00,  0.00,  0.00],   # display
        [0.00,  0.00, 0.00,  1.00,  0.50,  0.00],   # assortment_breadth
        [0.00,  0.00, 0.00,  0.50,  1.00,  0.00],   # facings_per_sku
        [0.85,  0.00, 0.00,  0.00,  0.00,  1.00],   # pack_size_per_unit_price
    ],
    dtype=np.float64,
)


def _nearest_psd_corr(mat: np.ndarray, eps: float = 1e-3) -> np.ndarray:
    """Project a symmetric matrix to the nearest PSD correlation matrix."""
    sym = (mat + mat.T) / 2
    vals, vecs = np.linalg.eigh(sym)
    vals = np.maximum(vals, eps)
    out = vecs @ np.diag(vals) @ vecs.T
    d = np.sqrt(np.diag(out))
    out = out / np.outer(d, d)
    return out


COLLINEARITY_MATRIX: np.ndarray = _nearest_psd_corr(_TARGET)
_eigvals = np.linalg.eigvalsh(COLLINEARITY_MATRIX)
assert np.all(_eigvals >= -1e-10), "Correlation matrix is not PSD"


# ---------------------------------------------------------------------------
# Low-velocity SKUs for Effect 2 (assortment-distribution synergy)
# ---------------------------------------------------------------------------
# These SKU indices (0-based within their category) are the 8 "low-velocity"
# SKUs that, when removed, free shelf space for top performers.
LOW_VELOCITY_SKU_OFFSETS: Tuple[int, ...] = (0, 1, 7, 8, 9, 2, 3, 6)
# Maps to SKU IDs in categories C (indices 20-29) and D (indices 30-39).
# Offsets 0,1,2,3 from C  →  sku_ids 20,21,22,23
# Offsets 6,7,8,9 from D  →  sku_ids 36,37,38,39

LOW_VELOCITY_SKU_IDS: Tuple[int, ...] = (20, 21, 22, 23, 36, 37, 38, 39)


# ---------------------------------------------------------------------------
# Premium SKU margin headroom for Effect 5
# ---------------------------------------------------------------------------
# Premium SKUs span Cat E (40-49) plus the premium-tier SKUs in other
# categories (indices 2, 5, 8 from A; 12, 15, 18 from B) = 12 total.
# Only 3 have >25% margin headroom after cost.
PREMIUM_SKU_IDS: Tuple[int, ...] = (2, 5, 12, 15, 40, 41, 42, 43, 44, 45, 46, 47)
PREMIUM_SKUS_WITH_HEADROOM: Tuple[int, ...] = (2, 12, 44)


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def get_effect_by_lever_pair(lever_a: str, lever_b: str) -> List[InteractionEffect]:
    """Return all effects involving both levers."""
    return [
        e for e in GROUND_TRUTH_EFFECTS
        if lever_a in e.levers and lever_b in e.levers
    ]


def collinearity_for_pair(lever_a: str, lever_b: str) -> float:
    """Return the ground-truth correlation between two levers."""
    try:
        i = LEVER_NAMES.index(lever_a)
        j = LEVER_NAMES.index(lever_b)
    except ValueError:
        return 0.0
    return float(COLLINEARITY_MATRIX[i, j])
