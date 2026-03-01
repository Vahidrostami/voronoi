"""Encode policy rules into ConstraintVector objects.

Transforms structured policy rule dicts into reasoning-ready constraint
representations with:
  * Parsed fields: lever, direction, bound, hardness, scope, interactions
  * Feasible region boundaries per lever
  * Constraint conflict detection (mutually exclusive rules)

Only depends on stdlib + numpy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..core.types import ConstraintHardness, ConstraintVector, LeverName
from ..core.config import Config


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encode_policy(rule: Dict[str, Any]) -> ConstraintVector:
    """Encode a single policy rule dict into a :class:`ConstraintVector`.

    Expected *rule* keys (matching ``data/policies.json`` schema):
        rule_id, type ("hard"|"soft"), lever, scope, threshold, rationale
    Optional: direction, interactions.
    """
    hardness = (
        ConstraintHardness.HARD if rule.get("type") == "hard"
        else ConstraintHardness.SOFT
    )

    # Extract a scalar bound from the threshold dict (first numeric value)
    threshold = rule.get("threshold", {})
    bound = _extract_bound(threshold)
    direction = rule.get("direction") or _infer_direction(threshold)

    # Infer interactions from scope (levers that share scope overlap)
    interactions = rule.get("interactions", [])

    return ConstraintVector(
        rule_id=str(rule.get("rule_id", "")),
        lever=str(rule.get("lever", "")),
        direction=direction,
        bound=bound,
        hardness=hardness,
        scope=rule.get("scope", {}),
        interactions=interactions,
        rationale=str(rule.get("rationale", "")),
        metadata={
            "threshold_raw": threshold,
        },
    )


def encode_policies(
    rules: Sequence[Dict[str, Any]],
) -> List[ConstraintVector]:
    """Encode a list of policy rules into ConstraintVectors."""
    return [encode_policy(r) for r in rules]


def compute_feasible_region(
    constraints: Sequence[ConstraintVector],
    lever: str,
    *,
    global_min: float = 0.0,
    global_max: float = 1.0,
) -> Dict[str, Any]:
    """Compute the feasible region boundaries for a single lever.

    Returns a dict with ``lower``, ``upper``, ``hard_lower``,
    ``hard_upper``, and list of ``binding_constraints``.
    """
    lower = global_min
    upper = global_max
    hard_lower = global_min
    hard_upper = global_max
    binding: List[str] = []

    for cv in constraints:
        if cv.lever != lever:
            continue

        if cv.direction in (">=", "min"):
            if cv.bound > lower:
                lower = cv.bound
                binding.append(cv.rule_id)
            if cv.hardness == ConstraintHardness.HARD and cv.bound > hard_lower:
                hard_lower = cv.bound
        elif cv.direction in ("<=", "max"):
            if cv.bound < upper:
                upper = cv.bound
                binding.append(cv.rule_id)
            if cv.hardness == ConstraintHardness.HARD and cv.bound < hard_upper:
                hard_upper = cv.bound

    return {
        "lever": lever,
        "lower": lower,
        "upper": upper,
        "hard_lower": hard_lower,
        "hard_upper": hard_upper,
        "binding_constraints": binding,
        "feasible": lower <= upper,
    }


def detect_conflicts(
    constraints: Sequence[ConstraintVector],
) -> List[Dict[str, Any]]:
    """Identify pairwise conflicts between constraints.

    A conflict exists when two constraints on the same lever and scope
    create an infeasible region (lower bound > upper bound), or when
    directions are contradictory.
    """
    conflicts: List[Dict[str, Any]] = []

    # Group by lever
    by_lever: Dict[str, List[ConstraintVector]] = {}
    for cv in constraints:
        by_lever.setdefault(cv.lever, []).append(cv)

    for lever, cvs in by_lever.items():
        lower_bounds: List[ConstraintVector] = []
        upper_bounds: List[ConstraintVector] = []

        for cv in cvs:
            if cv.direction in (">=", "min"):
                lower_bounds.append(cv)
            elif cv.direction in ("<=", "max"):
                upper_bounds.append(cv)

        # Check for infeasible intersections
        for lb in lower_bounds:
            for ub in upper_bounds:
                if lb.bound > ub.bound:
                    severity = (
                        "hard" if (
                            lb.hardness == ConstraintHardness.HARD
                            and ub.hardness == ConstraintHardness.HARD
                        ) else "soft"
                    )
                    conflicts.append({
                        "type": "infeasible_region",
                        "lever": lever,
                        "lower_constraint": lb.rule_id,
                        "upper_constraint": ub.rule_id,
                        "lower_bound": lb.bound,
                        "upper_bound": ub.bound,
                        "severity": severity,
                        "scopes_overlap": _scopes_overlap(lb.scope, ub.scope),
                    })

    # Check for interaction conflicts across levers
    for i, cv_a in enumerate(constraints):
        for cv_b in constraints[i + 1:]:
            if cv_a.lever != cv_b.lever and cv_b.lever in cv_a.interactions:
                if _has_direction_conflict(cv_a, cv_b):
                    conflicts.append({
                        "type": "interaction_conflict",
                        "constraint_a": cv_a.rule_id,
                        "constraint_b": cv_b.rule_id,
                        "lever_a": cv_a.lever,
                        "lever_b": cv_b.lever,
                    })

    return conflicts


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _extract_bound(threshold: Dict[str, Any]) -> float:
    """Extract the primary numeric bound from a threshold dict."""
    if not threshold:
        return 0.0
    for key in ("min_margin_pct", "max_promo_depth_pct",
                "max_promo_events_per_quarter", "min_shelf_share_pct",
                "min_facings", "max_per_unit_price_gap_pct",
                "max_cross_region_price_gap_pct",
                "max_simultaneous_promo_skus_pct",
                "max_total_facings", "min_price", "max_price",
                "min_skus_per_tier", "min_active_skus"):
        if key in threshold:
            return float(threshold[key])
    # Fallback: first numeric value
    for v in threshold.values():
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    return 0.0


def _infer_direction(threshold: Dict[str, Any]) -> str:
    """Infer constraint direction from threshold key names."""
    for key in threshold:
        if key.startswith("min"):
            return ">="
        if key.startswith("max"):
            return "<="
    return ">="


def _scopes_overlap(scope_a: Dict[str, Any], scope_b: Dict[str, Any]) -> bool:
    """Check if two scope dicts overlap."""
    if not scope_a or not scope_b:
        return True  # absence of scope means global

    level_a = scope_a.get("level", "")
    level_b = scope_b.get("level", "")
    if level_a != level_b:
        return False

    vals_a = scope_a.get("values", "all")
    vals_b = scope_b.get("values", "all")
    if vals_a == "all" or vals_b == "all":
        return True
    if isinstance(vals_a, list) and isinstance(vals_b, list):
        return bool(set(vals_a) & set(vals_b))
    return True


def _has_direction_conflict(
    cv_a: ConstraintVector, cv_b: ConstraintVector,
) -> bool:
    """Check for direction conflict between two interacting constraints."""
    # Opposing min/max on related levers can indicate tension
    if cv_a.direction in (">=", "min") and cv_b.direction in ("<=", "max"):
        return True
    if cv_a.direction in ("<=", "max") and cv_b.direction in (">=", "min"):
        return True
    return False
