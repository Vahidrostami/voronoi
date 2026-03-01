"""Generate ``data/expert_beliefs.json`` — expert judgment statements.

Produces 18 expert beliefs with varying correctness, confidence, recency,
and basis.  The mix is:
    * 7 correct beliefs  (align with data)
    * 5 outdated / wrong beliefs
    * 6 conditionally correct beliefs (correct only when combined with
      quantitative evidence or policy constraints)

Key planted signals:
    * Effect 4 — "Category B decline is seasonal and will reverse in Q3"
    * Effect 5 — "Premium segment is under-priced relative to market"
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List


# ---------------------------------------------------------------------------
# Expert belief definitions
# ---------------------------------------------------------------------------

_EXPERT_BELIEFS: List[Dict[str, Any]] = [
    # ===== CORRECT beliefs =====
    {
        "belief_id": "EXP-01",
        "statement": (
            "Category B decline is seasonal and will reverse in Q3. "
            "We see this pattern every year — summer is peak for these SKUs."
        ),
        "confidence": 0.85,
        "recency": "2025-11-15",
        "domain": ["assortment", "promotion"],
        "basis": "experience",
        "ground_truth_alignment": "correct",
        "related_effect": "GT-4",
    },
    {
        "belief_id": "EXP-02",
        "statement": (
            "Display placement is the single biggest driver of incremental "
            "volume in Categories C and D. A display can lift units 30-40%."
        ),
        "confidence": 0.90,
        "recency": "2025-10-20",
        "domain": ["distribution"],
        "basis": "analysis",
        "ground_truth_alignment": "correct",
        "related_effect": None,
    },
    {
        "belief_id": "EXP-03",
        "statement": (
            "Cross-regional price gaps above 12% create grey-market "
            "arbitrage. We've seen distributors re-routing stock."
        ),
        "confidence": 0.80,
        "recency": "2025-09-05",
        "domain": ["pricing"],
        "basis": "experience",
        "ground_truth_alignment": "correct",
        "related_effect": None,
    },
    {
        "belief_id": "EXP-04",
        "statement": (
            "Low-velocity SKUs in Categories C and D are eating shelf "
            "space without contributing meaningful revenue."
        ),
        "confidence": 0.75,
        "recency": "2025-12-01",
        "domain": ["assortment", "distribution"],
        "basis": "analysis",
        "ground_truth_alignment": "correct",
        "related_effect": "GT-2",
    },
    {
        "belief_id": "EXP-05",
        "statement": (
            "Consumers are increasingly trading up to larger pack sizes "
            "for better per-unit value."
        ),
        "confidence": 0.70,
        "recency": "2025-08-18",
        "domain": ["pack_price"],
        "basis": "analysis",
        "ground_truth_alignment": "correct",
        "related_effect": "GT-3",
    },
    {
        "belief_id": "EXP-06",
        "statement": (
            "Category A has a large loyal customer base that buys "
            "regardless of price within a reasonable band."
        ),
        "confidence": 0.88,
        "recency": "2025-11-28",
        "domain": ["pricing", "promotion"],
        "basis": "experience",
        "ground_truth_alignment": "correct",
        "related_effect": "GT-1",
    },
    {
        "belief_id": "EXP-07",
        "statement": (
            "Shelf facings have diminishing returns — going from 1 to 3 "
            "facings is impactful, but 5 to 8 barely moves the needle."
        ),
        "confidence": 0.72,
        "recency": "2025-07-10",
        "domain": ["distribution"],
        "basis": "analysis",
        "ground_truth_alignment": "correct",
        "related_effect": None,
    },

    # ===== OUTDATED / WRONG beliefs =====
    {
        "belief_id": "EXP-08",
        "statement": (
            "Deep promotions (30%+) on Category A always generate positive "
            "ROI. This has been our most reliable promo strategy for years."
        ),
        "confidence": 0.92,
        "recency": "2024-06-15",
        "domain": ["promotion", "pricing"],
        "basis": "experience",
        "ground_truth_alignment": "wrong",
        "related_effect": "GT-1",
    },
    {
        "belief_id": "EXP-09",
        "statement": (
            "Category B is in structural decline. We should reduce "
            "investment and reallocate shelf space to Category C."
        ),
        "confidence": 0.65,
        "recency": "2025-04-22",
        "domain": ["assortment", "distribution"],
        "basis": "intuition",
        "ground_truth_alignment": "wrong",
        "related_effect": "GT-4",
    },
    {
        "belief_id": "EXP-10",
        "statement": (
            "The 12-pack introduction in Category D has been a home run. "
            "Volume is up 15% and we should expand to other categories."
        ),
        "confidence": 0.78,
        "recency": "2025-10-30",
        "domain": ["pack_price"],
        "basis": "analysis",
        "ground_truth_alignment": "wrong",
        "related_effect": "GT-3",
    },
    {
        "belief_id": "EXP-11",
        "statement": (
            "Price elasticity is roughly uniform across regions. "
            "We can use a single national pricing strategy."
        ),
        "confidence": 0.60,
        "recency": "2024-02-10",
        "domain": ["pricing"],
        "basis": "intuition",
        "ground_truth_alignment": "wrong",
        "related_effect": None,
    },
    {
        "belief_id": "EXP-12",
        "statement": (
            "Removing any SKU from the assortment always hurts revenue. "
            "Every SKU serves a purpose."
        ),
        "confidence": 0.55,
        "recency": "2024-09-12",
        "domain": ["assortment"],
        "basis": "intuition",
        "ground_truth_alignment": "wrong",
        "related_effect": "GT-2",
    },

    # ===== CONDITIONALLY CORRECT beliefs =====
    {
        "belief_id": "EXP-13",
        "statement": (
            "Premium segment is under-priced relative to market. We "
            "should pursue aggressive price increases on premium SKUs."
        ),
        "confidence": 0.82,
        "recency": "2025-12-05",
        "domain": ["pricing"],
        "basis": "analysis",
        "ground_truth_alignment": "conditional",
        "related_effect": "GT-5",
    },
    {
        "belief_id": "EXP-14",
        "statement": (
            "Reducing assortment breadth can improve profitability, "
            "but only if freed shelf space is actively reallocated."
        ),
        "confidence": 0.76,
        "recency": "2025-11-10",
        "domain": ["assortment", "distribution"],
        "basis": "experience",
        "ground_truth_alignment": "conditional",
        "related_effect": "GT-2",
    },
    {
        "belief_id": "EXP-15",
        "statement": (
            "Promotional lift in Category A is real, but I suspect we're "
            "subsidising customers who would buy anyway."
        ),
        "confidence": 0.58,
        "recency": "2025-10-01",
        "domain": ["promotion", "pricing"],
        "basis": "intuition",
        "ground_truth_alignment": "conditional",
        "related_effect": "GT-1",
    },
    {
        "belief_id": "EXP-16",
        "statement": (
            "The 12-pack is gaining traction but may be pulling from our "
            "6-pack. We need to watch the cannibalisation numbers."
        ),
        "confidence": 0.68,
        "recency": "2025-11-20",
        "domain": ["pack_price", "pricing"],
        "basis": "analysis",
        "ground_truth_alignment": "conditional",
        "related_effect": "GT-3",
    },
    {
        "belief_id": "EXP-17",
        "statement": (
            "Maintaining Category B shelf share is contractually required, "
            "but within that constraint we should shift the mix towards "
            "higher-margin B SKUs."
        ),
        "confidence": 0.80,
        "recency": "2025-12-10",
        "domain": ["assortment", "pricing", "distribution"],
        "basis": "experience",
        "ground_truth_alignment": "conditional",
        "related_effect": "GT-4",
    },
    {
        "belief_id": "EXP-18",
        "statement": (
            "We can be more aggressive on pricing for a handful of "
            "premium SKUs with high margin headroom, but the rest are "
            "already near the floor."
        ),
        "confidence": 0.74,
        "recency": "2025-12-08",
        "domain": ["pricing"],
        "basis": "analysis",
        "ground_truth_alignment": "conditional",
        "related_effect": "GT-5",
    },
]


# ---------------------------------------------------------------------------
# Generator function
# ---------------------------------------------------------------------------

def generate_expert_beliefs() -> List[Dict[str, Any]]:
    """Return the list of expert belief dicts.

    Note: ``ground_truth_alignment`` and ``related_effect`` are metadata for
    scoring and are stripped when the beliefs are presented to agents.
    """
    return [dict(b) for b in _EXPERT_BELIEFS]


def generate_agent_facing_beliefs() -> List[Dict[str, Any]]:
    """Return beliefs with scoring metadata removed (agent-facing view)."""
    keep = ("belief_id", "statement", "confidence", "recency", "domain", "basis")
    return [{k: b[k] for k in keep} for b in _EXPERT_BELIEFS]


def write_expert_beliefs(output_dir: str, include_metadata: bool = False) -> str:
    """Write expert_beliefs.json and return the file path."""
    os.makedirs(output_dir, exist_ok=True)
    path = os.path.join(output_dir, "expert_beliefs.json")
    beliefs = generate_expert_beliefs() if include_metadata else generate_agent_facing_beliefs()
    with open(path, "w") as fh:
        json.dump(beliefs, fh, indent=2)
    return path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "data"
    p = write_expert_beliefs(out)
    print(f"Wrote {len(_EXPERT_BELIEFS)} expert beliefs to {p}")
