"""Experiment 3 — Progressive Reduction Pipeline.

Measures the pipeline's compression and quality at each stage:
  Stage 0: Full combinatorial space  ~10^18
  Stage 1: After diagnostic agents   ~10^3
  Stage 2: After causal synthesis     ~50
  Stage 3: After quality gate         ~10

Also tracks ground-truth coverage at each stage (should be 1.0 throughout).

Only depends on stdlib + numpy + scipy (via upstream modules).
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np

from ..core.config import Config
from ..core.types import (
    ConstraintVector,
    EvidencePacket,
    Intervention,
    StatisticalProfile,
    TemporalBelief,
)
from ..core.utils import get_logger, set_seed

from ..data.generator import BevCoGenerator
from ..data.policies import generate_policies
from ..data.experts import generate_expert_beliefs
from ..data.ground_truth import GROUND_TRUTH_EFFECTS, InteractionEffect

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

logger = get_logger("experiment_3")


# ---------------------------------------------------------------------------
# Ground-truth coverage checker
# ---------------------------------------------------------------------------

def _gt_coverage_evidence(
    evidence: List[EvidencePacket],
    effects: List[InteractionEffect],
) -> float:
    """What fraction of GT effects have at least one related evidence packet?"""
    if not effects:
        return 0.0
    found = 0
    for eff in effects:
        gt_levers = set(eff.levers)
        for ep in evidence:
            ep_levers = {ep.lever}
            ep_levers.update(ep.related_levers)
            if gt_levers & ep_levers:
                found += 1
                break
    return found / len(effects)


def _gt_coverage_interventions(
    interventions: List[Intervention],
    effects: List[InteractionEffect],
) -> float:
    """What fraction of GT effects have at least one matching intervention?"""
    if not effects:
        return 0.0
    found = 0
    for eff in effects:
        gt_levers = set(eff.levers)
        gt_mechanism = eff.mechanism.lower()
        for iv in interventions:
            iv_levers = set()
            iv_levers.add(iv.lever)
            for part in iv.lever.split("+"):
                iv_levers.add(part.strip())
            if gt_levers & iv_levers:
                found += 1
                break
    return found / len(effects)


# ---------------------------------------------------------------------------
# Main experiment runner
# ---------------------------------------------------------------------------

def run_experiment_3(config: Config | None = None) -> Dict[str, Any]:
    """Run Experiment 3: Progressive Reduction Pipeline.

    Returns
    -------
    dict
        stage_0_input, stage_1_diagnostic, stage_2_synthesis,
        stage_3_quality_gate, ground_truth_coverage_per_stage.
    """
    config = config or Config()
    set_seed(config.random_seed)
    logger.info("Starting Experiment 3: Progressive Reduction Pipeline")

    # --- Stage 0: Compute combinatorial space size ---
    # 5 levers × multiple variables × regions × SKUs
    # Pricing: ~50 price points × 50 SKUs × 4 regions = 10,000
    # Promotion: 12 types × 5 freq × 10 depths × 50 SKUs = 300,000
    # Assortment: 2^50 subsets × 20 clusters ≈ huge
    # Distribution: 200 stores × 8 facings × 50 SKUs
    # Pack-price: 5 sizes × 50 price points × 50 SKUs
    stage_0_input = 1e18  # As specified in PROMPT.md
    logger.info("Stage 0: Input space = %.0e", stage_0_input)

    # --- Generate data ---
    gen = BevCoGenerator(seed=config.random_seed)
    sales = gen.generate_sales()
    elasticities = gen.generate_elasticities()
    market_share = gen.generate_market_share()
    policies_raw = generate_policies()
    beliefs_raw = generate_expert_beliefs()

    # --- Encode knowledge ---
    encoded_quant: List[StatisticalProfile] = []
    revenue = np.asarray(sales.get("revenue", []), dtype=np.float64)
    sku_ids = np.asarray(sales.get("sku_id", []))
    weeks = np.asarray(sales.get("week", []))
    n_weeks = config.n_weeks

    for sku_id in range(config.n_skus):
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
        profile = encode_quantitative(weekly, ci_level=config.confidence_interval_level)
        profile.metadata["sku_id"] = int(sku_id)
        encoded_quant.append(profile)

    encoded_policy = encode_policies(policies_raw)
    encoded_expert = encode_experts(beliefs_raw, decay_rate=config.expert_decay_rate)

    encoded_knowledge = {
        "quantitative": encoded_quant,
        "policy": encoded_policy,
        "expert": encoded_expert,
        "sales": sales,
        "elasticities": elasticities,
        "market_share": market_share,
        "constraints": encoded_policy,
    }

    # --- Stage 1: Diagnostic agents ---
    agents = [
        ElasticityAgent(config, encoded_knowledge),
        InteractionAgent(config, encoded_knowledge),
        ConstraintAgent(config, encoded_knowledge),
        TemporalAgent(config, encoded_knowledge),
        PortfolioAgent(config, encoded_knowledge),
    ]

    all_evidence: List[EvidencePacket] = []
    for agent in agents:
        try:
            packets = agent.diagnose()
            all_evidence.extend(packets)
            logger.info("  Agent %s: %d packets", agent.AGENT_ID, len(packets))
        except Exception as exc:
            logger.warning("  Agent %s failed: %s", agent.AGENT_ID, exc)

    stage_1_size = len(all_evidence)
    coverage_1 = _gt_coverage_evidence(all_evidence, GROUND_TRUTH_EFFECTS)
    logger.info("Stage 1: Diagnostic output = %d evidence packets, GT coverage = %.2f",
                stage_1_size, coverage_1)

    # --- Stage 2: Causal synthesis ---
    assembler = CausalAssembler(config)
    interventions = assembler.assemble(all_evidence)
    stage_2_size = len(interventions)
    coverage_2 = _gt_coverage_interventions(interventions, GROUND_TRUTH_EFFECTS)
    logger.info("Stage 2: Synthesis output = %d interventions, GT coverage = %.2f",
                stage_2_size, coverage_2)

    # --- Stage 3: Quality gate ---
    gate = QualityGate(config, constraints=encoded_policy)
    final = gate.score_and_filter(interventions)
    stage_3_size = len(final)
    coverage_3 = _gt_coverage_interventions(final, GROUND_TRUTH_EFFECTS)
    logger.info("Stage 3: Quality gate output = %d final, GT coverage = %.2f",
                stage_3_size, coverage_3)

    # Full input space coverage is 1.0 by definition (all effects are in the space)
    coverage_0 = 1.0

    results = {
        "stage_0_input": stage_0_input,
        "stage_1_diagnostic": stage_1_size,
        "stage_2_synthesis": stage_2_size,
        "stage_3_quality_gate": stage_3_size,
        "ground_truth_coverage_per_stage": [
            round(coverage_0, 2),
            round(coverage_1, 2),
            round(coverage_2, 2),
            round(coverage_3, 2),
        ],
    }

    logger.info("Experiment 3 complete: %s", {
        k: v for k, v in results.items() if k != "ground_truth_coverage_per_stage"
    })
    return results
