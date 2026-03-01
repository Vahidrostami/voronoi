"""Multi-dimensional quality gate for candidate interventions.

Scores each intervention on 5 dimensions:
  * evidence_density  (0–1): how many independent sources support it
  * constraint_alignment (0–1): hard-constraint veto
  * actionability    (0–1): are lever+direction+magnitude+scope specified?
  * testability      (0–1): is it A/B testable?
  * novelty          (0–1): penalise obvious single-lever findings

Composite = weighted sum with hard-constraint veto.
Filters to top-K (default K=10).

Only depends on stdlib + numpy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from ..core.config import Config
from ..core.types import (
    ConstraintVector,
    Direction,
    Intervention,
    QualityScore,
)


# Names of the 5 diagnostic agents
_ALL_AGENTS = frozenset({
    "elasticity_agent",
    "interaction_agent",
    "constraint_agent",
    "temporal_agent",
    "portfolio_agent",
})


class QualityGate:
    """Multi-dimensional quality gate for ranking interventions."""

    def __init__(
        self,
        config: Config,
        constraints: Optional[List[ConstraintVector]] = None,
    ) -> None:
        self.config = config
        self.constraints = constraints or []
        self.top_k = config.quality_gate_top_k
        self.weights = config.quality_weights()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_and_filter(
        self,
        interventions: List[Intervention],
        *,
        top_k: Optional[int] = None,
    ) -> List[Intervention]:
        """Score all interventions and return the top-K.

        Each intervention receives a ``QualityScore`` attached to its
        ``.quality`` field.  Hard-constraint violations veto to composite=0.

        Parameters
        ----------
        interventions : list[Intervention]
            Candidate interventions from the synthesis layer.
        top_k : int, optional
            Override the default K from config.

        Returns
        -------
        list[Intervention]
            Scored and ranked interventions, length ≤ *top_k*.
        """
        k = top_k if top_k is not None else self.top_k

        for iv in interventions:
            iv.quality = self._score(iv)

        # Sort by composite descending, then by confidence as tiebreaker
        interventions.sort(
            key=lambda iv: (
                iv.quality.composite if iv.quality else 0.0,
                iv.confidence,
            ),
            reverse=True,
        )

        return interventions[:k]

    def score(self, iv: Intervention) -> QualityScore:
        """Score a single intervention without filtering."""
        return self._score(iv)

    # ------------------------------------------------------------------
    # Internal scoring
    # ------------------------------------------------------------------

    def _score(self, iv: Intervention) -> QualityScore:
        """Compute the multi-dimensional quality score for *iv*."""
        ed = self._evidence_density(iv)
        ca = self._constraint_alignment(iv)
        ac = self._actionability(iv)
        te = self._testability(iv)
        nv = self._novelty(iv)

        hard_violation = ca < 0.0  # negative signals a hard violation

        qs = QualityScore(
            evidence_density=ed,
            constraint_alignment=max(ca, 0.0),
            actionability=ac,
            testability=te,
            novelty=nv,
            hard_constraint_violation=hard_violation,
            details={
                "n_sources": self._count_sources(iv),
                "n_agents": self._count_agents(iv),
                "constraint_issues": self._constraint_details(iv),
            },
        )
        qs.compute_composite(self.weights)
        return qs

    # ------------------------------------------------------------------
    # Dimension 1 — Evidence density
    # ------------------------------------------------------------------

    def _evidence_density(self, iv: Intervention) -> float:
        """Score based on how many independent agent sources support this.

        0 sources → 0.0 ;  5 sources → 1.0 ;  linear interpolation.
        """
        n_agents = self._count_agents(iv)
        n_sources = self._count_sources(iv)
        # Agents provide independent analytical dimensions (max 5)
        agent_score = min(n_agents / 3.0, 1.0)  # 3+ agents = full score
        # Extra credit for multiple source *types* (quantitative, policy, expert)
        source_bonus = min(n_sources / 3.0, 1.0) * 0.2
        return min(agent_score + source_bonus, 1.0)

    # ------------------------------------------------------------------
    # Dimension 2 — Constraint alignment
    # ------------------------------------------------------------------

    def _constraint_alignment(self, iv: Intervention) -> float:
        """Check if the intervention violates any constraints.

        Returns -1.0 for hard-constraint violation (veto),
        0.5 for soft-constraint violation, 1.0 for no violation.
        """
        if not self.constraints:
            # No constraints loaded — assume aligned
            return 1.0

        hard_violated = False
        soft_violations = 0

        for cv in self.constraints:
            if not self._constraint_applies(cv, iv):
                continue

            violated = self._check_violation(cv, iv)
            if violated:
                if cv.hardness.value == "hard":
                    hard_violated = True
                    break
                else:
                    soft_violations += 1

        if hard_violated:
            return -1.0  # Veto signal

        if soft_violations > 0:
            # Penalise proportionally but don't veto
            return max(1.0 - 0.2 * soft_violations, 0.2)

        return 1.0

    def _constraint_applies(self, cv: ConstraintVector, iv: Intervention) -> bool:
        """Check if a constraint applies to this intervention's lever/scope."""
        # Match by lever name
        cv_lever = cv.lever.lower().strip()
        iv_lever = iv.lever.lower().strip()

        # Direct match or partial match (e.g., "pricing" in "pricing+promotion")
        if cv_lever not in iv_lever and iv_lever not in cv_lever:
            return False

        # Scope matching — if constraint has scope, check overlap
        if cv.scope:
            iv_cats = set(iv.scope.get("categories", []))
            cv_cats = set()
            if "category" in cv.scope:
                cv_cats.add(str(cv.scope["category"]))
            if "categories" in cv.scope:
                cv_cats.update(str(c) for c in cv.scope["categories"])

            if iv_cats and cv_cats and not iv_cats & cv_cats:
                return False

        return True

    def _check_violation(self, cv: ConstraintVector, iv: Intervention) -> bool:
        """Check if an intervention violates a specific constraint."""
        # Direction-based violation check
        direction_str = cv.direction.strip()
        bound = cv.bound

        if not direction_str or bound == 0.0:
            return False

        # For constraints like ">= 0.25" (min margin), check if the
        # intervention would push below the bound
        if ">=" in direction_str:
            # Intervention decreases → check if it drops below bound
            if iv.direction == Direction.DECREASE and iv.magnitude > 0:
                # Check metadata for specific threshold info
                margin_data = iv.metadata.get("margin_headroom")
                if margin_data is not None and margin_data < bound:
                    return True
                # Conservative: flag large decreases on constrained levers
                if iv.magnitude > 0.15:
                    return True
        elif "<=" in direction_str:
            if iv.direction == Direction.INCREASE and iv.magnitude > 0:
                if iv.magnitude > bound:
                    return True

        return False

    def _constraint_details(self, iv: Intervention) -> List[Dict[str, Any]]:
        """Return details about constraint interactions for this intervention."""
        issues: List[Dict[str, Any]] = []
        for cv in self.constraints:
            if not self._constraint_applies(cv, iv):
                continue
            violated = self._check_violation(cv, iv)
            if violated:
                issues.append({
                    "rule_id": cv.rule_id,
                    "hardness": cv.hardness.value,
                    "lever": cv.lever,
                    "direction": cv.direction,
                    "bound": cv.bound,
                    "violated": True,
                })
        return issues

    # ------------------------------------------------------------------
    # Dimension 3 — Actionability
    # ------------------------------------------------------------------

    def _actionability(self, iv: Intervention) -> float:
        """Score how actionable the intervention is.

        Full marks require: lever + direction + magnitude + scope all specified.
        """
        score = 0.0

        # Lever specified and not "unknown"
        if iv.lever and iv.lever != "unknown":
            score += 0.25

        # Direction specified and not MAINTAIN (MAINTAIN = no action)
        if iv.direction and iv.direction != Direction.MAINTAIN:
            score += 0.25

        # Magnitude specified and non-zero
        if iv.magnitude and abs(iv.magnitude) > 1e-6:
            score += 0.25

        # Scope specified (at least one of categories/regions/sku_ids)
        if iv.scope and any(iv.scope.values()):
            score += 0.25

        return score

    # ------------------------------------------------------------------
    # Dimension 4 — Testability
    # ------------------------------------------------------------------

    def _testability(self, iv: Intervention) -> float:
        """Score whether the intervention can be A/B tested.

        Higher if: scope is narrow (not "all stores"), direction is clear,
        magnitude is reasonable, mechanism is stated.
        """
        score = 0.0

        # Clear direction → testable
        if iv.direction in (Direction.INCREASE, Direction.DECREASE):
            score += 0.25

        # Reasonable magnitude (neither trivial nor extreme)
        if 0.01 <= abs(iv.magnitude) <= 0.5:
            score += 0.25

        # Scoped (not global) → can run a controlled test
        if iv.scope:
            scope_fields = sum(1 for v in iv.scope.values() if v)
            if scope_fields >= 1:
                score += 0.25

        # Mechanism stated → measurable outcome
        if iv.mechanism and iv.mechanism != "Unspecified mechanism":
            score += 0.25

        return score

    # ------------------------------------------------------------------
    # Dimension 5 — Novelty
    # ------------------------------------------------------------------

    def _novelty(self, iv: Intervention) -> float:
        """Score how non-obvious the finding is.

        Penalise interventions that any single-lever analysis would find.
        Reward multi-lever, cross-source, and interaction-based findings.
        """
        roles = iv.metadata.get("agent_roles", [])
        n_roles = len(roles)
        chain_strength = iv.metadata.get("chain_strength", 0.0)

        # Single agent → low novelty (any single-lever analysis finds this)
        if n_roles <= 1:
            return 0.2

        # Multi-agent → moderate novelty
        novelty = min(n_roles / 4.0, 0.8)

        # Cross-lever intervention → bonus
        if "+" in iv.lever or len(iv.metadata.get("related_levers", [])) > 0:
            novelty = min(novelty + 0.2, 1.0)

        # Strong causal chain → bonus
        if chain_strength >= 0.7:
            novelty = min(novelty + 0.15, 1.0)

        # Interaction agent involved → bonus (non-obvious by definition)
        if "interaction" in roles:
            novelty = min(novelty + 0.1, 1.0)

        return novelty

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _count_agents(iv: Intervention) -> int:
        """Count distinct diagnostic agents in the evidence trail."""
        agents = set()
        for entry in iv.evidence_trail:
            agent_id = entry.split(":")[0] if ":" in entry else entry
            agents.add(agent_id)
        # Also check metadata
        agents.update(iv.metadata.get("agent_roles", []))
        return len(agents)

    @staticmethod
    def _count_sources(iv: Intervention) -> int:
        """Count distinct knowledge source *types* referenced."""
        agent_to_source = {
            "elasticity_agent": "quantitative",
            "interaction_agent": "quantitative",
            "constraint_agent": "policy",
            "temporal_agent": "quantitative",
            "portfolio_agent": "quantitative",
            "sensitivity": "quantitative",
            "interaction": "quantitative",
            "constraint": "policy",
            "temporal": "quantitative",
            "portfolio": "quantitative",
        }
        sources = set()
        for entry in iv.evidence_trail:
            agent_id = entry.split(":")[0] if ":" in entry else entry
            src = agent_to_source.get(agent_id, "expert")
            sources.add(src)
        for role in iv.metadata.get("agent_roles", []):
            src = agent_to_source.get(role, "expert")
            sources.add(src)
        return len(sources)
