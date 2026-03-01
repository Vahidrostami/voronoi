"""Full pipeline orchestrator.

Orchestrates the end-to-end coupled-decisions pipeline:
  1. Load / generate data
  2. Encode all knowledge sources
  3. Run 5 diagnostic agents (sequentially for determinism)
  4. Collect evidence packets
  5. Causal synthesis → candidate interventions
  6. Quality gate → scored, ranked top-K interventions
  7. Score against ground truth
  8. Return results dict

Only depends on stdlib + numpy + scipy (via upstream modules).
"""

from __future__ import annotations

import logging
import time
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
from ..data.experts import generate_expert_beliefs, generate_agent_facing_beliefs
from ..data.ground_truth import GROUND_TRUTH_EFFECTS, InteractionEffect

from ..encoding import (
    encode_quantitative,
    encode_policies,
    encode_experts,
    cross_query,
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


logger = get_logger("pipeline")


class PipelineRunner:
    """Orchestrates the full coupled-decisions pipeline."""

    def __init__(self, config: Optional[Config] = None) -> None:
        self.config = config or Config()
        self.coupling = CouplingGraph()

        # Internal state populated during run()
        self._sales: Dict[str, np.ndarray] = {}
        self._elasticities: Dict[str, np.ndarray] = {}
        self._market_share: Dict[str, np.ndarray] = {}
        self._policies: List[Dict[str, Any]] = []
        self._expert_beliefs: List[Dict[str, Any]] = []
        self._encoded_quantitative: List[StatisticalProfile] = []
        self._encoded_policies: List[ConstraintVector] = []
        self._encoded_experts: List[TemporalBelief] = []
        self._evidence: List[EvidencePacket] = []
        self._interventions: List[Intervention] = []
        self._final: List[Intervention] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> Dict[str, Any]:
        """Execute the full pipeline and return results.

        Returns
        -------
        dict
            Contains: config, stages (with timings and sizes),
            interventions, ground_truth_scoring, and timings.
        """
        set_seed(self.config.random_seed)
        timings: Dict[str, float] = {}
        stages: Dict[str, Any] = {}

        # Stage 0: Generate / load data
        t0 = time.time()
        self._generate_data()
        timings["data_generation"] = time.time() - t0
        stages["stage_0_data"] = {
            "sales_rows": len(self._sales.get("week", [])),
            "elasticity_rows": len(self._elasticities.get("sku_i", [])),
            "market_share_rows": len(self._market_share.get("week", [])),
            "n_policies": len(self._policies),
            "n_expert_beliefs": len(self._expert_beliefs),
        }

        # Stage 1: Encode knowledge
        t0 = time.time()
        self._encode_knowledge()
        timings["encoding"] = time.time() - t0
        stages["stage_1_encoding"] = {
            "quantitative_profiles": len(self._encoded_quantitative),
            "policy_constraints": len(self._encoded_policies),
            "expert_beliefs": len(self._encoded_experts),
        }

        # Stage 2: Run diagnostic agents
        t0 = time.time()
        self._run_agents()
        timings["diagnostic_agents"] = time.time() - t0
        stages["stage_2_diagnostic"] = {
            "total_evidence_packets": len(self._evidence),
            "by_agent": self._evidence_by_agent(),
        }

        # Stage 3: Causal synthesis
        t0 = time.time()
        self._run_synthesis()
        timings["synthesis"] = time.time() - t0
        stages["stage_3_synthesis"] = {
            "candidate_interventions": len(self._interventions),
        }

        # Stage 4: Quality gate
        t0 = time.time()
        self._run_quality_gate()
        timings["quality_gate"] = time.time() - t0
        stages["stage_4_quality_gate"] = {
            "final_interventions": len(self._final),
        }

        # Stage 5: Score against ground truth
        t0 = time.time()
        gt_results = self._score_ground_truth()
        timings["scoring"] = time.time() - t0

        return {
            "config": self.config.to_dict(),
            "stages": stages,
            "timings": timings,
            "interventions": [iv.to_dict() for iv in self._final],
            "ground_truth": gt_results,
        }

    # ------------------------------------------------------------------
    # Pipeline stages
    # ------------------------------------------------------------------

    def _generate_data(self) -> None:
        """Generate synthetic BevCo data."""
        gen = BevCoGenerator(seed=self.config.random_seed)
        self._sales = gen.generate_sales()
        self._elasticities = gen.generate_elasticities()
        self._market_share = gen.generate_market_share()
        self._policies = generate_policies()
        self._expert_beliefs = generate_expert_beliefs()
        logger.info(
            "Data generated: %d sales rows, %d elasticity rows, %d policies, %d beliefs",
            len(self._sales.get("week", [])),
            len(self._elasticities.get("sku_i", [])),
            len(self._policies),
            len(self._expert_beliefs),
        )

    def _encode_knowledge(self) -> None:
        """Encode all three knowledge sources."""
        # Quantitative — encode per-SKU weekly sales profiles
        n_skus = self.config.n_skus
        n_weeks = self.config.n_weeks
        revenue = np.asarray(self._sales.get("revenue", []), dtype=np.float64)

        if len(revenue) > 0:
            sku_ids = np.asarray(self._sales.get("sku_id", []))
            for sku_id in range(n_skus):
                mask = sku_ids == sku_id
                sku_revenue = revenue[mask]
                if len(sku_revenue) > 0:
                    # Aggregate to weekly for this SKU
                    weeks = np.asarray(self._sales.get("week", []))[mask]
                    weekly = np.zeros(n_weeks)
                    counts = np.zeros(n_weeks)
                    for w, r in zip(weeks, sku_revenue):
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
                    self._encoded_quantitative.append(profile)

        # Policy — encode each policy rule
        self._encoded_policies = encode_policies(self._policies)

        # Expert — encode each belief
        self._encoded_experts = encode_experts(
            self._expert_beliefs,
            decay_rate=self.config.expert_decay_rate,
        )

        logger.info(
            "Encoded: %d quantitative profiles, %d policy constraints, %d expert beliefs",
            len(self._encoded_quantitative),
            len(self._encoded_policies),
            len(self._encoded_experts),
        )

    def _build_encoded_knowledge(self) -> Dict[str, Any]:
        """Build the encoded_knowledge dict expected by agents."""
        return {
            "quantitative": self._encoded_quantitative,
            "policy": self._encoded_policies,
            "expert": self._encoded_experts,
            "sales": self._sales,
            "elasticities": self._elasticities,
            "market_share": self._market_share,
            "constraints": self._encoded_policies,
        }

    def _run_agents(self) -> None:
        """Run all 5 diagnostic agents sequentially."""
        encoded = self._build_encoded_knowledge()
        agents = [
            ElasticityAgent(self.config, encoded),
            InteractionAgent(self.config, encoded),
            ConstraintAgent(self.config, encoded),
            TemporalAgent(self.config, encoded),
            PortfolioAgent(self.config, encoded),
        ]

        self._evidence = []
        for agent in agents:
            try:
                packets = agent.diagnose()
                self._evidence.extend(packets)
                logger.info(
                    "Agent %s produced %d evidence packets",
                    agent.AGENT_ID,
                    len(packets),
                )
            except Exception as exc:
                logger.warning(
                    "Agent %s failed: %s", agent.AGENT_ID, exc
                )

    def _run_synthesis(self) -> None:
        """Run causal synthesis on collected evidence."""
        assembler = CausalAssembler(self.config)
        self._interventions = assembler.assemble(self._evidence)
        logger.info(
            "Synthesis produced %d candidate interventions",
            len(self._interventions),
        )

    def _run_quality_gate(self) -> None:
        """Score and filter interventions through the quality gate."""
        gate = QualityGate(self.config, constraints=self._encoded_policies)
        self._final = gate.score_and_filter(self._interventions)
        logger.info(
            "Quality gate selected %d final interventions",
            len(self._final),
        )

    # ------------------------------------------------------------------
    # Ground truth scoring
    # ------------------------------------------------------------------

    def _score_ground_truth(self) -> Dict[str, Any]:
        """Score final interventions against planted ground-truth effects.

        For each ground-truth effect, check if any final intervention
        covers the relevant levers and mechanism.

        Returns
        -------
        dict
            effects_found, precision, recall, violations, per-effect details.
        """
        n_gt = len(GROUND_TRUTH_EFFECTS)
        discovered: List[str] = []
        details: Dict[str, Dict[str, Any]] = {}

        for gt_effect in GROUND_TRUTH_EFFECTS:
            match = self._match_effect(gt_effect, self._final)
            details[gt_effect.effect_id] = {
                "name": gt_effect.name,
                "levers": gt_effect.levers,
                "discovered": match is not None,
                "matching_intervention": match,
            }
            if match is not None:
                discovered.append(gt_effect.effect_id)

        # Precision: of interventions produced, how many correspond to GT effects
        n_final = len(self._final)
        true_positives = len(discovered)
        precision = true_positives / n_final if n_final > 0 else 0.0
        recall = true_positives / n_gt if n_gt > 0 else 0.0

        # Count constraint violations
        violations = sum(
            1 for iv in self._final
            if iv.quality and iv.quality.hard_constraint_violation
        )

        # Simulate revenue impact (based on magnitudes of correct interventions)
        revenue_impact = self._estimate_revenue_impact(discovered)

        return {
            "effects_found": true_positives,
            "effects_total": n_gt,
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "violations": violations,
            "revenue_impact": round(revenue_impact, 3),
            "discovered_effects": discovered,
            "per_effect": details,
        }

    def _match_effect(
        self,
        gt_effect: InteractionEffect,
        interventions: List[Intervention],
    ) -> Optional[str]:
        """Check if any intervention matches a ground-truth effect.

        Matching criteria: the intervention's lever(s) overlap with the
        effect's levers, and the mechanism keyword is related.

        Returns the intervention_id of the best match, or None.
        """
        gt_levers = set(gt_effect.levers)
        gt_mechanism = gt_effect.mechanism.lower()

        best_match: Optional[str] = None
        best_score = 0.0

        for iv in interventions:
            # Check lever overlap
            iv_levers = set()
            iv_levers.add(iv.lever)
            # Handle compound levers like "pricing+promotion"
            for part in iv.lever.split("+"):
                iv_levers.add(part.strip())

            overlap = gt_levers & iv_levers
            if not overlap:
                continue

            # Lever match score
            lever_score = len(overlap) / len(gt_levers)

            # Mechanism match — keyword overlap
            mech_score = 0.0
            iv_mechanism = iv.mechanism.lower()
            gt_keywords = set(gt_mechanism.replace("_", " ").split())
            iv_keywords = set(iv_mechanism.replace("_", " ").replace("→", " ").split())
            keyword_overlap = gt_keywords & iv_keywords
            if gt_keywords:
                mech_score = len(keyword_overlap) / len(gt_keywords)

            # Combined score
            score = 0.6 * lever_score + 0.4 * mech_score

            if score > best_score and score >= 0.3:
                best_score = score
                best_match = iv.intervention_id

        return best_match

    def _estimate_revenue_impact(self, discovered: List[str]) -> float:
        """Estimate revenue impact based on discovered GT effects.

        Uses the expected_impact values from ground truth as simulation.
        """
        total = 0.0
        from ..data.ground_truth import EFFECT_BY_ID
        for eid in discovered:
            effect = EFFECT_BY_ID.get(eid)
            if effect is None:
                continue
            impact = effect.expected_impact
            # Use the most positive delta as the revenue signal
            deltas = [
                v for k, v in impact.items()
                if isinstance(v, (int, float)) and "delta" in k
            ]
            if deltas:
                total += max(deltas)
        return total

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _evidence_by_agent(self) -> Dict[str, int]:
        """Count evidence packets per agent."""
        counts: Dict[str, int] = {}
        for ep in self._evidence:
            counts[ep.agent_id] = counts.get(ep.agent_id, 0) + 1
        return counts
