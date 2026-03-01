"""Causal synthesis assembler.

Takes evidence packets from all 5 diagnostic agents and assembles them
into candidate Intervention objects:
  1. Groups evidence by lever + direction.
  2. Identifies causal chains (elasticity signal + interaction + no
     constraint violation = strong candidate).
  3. Produces Intervention objects with full evidence trails.
  4. Merges overlapping interventions.
  5. Resolves conflicts via epistemic hierarchy
     (quantitative > policy > expert, unless confidence override).

Only depends on stdlib + numpy.
"""

from __future__ import annotations

import hashlib
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..core.config import Config
from ..core.types import (
    Direction,
    EvidencePacket,
    Intervention,
)


# ---------------------------------------------------------------------------
# Epistemic hierarchy weights
# ---------------------------------------------------------------------------

_SOURCE_HIERARCHY: Dict[str, float] = {
    "quantitative": 1.0,
    "policy": 0.8,
    "expert": 0.6,
}

# Agent contribution weights for causal-chain strength
_AGENT_ROLE: Dict[str, str] = {
    "elasticity_agent": "sensitivity",
    "interaction_agent": "interaction",
    "constraint_agent": "constraint",
    "temporal_agent": "temporal",
    "portfolio_agent": "portfolio",
}


def _evidence_key(ep: EvidencePacket) -> Tuple[str, str]:
    """Return the (lever, direction) grouping key for an evidence packet."""
    lever = ep.lever or "unknown"
    direction = ep.direction.value if ep.direction else "maintain"
    return (lever, direction)


def _merge_key(iv: Intervention) -> str:
    """Fingerprint for detecting overlapping interventions."""
    scope_str = "|".join(
        f"{k}={v}" for k, v in sorted(iv.scope.items()) if v
    )
    return f"{iv.lever}:{iv.direction.value}:{scope_str}"


def _intervention_id(lever: str, direction: str, idx: int) -> str:
    """Generate a short deterministic id."""
    raw = f"{lever}:{direction}:{idx}"
    return "IV-" + hashlib.md5(raw.encode()).hexdigest()[:8]


# ---------------------------------------------------------------------------
# CausalAssembler
# ---------------------------------------------------------------------------

class CausalAssembler:
    """Synthesises diagnostic evidence into ranked interventions."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.top_k = config.synthesis_top_k

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def assemble(
        self,
        evidence_packets: List[EvidencePacket],
    ) -> List[Intervention]:
        """Run the full synthesis pipeline.

        Parameters
        ----------
        evidence_packets : list[EvidencePacket]
            Evidence from all 5 diagnostic agents.

        Returns
        -------
        list[Intervention]
            Up to ``synthesis_top_k`` ranked interventions.
        """
        if not evidence_packets:
            return []

        # 1. Group evidence by lever + direction
        groups = self._group_evidence(evidence_packets)

        # 2. Build raw interventions from each group
        raw = self._build_interventions(groups)

        # 3. Merge overlapping interventions
        merged = self._merge_overlapping(raw)

        # 4. Resolve conflicts via epistemic hierarchy
        resolved = self._resolve_conflicts(merged)

        # 5. Rank by confidence and return top-K
        resolved.sort(key=lambda iv: iv.confidence, reverse=True)
        return resolved[: self.top_k]

    # ------------------------------------------------------------------
    # Step 1 — group evidence
    # ------------------------------------------------------------------

    def _group_evidence(
        self,
        packets: List[EvidencePacket],
    ) -> Dict[Tuple[str, str], List[EvidencePacket]]:
        """Group evidence packets by (lever, direction)."""
        groups: Dict[Tuple[str, str], List[EvidencePacket]] = defaultdict(list)
        for ep in packets:
            key = _evidence_key(ep)
            groups[key].append(ep)

            # Also index by related levers so multi-lever interventions
            # appear under each participating lever.
            for rl in ep.related_levers:
                alt_key = (rl, ep.direction.value if ep.direction else "maintain")
                groups[alt_key].append(ep)
        return dict(groups)

    # ------------------------------------------------------------------
    # Step 2 — build interventions from evidence groups
    # ------------------------------------------------------------------

    def _build_interventions(
        self,
        groups: Dict[Tuple[str, str], List[EvidencePacket]],
    ) -> List[Intervention]:
        """Convert each evidence group into a candidate Intervention."""
        interventions: List[Intervention] = []
        idx = 0

        for (lever, direction_str), packets in groups.items():
            direction = Direction(direction_str) if direction_str in Direction.__members__.values() else Direction.MAINTAIN

            # Causal chain detection — check which agent roles are present
            agent_roles = set()
            for ep in packets:
                role = _AGENT_ROLE.get(ep.agent_id, ep.agent_id)
                agent_roles.add(role)

            chain_strength = self._causal_chain_strength(packets, agent_roles)

            # Aggregate confidence — weighted by source hierarchy
            confidence = self._aggregate_confidence(packets)

            # Boost confidence if multiple complementary signals exist
            confidence *= chain_strength

            # Build evidence trail
            trail = [
                f"{ep.agent_id}:{ep.mechanism}" for ep in packets if ep.mechanism
            ]

            # Aggregate magnitude (weighted mean by confidence)
            magnitude = self._aggregate_magnitude(packets)

            # Build scope from packet data
            scope = self._aggregate_scope(packets)

            # Build mechanism description
            mechanism = self._synthesize_mechanism(packets, agent_roles)

            iv = Intervention(
                intervention_id=_intervention_id(lever, direction_str, idx),
                lever=lever,
                direction=direction,
                magnitude=magnitude,
                scope=scope,
                mechanism=mechanism,
                evidence_trail=trail,
                confidence=min(confidence, 1.0),
                metadata={
                    "agent_roles": sorted(agent_roles),
                    "n_evidence_packets": len(packets),
                    "chain_strength": chain_strength,
                },
            )
            interventions.append(iv)
            idx += 1

        return interventions

    # ------------------------------------------------------------------
    # Step 3 — merge overlapping interventions
    # ------------------------------------------------------------------

    def _merge_overlapping(
        self,
        interventions: List[Intervention],
    ) -> List[Intervention]:
        """Merge interventions that target the same lever+direction+scope."""
        buckets: Dict[str, List[Intervention]] = defaultdict(list)
        for iv in interventions:
            buckets[_merge_key(iv)].append(iv)

        merged: List[Intervention] = []
        for key, group in buckets.items():
            if len(group) == 1:
                merged.append(group[0])
            else:
                merged.append(self._merge_group(group))
        return merged

    def _merge_group(self, group: List[Intervention]) -> Intervention:
        """Merge a list of overlapping interventions into one."""
        # Pick the one with highest confidence as the base
        group.sort(key=lambda iv: iv.confidence, reverse=True)
        base = group[0]

        # Accumulate evidence trails and boost confidence
        all_trails: List[str] = []
        all_roles: set = set()
        total_packets = 0
        for iv in group:
            all_trails.extend(iv.evidence_trail)
            all_roles.update(iv.metadata.get("agent_roles", []))
            total_packets += iv.metadata.get("n_evidence_packets", 1)

        # Remove duplicate trail entries while preserving order
        seen: set = set()
        unique_trails: List[str] = []
        for t in all_trails:
            if t not in seen:
                seen.add(t)
                unique_trails.append(t)

        # Merged magnitude = confidence-weighted mean
        weights = np.array([iv.confidence for iv in group])
        magnitudes = np.array([iv.magnitude for iv in group])
        if weights.sum() > 0:
            merged_mag = float(np.average(magnitudes, weights=weights))
        else:
            merged_mag = float(magnitudes.mean())

        # Merged confidence — increases with corroborating evidence
        merged_conf = min(
            base.confidence * (1 + 0.1 * (len(group) - 1)),
            1.0,
        )

        return Intervention(
            intervention_id=base.intervention_id,
            lever=base.lever,
            direction=base.direction,
            magnitude=merged_mag,
            scope=base.scope,
            mechanism=base.mechanism,
            evidence_trail=unique_trails,
            confidence=merged_conf,
            metadata={
                "agent_roles": sorted(all_roles),
                "n_evidence_packets": total_packets,
                "merged_from": len(group),
                "chain_strength": base.metadata.get("chain_strength", 0.0),
            },
        )

    # ------------------------------------------------------------------
    # Step 4 — resolve conflicts via epistemic hierarchy
    # ------------------------------------------------------------------

    def _resolve_conflicts(
        self,
        interventions: List[Intervention],
    ) -> List[Intervention]:
        """Resolve conflicting interventions on the same lever.

        If two interventions target the same lever but opposite directions,
        keep the one with higher epistemic authority, unless the weaker one
        has sufficiently high confidence to override.
        """
        # Group by lever
        by_lever: Dict[str, List[Intervention]] = defaultdict(list)
        for iv in interventions:
            by_lever[iv.lever].append(iv)

        resolved: List[Intervention] = []
        for lever, group in by_lever.items():
            if len(group) <= 1:
                resolved.extend(group)
                continue

            # Detect directional conflicts
            directions: Dict[str, List[Intervention]] = defaultdict(list)
            for iv in group:
                directions[iv.direction.value].append(iv)

            if len(directions) <= 1:
                # No conflict — all same direction
                resolved.extend(group)
                continue

            # Conflict exists — resolve
            resolved.extend(self._pick_winner(group))

        return resolved

    def _pick_winner(
        self,
        conflicting: List[Intervention],
    ) -> List[Intervention]:
        """Choose among conflicting interventions using epistemic hierarchy.

        Returns a list (may be 1 item if conflict is fully resolved, or
        multiple if they target non-overlapping scopes).
        """
        # Score each by epistemic weight of supporting sources
        scored: List[Tuple[float, Intervention]] = []
        for iv in conflicting:
            ep_score = self._epistemic_score(iv)
            # Confidence-weighted override: if a lower-hierarchy source
            # has >1.5x the confidence of a higher one, it can override
            total_score = ep_score * iv.confidence
            scored.append((total_score, iv))

        scored.sort(key=lambda x: x[0], reverse=True)

        # Keep the winner; drop losers unless they have non-overlapping scope
        winner_score, winner = scored[0]
        result = [winner]

        for score, iv in scored[1:]:
            # Keep if score is close enough (within 30% of winner)
            # and scope doesn't overlap — indicates a different sub-problem
            if score >= winner_score * 0.7 and not self._scopes_overlap(winner, iv):
                result.append(iv)

        return result

    def _epistemic_score(self, iv: Intervention) -> float:
        """Score an intervention by the epistemic hierarchy of its sources."""
        trail = iv.evidence_trail
        if not trail:
            return 0.5

        # Extract source types from the evidence trail
        agent_types = set()
        for entry in trail:
            agent_id = entry.split(":")[0] if ":" in entry else entry
            agent_types.add(agent_id)

        # Map agents to knowledge types
        agent_to_source = {
            "elasticity_agent": "quantitative",
            "interaction_agent": "quantitative",
            "constraint_agent": "policy",
            "temporal_agent": "quantitative",
            "portfolio_agent": "quantitative",
        }

        hierarchy_scores = []
        for agent in agent_types:
            src = agent_to_source.get(agent, "expert")
            hierarchy_scores.append(_SOURCE_HIERARCHY.get(src, 0.5))

        return max(hierarchy_scores) if hierarchy_scores else 0.5

    @staticmethod
    def _scopes_overlap(a: Intervention, b: Intervention) -> bool:
        """Check if two interventions have overlapping scope."""
        if not a.scope or not b.scope:
            return True  # No scope = global = overlaps everything

        # Check category overlap
        cats_a = set(a.scope.get("categories", []))
        cats_b = set(b.scope.get("categories", []))
        if cats_a and cats_b and not cats_a & cats_b:
            return False

        # Check region overlap
        regs_a = set(a.scope.get("regions", []))
        regs_b = set(b.scope.get("regions", []))
        if regs_a and regs_b and not regs_a & regs_b:
            return False

        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _causal_chain_strength(
        self,
        packets: List[EvidencePacket],
        agent_roles: set,
    ) -> float:
        """Score how strong the causal chain is for this evidence group.

        A strong chain has: sensitivity signal + interaction signal +
        no constraint violation.  Each additional dimension adds to strength.
        """
        score = 0.0
        has_sensitivity = "sensitivity" in agent_roles
        has_interaction = "interaction" in agent_roles
        has_constraint = "constraint" in agent_roles
        has_temporal = "temporal" in agent_roles
        has_portfolio = "portfolio" in agent_roles

        # Base: any single signal
        n_roles = len(agent_roles)
        score = min(n_roles / 3.0, 1.0)  # 3+ roles = max chain strength

        # Bonus for the ideal chain: sensitivity + interaction + constraint
        if has_sensitivity and has_interaction:
            score = max(score, 0.7)
        if has_sensitivity and has_interaction and has_constraint:
            score = max(score, 0.9)

        # Check for constraint violations in the packets
        for ep in packets:
            if ep.agent_id == "constraint_agent":
                if ep.data.get("violation", False):
                    score *= 0.3  # Heavy penalty for constraint violation
                elif ep.data.get("binding", False):
                    score *= 0.8  # Mild penalty for binding constraint

        return min(score, 1.0)

    def _aggregate_confidence(
        self,
        packets: List[EvidencePacket],
    ) -> float:
        """Compute aggregate confidence from evidence packets.

        Uses epistemic hierarchy weighting: quantitative sources weigh more
        than policy, which weighs more than expert.
        """
        if not packets:
            return 0.0

        weighted_sum = 0.0
        weight_total = 0.0

        for ep in packets:
            # Determine source weight from hierarchy
            source_weight = 0.5
            for src in ep.source_types:
                w = _SOURCE_HIERARCHY.get(src, 0.5)
                source_weight = max(source_weight, w)

            weighted_sum += ep.confidence * source_weight
            weight_total += source_weight

        return weighted_sum / weight_total if weight_total > 0 else 0.0

    @staticmethod
    def _aggregate_magnitude(packets: List[EvidencePacket]) -> float:
        """Confidence-weighted mean magnitude across packets."""
        if not packets:
            return 0.0
        confs = np.array([ep.confidence for ep in packets])
        mags = np.array([ep.magnitude for ep in packets])
        total_conf = confs.sum()
        if total_conf > 0:
            return float(np.average(mags, weights=confs))
        return float(mags.mean()) if len(mags) > 0 else 0.0

    @staticmethod
    def _aggregate_scope(packets: List[EvidencePacket]) -> Dict[str, Any]:
        """Build a unified scope dict from packet data."""
        categories: set = set()
        regions: set = set()
        sku_ids: set = set()

        for ep in packets:
            d = ep.data
            if "categories" in d:
                cats = d["categories"]
                if isinstance(cats, (list, tuple, set)):
                    categories.update(cats)
                else:
                    categories.add(str(cats))
            if "category" in d:
                categories.add(str(d["category"]))
            if "regions" in d:
                regs = d["regions"]
                if isinstance(regs, (list, tuple, set)):
                    regions.update(regs)
                else:
                    regions.add(str(regs))
            if "region" in d:
                regions.add(str(d["region"]))
            if "sku_ids" in d:
                ids = d["sku_ids"]
                if isinstance(ids, (list, tuple, set)):
                    sku_ids.update(int(x) for x in ids)
                elif ids is not None:
                    sku_ids.add(int(ids))
            if "sku_id" in d:
                sku_ids.add(int(d["sku_id"]))

        scope: Dict[str, Any] = {}
        if categories:
            scope["categories"] = sorted(categories)
        if regions:
            scope["regions"] = sorted(regions)
        if sku_ids:
            scope["sku_ids"] = sorted(sku_ids)
        return scope

    @staticmethod
    def _synthesize_mechanism(
        packets: List[EvidencePacket],
        agent_roles: set,
    ) -> str:
        """Build a mechanism description from contributing evidence."""
        mechanisms = []
        for ep in packets:
            if ep.mechanism and ep.mechanism not in mechanisms:
                mechanisms.append(ep.mechanism)

        if not mechanisms:
            return "Unspecified mechanism"

        # Join unique mechanisms with causal-chain notation
        if len(mechanisms) == 1:
            return mechanisms[0]
        return " → ".join(mechanisms[:4])  # Cap at 4 for readability
