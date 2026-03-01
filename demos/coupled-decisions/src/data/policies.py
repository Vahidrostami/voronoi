"""Generate ``data/policies.json`` — codified business rules and constraints.

Each policy is a structured object with:
    rule_id, type (hard|soft), lever, scope, threshold, rationale

The policies encode real-world operational constraints that interact with the
five ground-truth effects.  In particular:
  * Minimum margin floor (25%) gates Effect 5 (constraint-coupling conflict).
  * Category B shelf-share minimum feeds Effect 4 (cross-source signal).
  * Promo frequency caps shape the environment for Effect 1 (price-promo trap).
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Policy definitions
# ---------------------------------------------------------------------------

_POLICIES: List[Dict[str, Any]] = [
    # -- Margin constraints (hard) --
    {
        "rule_id": "POL-001",
        "type": "hard",
        "lever": "pricing",
        "scope": {"level": "category", "values": ["A", "B", "C", "D", "E"]},
        "threshold": {"min_margin_pct": 0.25},
        "rationale": (
            "Corporate mandate: no SKU may be sold below 25% gross margin. "
            "Ensures long-term brand health and retailer profitability."
        ),
    },
    {
        "rule_id": "POL-002",
        "type": "hard",
        "lever": "pricing",
        "scope": {"level": "category", "values": ["E"]},
        "threshold": {"min_margin_pct": 0.30},
        "rationale": (
            "Premium tier must maintain at least 30% margin to preserve "
            "brand equity positioning."
        ),
    },
    # -- Promotion frequency (soft) --
    {
        "rule_id": "POL-003",
        "type": "soft",
        "lever": "promotion",
        "scope": {"level": "sku", "values": "all"},
        "threshold": {"max_promo_events_per_quarter": 4},
        "rationale": (
            "Guideline: limit promotional events to 4 per quarter per SKU "
            "to prevent consumer price-reference erosion."
        ),
    },
    {
        "rule_id": "POL-004",
        "type": "soft",
        "lever": "promotion",
        "scope": {"level": "category", "values": ["E"]},
        "threshold": {"max_promo_events_per_quarter": 1},
        "rationale": (
            "Premium SKUs should be promoted sparingly — at most once per "
            "quarter — to avoid diluting premium perception."
        ),
    },
    {
        "rule_id": "POL-005",
        "type": "soft",
        "lever": "promotion",
        "scope": {"level": "sku", "values": "all"},
        "threshold": {"max_promo_depth_pct": 0.40},
        "rationale": (
            "No single promotion should exceed 40% discount depth. "
            "Deep discounts create reference-price anchoring."
        ),
    },
    # -- Shelf space minimums (hard) --
    {
        "rule_id": "POL-006",
        "type": "hard",
        "lever": "distribution",
        "scope": {"level": "category", "values": ["B"]},
        "threshold": {"min_shelf_share_pct": 0.30},
        "rationale": (
            "Category B must maintain at least 30% of allocated shelf space "
            "per contractual agreement with key retail partners."
        ),
    },
    {
        "rule_id": "POL-007",
        "type": "hard",
        "lever": "distribution",
        "scope": {"level": "category", "values": ["A", "C", "D", "E"]},
        "threshold": {"min_shelf_share_pct": 0.10},
        "rationale": (
            "Every active category must occupy at least 10% of its section "
            "shelf space for visibility."
        ),
    },
    {
        "rule_id": "POL-008",
        "type": "hard",
        "lever": "distribution",
        "scope": {"level": "sku", "values": "all"},
        "threshold": {"min_facings": 1},
        "rationale": (
            "Every listed SKU must have at least 1 facing. Zero facings "
            "indicates de-listing, which requires a separate process."
        ),
    },
    # -- Pricing corridor (hard) --
    {
        "rule_id": "POL-009",
        "type": "hard",
        "lever": "pack_price",
        "scope": {"level": "sku_pair", "values": "adjacent_pack_sizes"},
        "threshold": {"max_per_unit_price_gap_pct": 0.20},
        "rationale": (
            "Adjacent pack sizes for the same brand must not differ in "
            "per-unit price by more than 20%. Prevents incoherent pricing "
            "ladders that confuse shoppers."
        ),
    },
    {
        "rule_id": "POL-010",
        "type": "hard",
        "lever": "pricing",
        "scope": {"level": "region", "values": "all"},
        "threshold": {"max_cross_region_price_gap_pct": 0.15},
        "rationale": (
            "The same SKU may not differ in base price by more than 15% "
            "across regions, preventing arbitrage and channel conflict."
        ),
    },
    # -- Brand portfolio rules (soft) --
    {
        "rule_id": "POL-011",
        "type": "soft",
        "lever": "assortment",
        "scope": {"level": "brand_tier", "values": ["value", "mainstream", "premium"]},
        "threshold": {"min_skus_per_tier": 3},
        "rationale": (
            "Each brand tier must carry at least 3 active SKUs to maintain "
            "portfolio breadth and consumer choice."
        ),
    },
    {
        "rule_id": "POL-012",
        "type": "soft",
        "lever": "assortment",
        "scope": {"level": "category", "values": ["A", "B", "C", "D", "E"]},
        "threshold": {"min_active_skus": 5},
        "rationale": (
            "Each category should have at least 5 active SKUs to ensure "
            "competitive shelf presence."
        ),
    },
    # -- Additional constraints --
    {
        "rule_id": "POL-013",
        "type": "hard",
        "lever": "promotion",
        "scope": {"level": "category", "values": ["A", "B", "C", "D", "E"]},
        "threshold": {"max_simultaneous_promo_skus_pct": 0.50},
        "rationale": (
            "No more than 50% of SKUs in a category may be on promotion "
            "simultaneously to prevent category-level margin collapse."
        ),
    },
    {
        "rule_id": "POL-014",
        "type": "soft",
        "lever": "distribution",
        "scope": {"level": "store", "values": "all"},
        "threshold": {"max_total_facings": 400},
        "rationale": (
            "Total facings per store should not exceed allocated fixture "
            "space (~400 facings across the beverage section)."
        ),
    },
    {
        "rule_id": "POL-015",
        "type": "hard",
        "lever": "pricing",
        "scope": {"level": "sku", "values": "all"},
        "threshold": {"min_price": 0.50, "max_price": 8.00},
        "rationale": (
            "Absolute price bounds: no SKU below $0.50 or above $8.00."
        ),
    },
]


# ---------------------------------------------------------------------------
# Generator function
# ---------------------------------------------------------------------------

def generate_policies() -> List[Dict[str, Any]]:
    """Return the list of policy rule dicts."""
    return [dict(p) for p in _POLICIES]


def write_policies(output_dir: str) -> str:
    """Write policies.json and return the file path."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "policies.json")
    with open(path, "w") as fh:
        json.dump(generate_policies(), fh, indent=2)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "data"
    p = write_policies(out)
    print(f"Wrote {len(_POLICIES)} policies to {p}")
