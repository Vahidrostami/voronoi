"""Lever coupling model — weighted graph of pairwise interactions.

Models the 5 RGM levers (pricing, promotion, assortment, distribution,
pack_price) and their known coupling strengths.  Provides utilities to
query neighbours, measure interaction strength, and propagate changes
through the coupling graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

import numpy as np

from .types import LeverName


# ---------------------------------------------------------------------------
# Coupling weights  (symmetric, 0 = no coupling, 1 = maximum coupling)
# Source: PROMPT.md ground-truth interaction matrix
# ---------------------------------------------------------------------------

_COUPLING_MATRIX: Dict[Tuple[LeverName, LeverName], float] = {
    # pricing ↔ promotion  (discount depth erodes margin)
    (LeverName.PRICING, LeverName.PROMOTION): 0.85,
    # pricing ↔ assortment  (premium mix affects pricing power)
    (LeverName.PRICING, LeverName.ASSORTMENT): 0.55,
    # pricing ↔ pack_price  (per-unit economics, cannibalization)
    (LeverName.PRICING, LeverName.PACK_PRICE): 0.80,
    # promotion ↔ distribution  (display allocation, lift)
    (LeverName.PROMOTION, LeverName.DISTRIBUTION): 0.65,
    # assortment ↔ distribution  (shelf space allocation)
    (LeverName.ASSORTMENT, LeverName.DISTRIBUTION): 0.70,
    # assortment ↔ pack_price  (portfolio coherence)
    (LeverName.ASSORTMENT, LeverName.PACK_PRICE): 0.45,
    # pricing ↔ distribution  (weaker, through coverage economics)
    (LeverName.PRICING, LeverName.DISTRIBUTION): 0.30,
    # promotion ↔ assortment  (promo mix depends on assortment)
    (LeverName.PROMOTION, LeverName.ASSORTMENT): 0.40,
    # promotion ↔ pack_price  (promo on which pack size?)
    (LeverName.PROMOTION, LeverName.PACK_PRICE): 0.35,
    # distribution ↔ pack_price  (shelf space per pack variant)
    (LeverName.DISTRIBUTION, LeverName.PACK_PRICE): 0.40,
}

# Build symmetric lookup
_WEIGHTS: Dict[Tuple[LeverName, LeverName], float] = {}
for (a, b), w in _COUPLING_MATRIX.items():
    _WEIGHTS[(a, b)] = w
    _WEIGHTS[(b, a)] = w
# Self-coupling = 1.0
for lv in LeverName:
    _WEIGHTS[(lv, lv)] = 1.0


# ---------------------------------------------------------------------------
# Coupling descriptions (for explainability)
# ---------------------------------------------------------------------------

_COUPLING_DESCRIPTIONS: Dict[Tuple[LeverName, LeverName], str] = {
    (LeverName.PRICING, LeverName.PROMOTION):
        "Discount depth directly erodes pricing margin; joint optimisation needed.",
    (LeverName.PRICING, LeverName.ASSORTMENT):
        "Premium-mix skew alters pricing power across the portfolio.",
    (LeverName.PRICING, LeverName.PACK_PRICE):
        "Per-unit economics and cannibalization between pack sizes.",
    (LeverName.PROMOTION, LeverName.DISTRIBUTION):
        "Display allocation amplifies or dampens promotional lift.",
    (LeverName.ASSORTMENT, LeverName.DISTRIBUTION):
        "Removing low-velocity SKUs frees shelf space for top performers.",
    (LeverName.ASSORTMENT, LeverName.PACK_PRICE):
        "Pack variants must cohere with assortment strategy.",
    (LeverName.PRICING, LeverName.DISTRIBUTION):
        "Coverage economics depend on price points.",
    (LeverName.PROMOTION, LeverName.ASSORTMENT):
        "Promotional mix is constrained by available assortment.",
    (LeverName.PROMOTION, LeverName.PACK_PRICE):
        "Which pack size to promote affects unit economics.",
    (LeverName.DISTRIBUTION, LeverName.PACK_PRICE):
        "Shelf space per pack variant is a scarce resource.",
}


# ---------------------------------------------------------------------------
# CouplingGraph class
# ---------------------------------------------------------------------------

@dataclass
class CouplingGraph:
    """Weighted undirected graph of lever couplings.

    Nodes are LeverName values.  Edge weights represent interaction
    strength (0–1).  Supports propagation of changes through the graph.
    """

    weights: Dict[Tuple[LeverName, LeverName], float] = field(
        default_factory=lambda: dict(_WEIGHTS)
    )
    descriptions: Dict[Tuple[LeverName, LeverName], str] = field(
        default_factory=lambda: dict(_COUPLING_DESCRIPTIONS)
    )

    # -- Queries -----------------------------------------------------------

    def levers(self) -> List[LeverName]:
        """Return all lever names."""
        return list(LeverName)

    def get_coupled(self, lever: LeverName) -> List[Tuple[LeverName, float]]:
        """Return (neighbour, weight) pairs for *lever*, sorted by weight desc."""
        pairs = [
            (other, self.weights.get((lever, other), 0.0))
            for other in LeverName
            if other != lever and self.weights.get((lever, other), 0.0) > 0
        ]
        pairs.sort(key=lambda x: x[1], reverse=True)
        return pairs

    def strength(self, a: LeverName, b: LeverName) -> float:
        """Return the coupling weight between two levers (0 if none)."""
        return self.weights.get((a, b), 0.0)

    def description(self, a: LeverName, b: LeverName) -> str:
        """Return a human-readable description of the coupling."""
        key = (a, b) if (a, b) in self.descriptions else (b, a)
        return self.descriptions.get(key, "")

    def adjacency_matrix(self) -> Tuple[List[LeverName], "np.ndarray"]:
        """Return the lever list and the 5×5 adjacency matrix as ndarray."""
        levers = list(LeverName)
        n = len(levers)
        mat = np.zeros((n, n), dtype=np.float64)
        for i, li in enumerate(levers):
            for j, lj in enumerate(levers):
                mat[i, j] = self.weights.get((li, lj), 0.0)
        return levers, mat

    # -- Propagation -------------------------------------------------------

    def propagate(
        self,
        source: LeverName,
        direction: float,
        magnitude: float,
        *,
        damping: float = 0.5,
        threshold: float = 0.01,
    ) -> Dict[LeverName, float]:
        """Propagate a change from *source* through the coupling graph.

        Uses a single-hop weighted propagation:
            impact_j = direction * magnitude * weight(source, j) * damping

        Returns a dict mapping every lever (including source) to its
        estimated impact.  Impacts below *threshold* are zeroed.
        """
        impacts: Dict[LeverName, float] = {source: direction * magnitude}
        for other in LeverName:
            if other == source:
                continue
            w = self.weights.get((source, other), 0.0)
            impact = direction * magnitude * w * damping
            impacts[other] = impact if abs(impact) >= threshold else 0.0
        return impacts

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-friendly dict."""
        edges = []
        seen = set()
        for (a, b), w in self.weights.items():
            key = tuple(sorted([a.value, b.value]))
            if key not in seen and a != b:
                seen.add(key)
                edges.append({
                    "lever_a": a.value,
                    "lever_b": b.value,
                    "weight": w,
                    "description": self.description(a, b),
                })
        return {"levers": [lv.value for lv in LeverName], "edges": edges}


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------

_GRAPH = CouplingGraph()


def get_coupled_levers(lever: LeverName) -> List[Tuple[LeverName, float]]:
    """Return levers coupled with *lever* and their weights."""
    return _GRAPH.get_coupled(lever)


def interaction_strength(lever_a: LeverName, lever_b: LeverName) -> float:
    """Return the interaction weight between two levers."""
    return _GRAPH.strength(lever_a, lever_b)


def propagate_change(
    lever: LeverName,
    direction: float,
    magnitude: float,
    **kwargs: Any,
) -> Dict[LeverName, float]:
    """Propagate a change from *lever* through the coupling graph."""
    return _GRAPH.propagate(lever, direction, magnitude, **kwargs)
