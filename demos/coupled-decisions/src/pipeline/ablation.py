"""Ablation study runner.

Runs 4 ablation configurations from Experiment 2:
  * full_system      — all components enabled
  * no_coupling      — independent lever optimisation (no coupling graph)
  * no_encoding      — raw text concatenation instead of structured encoding
  * no_pipeline      — single-pass analysis (no progressive reduction)

Each config disables one component and measures degradation in:
  * effects_found — number of ground-truth effects discovered (out of 5)
  * precision     — of generated interventions vs ground truth
  * recall        — of ground-truth effects discovered
  * violations    — number of hard-constraint violations
  * revenue_impact — simulated revenue improvement

Only depends on stdlib + numpy + scipy (via upstream modules).
"""

from __future__ import annotations

import copy
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

from ..core.config import Config
from ..core.types import (
    ConstraintVector,
    Direction,
    EvidencePacket,
    Intervention,
    QualityScore,
    StatisticalProfile,
    TemporalBelief,
)
from ..core.coupling import CouplingGraph
from ..core.utils import get_logger, set_seed

from ..data.generator import BevCoGenerator
from ..data.policies import generate_policies
from ..data.experts import generate_expert_beliefs
from ..data.ground_truth import GROUND_TRUTH_EFFECTS, EFFECT_BY_ID

from ..encoding import (
    encode_quantitative,
    encode_policies,
    encode_experts,
)

from ..agents import (
    ElasticityAgent,
    InteractionAgent,
    ConstraintAgent,
    TemporalAgent,
    PortfolioAgent,
)

from ..synthesis.assembler import CausalAssembler
from ..quality.gate import QualityGate


logger = get_logger("ablation")


# ---------------------------------------------------------------------------
# Ablation configuration
# ---------------------------------------------------------------------------

@dataclass
class AblationConfig:
    """Configuration for a single ablation condition."""

    name: str
    description: str
    use_coupling: bool = True
    use_encoding: bool = True
    use_pipeline: bool = True
    use_all_agents: bool = True


# The 4 standard ablation configs
ABLATION_CONFIGS: Dict[str, AblationConfig] = {
    "full_system": AblationConfig(
        name="full_system",
        description="All components enabled — baseline",
        use_coupling=True,
        use_encoding=True,
        use_pipeline=True,
    ),
    "no_coupling": AblationConfig(
        name="no_coupling",
        description="Independent lever optimisation — no coupling graph",
        use_coupling=False,
        use_encoding=True,
        use_pipeline=True,
    ),
    "no_encoding": AblationConfig(
        name="no_encoding",
        description="Raw text concatenation — no structured encoding",
        use_coupling=True,
        use_encoding=False,
        use_pipeline=True,
    ),
    "no_pipeline": AblationConfig(
        name="no_pipeline",
        description="Single-pass analysis — no progressive reduction",
        use_coupling=True,
        use_encoding=True,
        use_pipeline=False,
    ),
}


# ---------------------------------------------------------------------------
# AblationRunner
# ---------------------------------------------------------------------------

class AblationRunner:
    """Runs all 4 ablation configurations and collects comparison results."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config()

    def run_all(self) -> Dict[str, Any]:
        """Run all 4 ablation configs and return comparison results.

        Returns
        -------
        dict
            Keys are ablation config names, values are result dicts.
        """
        results: Dict[str, Any] = {}
        for name, ablation_cfg in ABLATION_CONFIGS.items():
            logger.info("Running ablation: %s", name)
            t0 = time.time()
            result = self._run_single(ablation_cfg)
            result["elapsed_seconds"] = round(time.time() - t0, 2)
            results[name] = result
            logger.info(
                "Ablation %s: effects=%d/%d precision=%.2f recall=%.2f violations=%d",
                name,
                result["effects_found"],
                result["effects_total"],
                result["precision"],
                result["recall"],
                result["violations"],
            )
        return results

    def run_single(self, name: str) -> Dict[str, Any]:
        """Run a single named ablation config."""
        cfg = ABLATION_CONFIGS.get(name)
        if cfg is None:
            raise ValueError(f"Unknown ablation config: {name}")
        return self._run_single(cfg)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run_single(self, ablation_cfg: AblationConfig) -> Dict[str, Any]:
        """Execute one ablation condition."""
        set_seed(self.config.random_seed)

        # 1. Generate data (same for all conditions)
        gen = BevCoGenerator(seed=self.config.random_seed)
        sales = gen.generate_sales()
        elasticities = gen.generate_elasticities()
        market_share = gen.generate_market_share()
        policies = generate_policies()
        expert_beliefs = generate_expert_beliefs()

        # 2. Encode knowledge (or skip if no_encoding)
        if ablation_cfg.use_encoding:
            encoded_q = self._encode_quantitative(sales)
            encoded_p = encode_policies(policies)
            encoded_e = encode_experts(
                expert_beliefs,
                decay_rate=self.config.expert_decay_rate,
            )
        else:
            # No encoding — pass raw data as minimal profiles
            encoded_q = self._raw_quantitative(sales)
            encoded_p = self._raw_policies(policies)
            encoded_e = self._raw_experts(expert_beliefs)

        encoded_knowledge = {
            "quantitative": encoded_q,
            "policy": encoded_p,
            "expert": encoded_e,
            "sales": sales,
            "elasticities": elasticities,
            "market_share": market_share,
            "constraints": encoded_p,
        }

        # 3. Optionally disable coupling info
        if not ablation_cfg.use_coupling:
            # Remove cross-lever data so agents treat levers independently
            encoded_knowledge["elasticities"] = self._strip_cross_elasticities(
                elasticities
            )

        # 4. Run agents
        evidence = self._run_agents(encoded_knowledge)

        # 5. Synthesis + quality gate (or single-pass if no_pipeline)
        if ablation_cfg.use_pipeline:
            interventions = self._run_pipeline(evidence, encoded_p)
        else:
            interventions = self._single_pass(evidence, encoded_p)

        # 6. Score against ground truth
        return self._score(interventions, ablation_cfg.name)

    def _encode_quantitative(
        self,
        sales: Dict[str, np.ndarray],
    ) -> List[StatisticalProfile]:
        """Encode per-SKU weekly revenue into StatisticalProfiles."""
        profiles: List[StatisticalProfile] = []
        revenue = np.asarray(sales.get("revenue", []), dtype=np.float64)
        if len(revenue) == 0:
            return profiles

        sku_ids = np.asarray(sales.get("sku_id", []))
        weeks = np.asarray(sales.get("week", []))
        n_weeks = self.config.n_weeks

        for sku_id in range(self.config.n_skus):
            mask = sku_ids == sku_id
            sku_revenue = revenue[mask]
            if len(sku_revenue) == 0:
                continue
            sku_weeks = weeks[mask]
            weekly = np.zeros(n_weeks)
            counts = np.zeros(n_weeks)
            for w, r in zip(sku_weeks, sku_revenue):
                wi = int(w) % n_weeks
                weekly[wi] += r
                counts[wi] += 1
            counts[counts == 0] = 1
            weekly /= counts
            profile = encode_quantitative(
                weekly,
                ci_level=self.config.confidence_interval_level,
            )
            profile.metadata["sku_id"] = int(sku_id)
            profiles.append(profile)
        return profiles

    @staticmethod
    def _raw_quantitative(
        sales: Dict[str, np.ndarray],
    ) -> List[StatisticalProfile]:
        """Minimal no-encoding: just store raw means as profiles."""
        profiles: List[StatisticalProfile] = []
        revenue = np.asarray(sales.get("revenue", []), dtype=np.float64)
        if len(revenue) == 0:
            return profiles
        # Single global profile — loses per-SKU granularity
        profile = StatisticalProfile(
            mean=float(np.mean(revenue)),
            std=float(np.std(revenue)),
            n_observations=len(revenue),
            metadata={"encoding": "raw"},
        )
        profiles.append(profile)
        return profiles

    @staticmethod
    def _raw_policies(
        policies: List[Dict[str, Any]],
    ) -> List[ConstraintVector]:
        """Minimal no-encoding: basic constraint vectors without enrichment."""
        vectors: List[ConstraintVector] = []
        for p in policies:
            # Threshold may be a dict (e.g., {"min_margin_pct": 0.25})
            threshold = p.get("threshold", 0.0)
            if isinstance(threshold, dict):
                # Extract the first numeric value
                bound = 0.0
                for v in threshold.values():
                    if isinstance(v, (int, float)):
                        bound = float(v)
                        break
            else:
                bound = float(threshold)
            cv = ConstraintVector(
                rule_id=p.get("rule_id", ""),
                lever=p.get("lever", ""),
                direction=p.get("direction", ""),
                bound=bound,
                scope=p.get("scope", {}),
                rationale=p.get("rationale", ""),
                metadata={"encoding": "raw"},
            )
            vectors.append(cv)
        return vectors

    @staticmethod
    def _raw_experts(
        beliefs: List[Dict[str, Any]],
    ) -> List[TemporalBelief]:
        """Minimal no-encoding: beliefs without decay or conflict detection."""
        result: List[TemporalBelief] = []
        for b in beliefs:
            tb = TemporalBelief(
                statement=b.get("statement", ""),
                confidence=float(b.get("confidence", 0.5)),
                domain=b.get("domain", []),
                metadata={"encoding": "raw"},
            )
            result.append(tb)
        return result

    @staticmethod
    def _strip_cross_elasticities(
        elasticities: Dict[str, np.ndarray],
    ) -> Dict[str, np.ndarray]:
        """Remove cross-price elasticities (keep only own-price)."""
        types = np.asarray(elasticities.get("type", []))
        if len(types) == 0:
            return elasticities

        own_mask = types == "own"
        stripped: Dict[str, np.ndarray] = {}
        for key, arr in elasticities.items():
            arr = np.asarray(arr)
            if len(arr) == len(own_mask):
                stripped[key] = arr[own_mask]
            else:
                stripped[key] = arr
        return stripped

    def _run_agents(
        self,
        encoded_knowledge: Dict[str, Any],
    ) -> List[EvidencePacket]:
        """Run all 5 diagnostic agents."""
        agents = [
            ElasticityAgent(self.config, encoded_knowledge),
            InteractionAgent(self.config, encoded_knowledge),
            ConstraintAgent(self.config, encoded_knowledge),
            TemporalAgent(self.config, encoded_knowledge),
            PortfolioAgent(self.config, encoded_knowledge),
        ]
        evidence: List[EvidencePacket] = []
        for agent in agents:
            try:
                packets = agent.diagnose()
                evidence.extend(packets)
            except Exception as exc:
                logger.warning("Agent %s failed: %s", agent.AGENT_ID, exc)
        return evidence

    def _run_pipeline(
        self,
        evidence: List[EvidencePacket],
        constraints: List[ConstraintVector],
    ) -> List[Intervention]:
        """Full pipeline: synthesis → quality gate."""
        assembler = CausalAssembler(self.config)
        interventions = assembler.assemble(evidence)

        gate = QualityGate(self.config, constraints=constraints)
        return gate.score_and_filter(interventions)

    def _single_pass(
        self,
        evidence: List[EvidencePacket],
        constraints: List[ConstraintVector],
    ) -> List[Intervention]:
        """No-pipeline: convert evidence directly to interventions.

        Skips causal synthesis — each evidence packet becomes a raw
        intervention. Still applies quality gate for fair comparison.
        """
        interventions: List[Intervention] = []
        for i, ep in enumerate(evidence):
            iv = Intervention(
                intervention_id=f"SP-{i:04d}",
                lever=ep.lever,
                direction=ep.direction,
                magnitude=ep.magnitude,
                scope=ep.data.get("scope", {}),
                mechanism=ep.mechanism,
                evidence_trail=[f"{ep.agent_id}:{ep.mechanism}"],
                confidence=ep.confidence,
                metadata={
                    "agent_roles": [ep.agent_id],
                    "n_evidence_packets": 1,
                    "chain_strength": 0.3,  # Single-pass = weak chain
                    "single_pass": True,
                },
            )
            interventions.append(iv)

        # Still apply quality gate for fair scoring
        gate = QualityGate(self.config, constraints=constraints)
        return gate.score_and_filter(interventions, top_k=self.config.quality_gate_top_k)

    # ------------------------------------------------------------------
    # Ground truth scoring (same logic as PipelineRunner)
    # ------------------------------------------------------------------

    def _score(
        self,
        interventions: List[Intervention],
        config_name: str,
    ) -> Dict[str, Any]:
        """Score interventions against ground truth."""
        n_gt = len(GROUND_TRUTH_EFFECTS)
        discovered: List[str] = []
        per_effect: Dict[str, Dict[str, Any]] = {}

        for gt_effect in GROUND_TRUTH_EFFECTS:
            match = self._match_effect(gt_effect, interventions)
            per_effect[gt_effect.effect_id] = {
                "name": gt_effect.name,
                "levers": gt_effect.levers,
                "discovered": match is not None,
                "matching_intervention": match,
            }
            if match is not None:
                discovered.append(gt_effect.effect_id)

        n_final = len(interventions)
        true_positives = len(discovered)
        precision = true_positives / n_final if n_final > 0 else 0.0
        recall = true_positives / n_gt if n_gt > 0 else 0.0

        violations = sum(
            1 for iv in interventions
            if iv.quality and iv.quality.hard_constraint_violation
        )

        revenue_impact = self._estimate_revenue_impact(discovered)

        return {
            "config": config_name,
            "effects_found": true_positives,
            "effects_total": n_gt,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "violations": violations,
            "revenue_impact": round(revenue_impact, 3),
            "discovered_effects": discovered,
            "per_effect": per_effect,
        }

    @staticmethod
    def _match_effect(
        gt_effect: InteractionEffect,
        interventions: List[Intervention],
    ) -> Optional[str]:
        """Check if any intervention matches a ground-truth effect."""
        gt_levers = set(gt_effect.levers)
        gt_mechanism = gt_effect.mechanism.lower()

        best_match: Optional[str] = None
        best_score = 0.0

        for iv in interventions:
            iv_levers = set()
            iv_levers.add(iv.lever)
            for part in iv.lever.split("+"):
                iv_levers.add(part.strip())

            overlap = gt_levers & iv_levers
            if not overlap:
                continue

            lever_score = len(overlap) / len(gt_levers)

            mech_score = 0.0
            iv_mechanism = iv.mechanism.lower()
            gt_keywords = set(gt_mechanism.replace("_", " ").split())
            iv_keywords = set(iv_mechanism.replace("_", " ").replace("→", " ").split())
            keyword_overlap = gt_keywords & iv_keywords
            if gt_keywords:
                mech_score = len(keyword_overlap) / len(gt_keywords)

            score = 0.6 * lever_score + 0.4 * mech_score
            if score > best_score and score >= 0.3:
                best_score = score
                best_match = iv.intervention_id

        return best_match

    @staticmethod
    def _estimate_revenue_impact(discovered: List[str]) -> float:
        """Estimate revenue impact from discovered GT effects."""
        total = 0.0
        for eid in discovered:
            effect = EFFECT_BY_ID.get(eid)
            if effect is None:
                continue
            impact = effect.expected_impact
            deltas = [
                v for k, v in impact.items()
                if isinstance(v, (int, float)) and "delta" in k
            ]
            if deltas:
                total += max(deltas)
        return total
