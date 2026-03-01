"""Constraint diagnostic agent.

Maps the feasible region from encoded ConstraintVectors. Identifies
binding constraints, slack variables, and constraint-constraint
conflicts. Prunes infeasible combinations from the candidate space.

Only depends on stdlib + numpy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from ..core.config import Config
from ..core.types import (
    ConstraintHardness,
    ConstraintVector,
    Direction,
    EvidencePacket,
    LeverName,
)
from ..encoding.constraint_vector import compute_feasible_region, detect_conflicts


# Lever names and their default global ranges
_LEVER_RANGES: Dict[str, tuple] = {
    "pricing": (0.50, 8.00),
    "promotion": (0.0, 0.50),
    "distribution": (0.0, 1.0),
    "assortment": (0.0, 1.0),
    "pack_price": (0.0, 1.0),
}


class ConstraintAgent:
    """Diagnostic agent for constraint analysis and feasible region mapping."""

    AGENT_ID = "constraint_agent"

    def __init__(self, config: Config, encoded_knowledge: Dict[str, Any]) -> None:
        self.config = config
        self.encoded_knowledge = encoded_knowledge
        self._evidence: List[EvidencePacket] = []
        self._pruned: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def diagnose(self) -> List[EvidencePacket]:
        """Run constraint diagnostic, return evidence packets."""
        self._evidence = []
        self._pruned = {
            "feasible_regions": {},
            "binding_constraints": [],
            "infeasible_combinations": [],
            "constraint_conflicts": [],
            "slack_analysis": [],
        }

        constraints = self._get_constraints()
        if not constraints:
            return self._evidence

        self._map_feasible_regions(constraints)
        self._detect_constraint_conflicts(constraints)
        self._analyze_binding_and_slack(constraints)
        self._identify_infeasible_combinations(constraints)

        return self._evidence

    def get_pruned_space(self) -> Dict[str, Any]:
        """Return the reduced candidate space."""
        if not self._evidence:
            self.diagnose()
        return self._pruned

    # ------------------------------------------------------------------
    # Internal analysis methods
    # ------------------------------------------------------------------

    def _get_constraints(self) -> List[ConstraintVector]:
        """Extract ConstraintVector objects from encoded knowledge."""
        raw = self.encoded_knowledge.get("policy", [])
        result = []
        for item in raw:
            if isinstance(item, ConstraintVector):
                result.append(item)
            elif isinstance(item, dict):
                result.append(ConstraintVector.from_dict(item))
        return result

    def _map_feasible_regions(self, constraints: List[ConstraintVector]) -> None:
        """Compute feasible region for each lever."""
        levers_seen = set()
        for cv in constraints:
            levers_seen.add(cv.lever)

        for lever in levers_seen:
            global_min, global_max = _LEVER_RANGES.get(lever, (0.0, 1.0))
            region = compute_feasible_region(
                constraints, lever,
                global_min=global_min, global_max=global_max,
            )

            self._pruned["feasible_regions"][lever] = region

            # Emit evidence about feasibility
            if region["feasible"]:
                range_width = region["upper"] - region["lower"]
                total_width = global_max - global_min
                utilization = range_width / total_width if total_width > 0 else 0.0

                if utilization < 0.3:
                    # Heavily constrained lever
                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever=lever,
                        direction=Direction.MAINTAIN,
                        magnitude=utilization,
                        confidence=0.95,
                        mechanism=(
                            f"Lever '{lever}' is heavily constrained: "
                            f"feasible range [{region['lower']:.3f}, "
                            f"{region['upper']:.3f}] uses only "
                            f"{utilization:.0%} of total range. "
                            f"Limited room for optimization."
                        ),
                        source_types=["policy"],
                        data={
                            "lever": lever,
                            "feasible_lower": region["lower"],
                            "feasible_upper": region["upper"],
                            "utilization": utilization,
                            "binding_constraints": region["binding_constraints"],
                            "analysis_type": "feasible_region",
                        },
                    ))
                elif region["binding_constraints"]:
                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever=lever,
                        direction=Direction.MAINTAIN,
                        magnitude=utilization,
                        confidence=0.9,
                        mechanism=(
                            f"Lever '{lever}' has binding constraints: "
                            f"{', '.join(region['binding_constraints'])}. "
                            f"Feasible range: [{region['lower']:.3f}, "
                            f"{region['upper']:.3f}] ({utilization:.0%} utilization)."
                        ),
                        source_types=["policy"],
                        data={
                            "lever": lever,
                            "feasible_lower": region["lower"],
                            "feasible_upper": region["upper"],
                            "utilization": utilization,
                            "binding_constraints": region["binding_constraints"],
                            "analysis_type": "feasible_region",
                        },
                    ))
            else:
                # Infeasible lever
                self._evidence.append(EvidencePacket(
                    agent_id=self.AGENT_ID,
                    lever=lever,
                    direction=Direction.MAINTAIN,
                    magnitude=0.0,
                    confidence=1.0,
                    mechanism=(
                        f"Lever '{lever}' has INFEASIBLE region: "
                        f"lower bound ({region['lower']:.3f}) > "
                        f"upper bound ({region['upper']:.3f}). "
                        f"Conflicting constraints make this lever unactionable."
                    ),
                    source_types=["policy"],
                    data={
                        "lever": lever,
                        "lower": region["lower"],
                        "upper": region["upper"],
                        "analysis_type": "infeasible_lever",
                    },
                ))
                self._pruned["infeasible_combinations"].append({
                    "lever": lever,
                    "reason": "conflicting constraints create empty feasible region",
                })

    def _detect_constraint_conflicts(
        self, constraints: List[ConstraintVector],
    ) -> None:
        """Detect pairwise conflicts between constraints."""
        conflicts = detect_conflicts(constraints)

        for conflict in conflicts:
            c_type = conflict.get("type", "unknown")
            lever = conflict.get("lever", "")

            if c_type == "infeasible_region":
                severity = conflict.get("severity", "soft")
                self._evidence.append(EvidencePacket(
                    agent_id=self.AGENT_ID,
                    lever=lever,
                    direction=Direction.MAINTAIN,
                    magnitude=abs(conflict.get("lower_bound", 0) - conflict.get("upper_bound", 0)),
                    confidence=1.0 if severity == "hard" else 0.8,
                    mechanism=(
                        f"Constraint conflict on '{lever}': "
                        f"{conflict.get('lower_constraint')} (≥{conflict.get('lower_bound', 0):.3f}) "
                        f"vs {conflict.get('upper_constraint')} (≤{conflict.get('upper_bound', 0):.3f}). "
                        f"Severity: {severity}."
                    ),
                    source_types=["policy"],
                    data={
                        "conflict": conflict,
                        "analysis_type": "constraint_conflict",
                    },
                ))
            elif c_type == "interaction_conflict":
                self._evidence.append(EvidencePacket(
                    agent_id=self.AGENT_ID,
                    lever=conflict.get("lever_a", ""),
                    related_levers=[conflict.get("lever_b", "")],
                    direction=Direction.MAINTAIN,
                    magnitude=0.5,
                    confidence=0.75,
                    mechanism=(
                        f"Cross-lever constraint interaction: "
                        f"{conflict.get('constraint_a')} on "
                        f"'{conflict.get('lever_a')}' interacts with "
                        f"{conflict.get('constraint_b')} on "
                        f"'{conflict.get('lever_b')}'."
                    ),
                    source_types=["policy"],
                    data={
                        "conflict": conflict,
                        "analysis_type": "interaction_constraint_conflict",
                    },
                ))

            self._pruned["constraint_conflicts"].append(conflict)

    def _analyze_binding_and_slack(
        self, constraints: List[ConstraintVector],
    ) -> None:
        """Analyze binding constraints and slack variables."""
        tolerance = self.config.constraint_slack_tolerance

        for cv in constraints:
            global_min, global_max = _LEVER_RANGES.get(cv.lever, (0.0, 1.0))
            region = compute_feasible_region(
                constraints, cv.lever,
                global_min=global_min, global_max=global_max,
            )

            if not region["feasible"]:
                continue

            # Check if this constraint is binding (slack ≈ 0)
            if cv.direction in (">=", "min"):
                slack = region["lower"] - cv.bound
                is_binding = abs(slack) <= tolerance
            elif cv.direction in ("<=", "max"):
                slack = cv.bound - region["upper"]
                is_binding = abs(slack) <= tolerance
            else:
                slack = float("inf")
                is_binding = False

            if is_binding:
                self._pruned["binding_constraints"].append({
                    "rule_id": cv.rule_id,
                    "lever": cv.lever,
                    "bound": cv.bound,
                    "direction": cv.direction,
                    "hardness": cv.hardness.value,
                    "slack": float(slack),
                })

                if cv.hardness == ConstraintHardness.HARD:
                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever=cv.lever,
                        direction=Direction.MAINTAIN,
                        magnitude=cv.bound,
                        confidence=0.95,
                        mechanism=(
                            f"HARD binding constraint {cv.rule_id} on "
                            f"'{cv.lever}': {cv.direction} {cv.bound:.3f}. "
                            f"Slack={slack:.4f}. {cv.rationale[:60]}"
                        ),
                        source_types=["policy"],
                        data={
                            "rule_id": cv.rule_id,
                            "lever": cv.lever,
                            "bound": cv.bound,
                            "hardness": "hard",
                            "slack": float(slack),
                            "rationale": cv.rationale,
                            "analysis_type": "binding_constraint",
                        },
                    ))
            else:
                self._pruned["slack_analysis"].append({
                    "rule_id": cv.rule_id,
                    "lever": cv.lever,
                    "bound": cv.bound,
                    "direction": cv.direction,
                    "hardness": cv.hardness.value,
                    "slack": float(slack),
                })

    def _identify_infeasible_combinations(
        self, constraints: List[ConstraintVector],
    ) -> None:
        """Identify lever combinations that are infeasible under constraints.

        Checks scope-specific constraints to find SKU/category/region
        combinations where the constraint space collapses.
        """
        # Group constraints by scope
        by_scope: Dict[str, List[ConstraintVector]] = {}
        for cv in constraints:
            scope_key = self._scope_key(cv.scope)
            by_scope.setdefault(scope_key, []).append(cv)

        for scope_key, scope_constraints in by_scope.items():
            # Check each lever within this scope
            levers_in_scope = set(cv.lever for cv in scope_constraints)
            for lever in levers_in_scope:
                lever_cvs = [cv for cv in scope_constraints if cv.lever == lever]
                global_min, global_max = _LEVER_RANGES.get(lever, (0.0, 1.0))
                region = compute_feasible_region(
                    lever_cvs, lever,
                    global_min=global_min, global_max=global_max,
                )

                if not region["feasible"]:
                    self._pruned["infeasible_combinations"].append({
                        "scope": scope_key,
                        "lever": lever,
                        "constraints": [cv.rule_id for cv in lever_cvs],
                        "reason": (
                            f"Infeasible in scope '{scope_key}': "
                            f"lower={region['lower']:.3f} > upper={region['upper']:.3f}"
                        ),
                    })

    @staticmethod
    def _scope_key(scope: Dict[str, Any]) -> str:
        """Create a hashable key from a scope dict."""
        level = scope.get("level", "global")
        values = scope.get("values", "all")
        if isinstance(values, list):
            return f"{level}:{','.join(sorted(str(v) for v in values))}"
        return f"{level}:{values}"
