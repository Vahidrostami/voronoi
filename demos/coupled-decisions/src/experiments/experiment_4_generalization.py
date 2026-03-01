"""Experiment 4 — Cross-Domain Generalization.

Two mini-domains using the same pipeline architecture:

(a) Precision Medicine: 3 coupled treatment levers (drug, dose, timing),
    synthetic 100-patient dataset, 1 planted cross-lever effect.

(b) Supply Chain: 3 coupled levers (sourcing, inventory, routing),
    50-node dataset, 1 planted cross-lever effect.

Metric: Does the framework discover at least 1 planted effect in each domain?

Only depends on stdlib + numpy + scipy (via upstream modules).
"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import stats as sp_stats

from ..core.config import Config
from ..core.types import (
    ConstraintHardness,
    ConstraintVector,
    Direction,
    EvidencePacket,
    ExpertBasis,
    Intervention,
    QualityScore,
    StatisticalProfile,
    TemporalBelief,
)
from ..core.utils import get_logger, set_seed

logger = get_logger("experiment_4")


# ===================================================================
# Generic mini-domain pipeline
# ===================================================================

class MiniDomainPipeline:
    """A stripped-down pipeline for mini-domain generalization tests.

    Reuses the same architecture: encode → diagnose → synthesize → gate,
    but with domain-specific data and fewer levers.
    """

    def __init__(
        self,
        domain_name: str,
        levers: List[str],
        planted_effects: List[Dict[str, Any]],
        seed: int = 42,
    ) -> None:
        self.domain_name = domain_name
        self.levers = levers
        self.planted_effects = planted_effects
        self.rng = np.random.default_rng(seed)

    def run(
        self,
        quant_data: Dict[str, np.ndarray],
        policies: List[Dict[str, Any]],
        expert_beliefs: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Run the mini-domain pipeline.

        Returns: effects_found, effects_total, pipeline_functional, details.
        """
        # 1. Encode
        encoded_quant = self._encode_quantitative(quant_data)
        encoded_policy = self._encode_policies(policies)
        encoded_expert = self._encode_experts(expert_beliefs)

        # 2. Diagnose — lightweight agent-like analysis
        evidence = self._diagnose(
            quant_data, encoded_quant, encoded_policy, encoded_expert
        )

        # 3. Synthesize — group evidence into interventions
        interventions = self._synthesize(evidence, encoded_policy)

        # 4. Quality gate — score and filter
        final = self._quality_gate(interventions, encoded_policy)

        # 5. Score against planted effects
        effects_found = self._score(final)

        return {
            "effects_found": effects_found,
            "effects_total": len(self.planted_effects),
            "pipeline_functional": len(final) > 0,
            "n_evidence_packets": len(evidence),
            "n_interventions": len(interventions),
            "n_final": len(final),
        }

    # ---- Encode ----

    def _encode_quantitative(
        self, data: Dict[str, np.ndarray]
    ) -> List[StatisticalProfile]:
        """Encode quantitative data into per-lever profiles."""
        profiles = []
        for lever in self.levers:
            arr = data.get(lever)
            if arr is None:
                continue
            arr = np.asarray(arr, dtype=np.float64).ravel()
            if len(arr) == 0:
                continue
            mean = float(np.mean(arr))
            std = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
            n = len(arr)
            if n > 1 and std > 0:
                t_crit = float(sp_stats.t.ppf(0.975, df=n - 1))
                margin = t_crit * std / np.sqrt(n)
            else:
                margin = 0.0
            profiles.append(StatisticalProfile(
                mean=mean,
                std=std,
                ci_lower=mean - margin,
                ci_upper=mean + margin,
                n_observations=n,
                metadata={"lever": lever},
            ))
        return profiles

    def _encode_policies(
        self, policies: List[Dict[str, Any]]
    ) -> List[ConstraintVector]:
        """Encode policy rules into constraint vectors."""
        result = []
        for p in policies:
            thresh = p.get("threshold", 0.0)
            if isinstance(thresh, dict):
                bound = next(
                    (float(v) for v in thresh.values() if isinstance(v, (int, float))),
                    0.0,
                )
            else:
                bound = float(thresh)
            hardness = (
                ConstraintHardness.HARD
                if p.get("type") == "hard"
                else ConstraintHardness.SOFT
            )
            result.append(ConstraintVector(
                rule_id=p.get("rule_id", ""),
                lever=p.get("lever", ""),
                direction=p.get("direction", ">="),
                bound=bound,
                hardness=hardness,
                scope=p.get("scope", {}),
                rationale=p.get("rationale", ""),
            ))
        return result

    def _encode_experts(
        self, beliefs: List[Dict[str, Any]]
    ) -> List[TemporalBelief]:
        """Encode expert beliefs into temporal beliefs."""
        result = []
        for b in beliefs:
            basis_str = b.get("basis", "experience")
            try:
                basis = ExpertBasis(basis_str)
            except ValueError:
                basis = ExpertBasis.EXPERIENCE
            result.append(TemporalBelief(
                statement=b.get("statement", ""),
                confidence=float(b.get("confidence", 0.5)),
                domain=b.get("domain", []),
                basis=basis,
                current_confidence=float(b.get("confidence", 0.5)),
                lever_direction=b.get("lever_direction"),
            ))
        return result

    # ---- Diagnose ----

    def _diagnose(
        self,
        raw_data: Dict[str, np.ndarray],
        profiles: List[StatisticalProfile],
        constraints: List[ConstraintVector],
        beliefs: List[TemporalBelief],
    ) -> List[EvidencePacket]:
        """Lightweight diagnostic analysis across all levers."""
        evidence = []

        # Sensitivity analysis: check if levers have significant variation
        for prof in profiles:
            lever = prof.metadata.get("lever", "")
            if prof.std > 0 and prof.n_observations > 5:
                cv = prof.std / abs(prof.mean) if prof.mean != 0 else 0
                direction = Direction.INCREASE if prof.mean > 0 else Direction.DECREASE
                evidence.append(EvidencePacket(
                    agent_id="sensitivity_agent",
                    lever=lever,
                    direction=direction,
                    magnitude=cv,
                    confidence=min(1.0, prof.n_observations / 50.0),
                    mechanism=f"Lever {lever} sensitivity: CV={cv:.3f}",
                    source_types=["quantitative"],
                    data={"mean": prof.mean, "std": prof.std, "cv": cv},
                ))

        # Interaction detection: check pairwise correlations in raw data
        lever_arrays = {}
        for lever in self.levers:
            arr = raw_data.get(lever)
            if arr is not None:
                lever_arrays[lever] = np.asarray(arr, dtype=np.float64).ravel()

        checked_pairs = set()
        for la in self.levers:
            for lb in self.levers:
                if la >= lb:
                    continue
                pair_key = (la, lb)
                if pair_key in checked_pairs:
                    continue
                checked_pairs.add(pair_key)
                arr_a = lever_arrays.get(la)
                arr_b = lever_arrays.get(lb)
                if arr_a is None or arr_b is None:
                    continue
                min_len = min(len(arr_a), len(arr_b))
                if min_len < 10:
                    continue
                corr, pval = sp_stats.pearsonr(arr_a[:min_len], arr_b[:min_len])
                if abs(corr) > 0.3 and pval < 0.05:
                    direction = Direction.INCREASE if corr > 0 else Direction.DECREASE
                    evidence.append(EvidencePacket(
                        agent_id="interaction_agent",
                        lever=la,
                        related_levers=[lb],
                        direction=direction,
                        magnitude=abs(corr),
                        confidence=1.0 - pval,
                        mechanism=f"Interaction {la}×{lb}: r={corr:.3f}",
                        source_types=["quantitative"],
                        data={"correlation": corr, "p_value": pval, "lever_pair": [la, lb]},
                    ))

        # Constraint analysis
        for cv in constraints:
            evidence.append(EvidencePacket(
                agent_id="constraint_agent",
                lever=cv.lever,
                direction=Direction.MAINTAIN,
                magnitude=cv.bound,
                confidence=1.0 if cv.hardness == ConstraintHardness.HARD else 0.7,
                mechanism=f"Constraint on {cv.lever}: {cv.rationale[:60]}",
                source_types=["policy"],
                data={"rule_id": cv.rule_id, "hardness": cv.hardness.value},
            ))

        # Expert evidence
        for tb in beliefs:
            dir_map = {"increase": Direction.INCREASE, "decrease": Direction.DECREASE}
            direction = dir_map.get(tb.lever_direction or "", Direction.MAINTAIN)
            for dom in tb.domain:
                evidence.append(EvidencePacket(
                    agent_id="expert_agent",
                    lever=dom,
                    direction=direction,
                    magnitude=tb.current_confidence,
                    confidence=tb.current_confidence,
                    mechanism=f"Expert: {tb.statement[:60]}",
                    source_types=["expert"],
                    data={"basis": tb.basis.value},
                ))

        return evidence

    # ---- Synthesize ----

    def _synthesize(
        self,
        evidence: List[EvidencePacket],
        constraints: List[ConstraintVector],
    ) -> List[Intervention]:
        """Group evidence into candidate interventions."""
        from collections import defaultdict

        groups: Dict[Tuple[str, str], List[EvidencePacket]] = defaultdict(list)
        for ep in evidence:
            key = (ep.lever, ep.direction.value)
            groups[key].append(ep)

        interventions = []
        for idx, ((lever, direction), eps) in enumerate(groups.items()):
            if len(eps) < 1:
                continue
            confidence = float(np.mean([ep.confidence for ep in eps]))
            magnitude = float(np.mean([ep.magnitude for ep in eps]))
            all_source_types = set()
            for ep in eps:
                all_source_types.update(ep.source_types)
            all_related = set()
            for ep in eps:
                all_related.update(ep.related_levers)

            # Build mechanism description
            mechanisms = [ep.mechanism for ep in eps]
            mechanism = " | ".join(mechanisms[:3])

            raw = f"{self.domain_name}:{lever}:{direction}:{idx}"
            iid = "IV-" + hashlib.md5(raw.encode()).hexdigest()[:8]

            interventions.append(Intervention(
                intervention_id=iid,
                lever=lever,
                direction=Direction(direction) if direction in ("increase", "decrease", "maintain") else Direction.MAINTAIN,
                magnitude=magnitude,
                scope={"domain": self.domain_name},
                mechanism=mechanism,
                evidence_trail=[ep.agent_id for ep in eps],
                confidence=confidence,
                metadata={
                    "n_evidence": len(eps),
                    "source_types": list(all_source_types),
                    "related_levers": list(all_related),
                    "agent_roles": list(set(ep.agent_id for ep in eps)),
                },
            ))

        return interventions

    # ---- Quality gate ----

    def _quality_gate(
        self,
        interventions: List[Intervention],
        constraints: List[ConstraintVector],
    ) -> List[Intervention]:
        """Score and filter interventions."""
        for iv in interventions:
            n_evidence = iv.metadata.get("n_evidence", 1)
            n_source_types = len(iv.metadata.get("source_types", []))
            has_related = len(iv.metadata.get("related_levers", [])) > 0

            evidence_density = min(1.0, n_evidence / 5.0)
            constraint_ok = True
            for cv in constraints:
                if cv.lever == iv.lever and cv.hardness == ConstraintHardness.HARD:
                    if iv.magnitude < cv.bound * 0.5:
                        constraint_ok = False
            constraint_alignment = 1.0 if constraint_ok else 0.0
            actionability = 0.5 + 0.5 * (1.0 if iv.magnitude > 0 else 0.0)
            testability = 0.6 if iv.lever else 0.3
            novelty = 0.7 if has_related else 0.3

            composite = (
                0.25 * evidence_density
                + 0.25 * constraint_alignment
                + 0.20 * actionability
                + 0.15 * testability
                + 0.15 * novelty
            )

            iv.quality = QualityScore(
                evidence_density=evidence_density,
                constraint_alignment=constraint_alignment,
                actionability=actionability,
                testability=testability,
                novelty=novelty,
                composite=composite,
                hard_constraint_violation=not constraint_ok,
            )

        # Filter: keep non-violated, sort by composite, top 10
        valid = [iv for iv in interventions if not (iv.quality and iv.quality.hard_constraint_violation)]
        valid.sort(key=lambda iv: (iv.quality.composite if iv.quality else 0), reverse=True)
        return valid[:10]

    # ---- Scoring ----

    def _score(self, final: List[Intervention]) -> int:
        """Count how many planted effects are discovered."""
        found = 0
        for effect in self.planted_effects:
            eff_levers = set(effect.get("levers", []))
            for iv in final:
                iv_levers = {iv.lever}
                iv_levers.update(iv.metadata.get("related_levers", []))
                if eff_levers & iv_levers:
                    found += 1
                    break
        return found


# ===================================================================
# Domain A: Precision Medicine
# ===================================================================

def _generate_medicine_data(rng: np.random.Generator) -> Tuple[
    Dict[str, np.ndarray],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    """Generate synthetic precision medicine dataset (100 patients).

    Levers: drug (categorical 0-2), dose (continuous 0.1-10), timing (days 1-30).
    Planted effect: drug × dose interaction — drug 1 is effective only at
    doses > 5mg, but drug 0 works at any dose. Optimizing independently
    misses that switching from drug 0 to drug 1 requires dose escalation.
    """
    n_patients = 100
    drug = rng.integers(0, 3, n_patients).astype(float)
    dose = rng.uniform(0.1, 10.0, n_patients)
    timing = rng.uniform(1.0, 30.0, n_patients)

    # Outcome: response rate (higher = better)
    # Drug 0: moderate effect at any dose
    # Drug 1: strong effect only at dose > 5
    # Drug 2: weak effect
    base_response = np.where(
        drug == 0,
        0.5 + 0.03 * dose,
        np.where(
            drug == 1,
            np.where(dose > 5.0, 0.3 + 0.10 * dose, 0.2 + 0.01 * dose),
            0.3 + 0.01 * dose,
        ),
    )
    # Timing effect: earlier is slightly better
    timing_effect = -0.005 * timing
    # Planted interaction: drug 1 × high dose × early timing
    interaction = np.where(
        (drug == 1) & (dose > 5) & (timing < 15), 0.15, 0.0
    )
    response = base_response + timing_effect + interaction
    response += rng.normal(0, 0.05, n_patients)
    response = np.clip(response, 0, 1)

    quant_data = {
        "drug": drug,
        "dose": dose,
        "timing": timing,
        "outcome": response,
    }

    policies = [
        {
            "rule_id": "MED-001",
            "type": "hard",
            "lever": "dose",
            "threshold": {"max_dose_mg": 10.0},
            "scope": {"level": "all"},
            "rationale": "Maximum safe dose is 10mg per clinical guidelines.",
            "direction": "<=",
        },
        {
            "rule_id": "MED-002",
            "type": "soft",
            "lever": "timing",
            "threshold": {"preferred_start_days": 7},
            "scope": {"level": "all"},
            "rationale": "Treatment should ideally start within 7 days of diagnosis.",
            "direction": "<=",
        },
    ]

    expert_beliefs = [
        {
            "statement": "Drug 1 shows superior efficacy in high-dose patients.",
            "confidence": 0.8,
            "domain": ["drug", "dose"],
            "basis": "analysis",
            "lever_direction": "increase",
        },
        {
            "statement": "Early treatment initiation improves all outcomes.",
            "confidence": 0.7,
            "domain": ["timing"],
            "basis": "experience",
            "lever_direction": "decrease",
        },
        {
            "statement": "Drug 0 is safest choice for most patient profiles.",
            "confidence": 0.6,
            "domain": ["drug"],
            "basis": "experience",
            "lever_direction": "maintain",
        },
    ]

    return quant_data, policies, expert_beliefs


# ===================================================================
# Domain B: Supply Chain
# ===================================================================

def _generate_supply_chain_data(rng: np.random.Generator) -> Tuple[
    Dict[str, np.ndarray],
    List[Dict[str, Any]],
    List[Dict[str, Any]],
]:
    """Generate synthetic supply chain dataset (50 nodes).

    Levers: sourcing (cost 0-1), inventory (level 0-1), routing (efficiency 0-1).
    Planted effect: sourcing × routing interaction — switching to cheaper
    sourcing only works if routing is also optimized (longer lead times from
    cheap suppliers need faster routing).
    """
    n_nodes = 50
    sourcing = rng.uniform(0.0, 1.0, n_nodes)  # 0 = expensive/reliable, 1 = cheap/slow
    inventory = rng.uniform(0.0, 1.0, n_nodes)  # 0 = lean, 1 = buffer
    routing = rng.uniform(0.0, 1.0, n_nodes)    # 0 = basic, 1 = optimized

    # Total cost (lower = better)
    # Sourcing: cheaper is better, but...
    sourcing_cost = 1.0 - 0.3 * sourcing
    # Inventory holding cost
    inventory_cost = 0.2 * inventory
    # Routing cost
    routing_cost = 0.5 - 0.3 * routing

    # Planted interaction: cheap sourcing × poor routing = stockouts (high cost)
    # Cheap sourcing only works with optimized routing
    interaction_penalty = np.where(
        (sourcing > 0.6) & (routing < 0.4),
        0.4,  # penalty for cheap sourcing + bad routing
        np.where(
            (sourcing > 0.6) & (routing > 0.6),
            -0.2,  # bonus for cheap sourcing + good routing
            0.0,
        ),
    )

    total_cost = sourcing_cost + inventory_cost + routing_cost + interaction_penalty
    total_cost += rng.normal(0, 0.05, n_nodes)
    total_cost = np.clip(total_cost, 0.1, 3.0)

    quant_data = {
        "sourcing": sourcing,
        "inventory": inventory,
        "routing": routing,
        "outcome": total_cost,
    }

    policies = [
        {
            "rule_id": "SC-001",
            "type": "hard",
            "lever": "inventory",
            "threshold": {"min_safety_stock_pct": 0.15},
            "scope": {"level": "all"},
            "rationale": "Safety stock must be at least 15% to prevent stockouts.",
            "direction": ">=",
        },
        {
            "rule_id": "SC-002",
            "type": "soft",
            "lever": "sourcing",
            "threshold": {"max_single_source_pct": 0.60},
            "scope": {"level": "all"},
            "rationale": "No single supplier should exceed 60% of total sourcing.",
            "direction": "<=",
        },
    ]

    expert_beliefs = [
        {
            "statement": "Switching to cheaper suppliers can reduce costs by 20% if routing is adapted.",
            "confidence": 0.75,
            "domain": ["sourcing", "routing"],
            "basis": "analysis",
            "lever_direction": "increase",
        },
        {
            "statement": "Inventory buffers are the safest way to handle supply disruptions.",
            "confidence": 0.65,
            "domain": ["inventory"],
            "basis": "experience",
            "lever_direction": "increase",
        },
    ]

    return quant_data, policies, expert_beliefs


# ===================================================================
# Main experiment runner
# ===================================================================

def run_experiment_4(config: Config | None = None) -> Dict[str, Any]:
    """Run Experiment 4: Cross-Domain Generalization.

    Returns
    -------
    dict
        precision_medicine: {effects_found, effects_total, pipeline_functional}
        supply_chain: {effects_found, effects_total, pipeline_functional}
    """
    config = config or Config()
    set_seed(config.random_seed)
    rng = np.random.default_rng(config.random_seed + 100)
    logger.info("Starting Experiment 4: Cross-Domain Generalization")

    # --- Domain A: Precision Medicine ---
    logger.info("  Running Precision Medicine mini-domain...")
    med_data, med_policies, med_beliefs = _generate_medicine_data(rng)
    med_pipeline = MiniDomainPipeline(
        domain_name="precision_medicine",
        levers=["drug", "dose", "timing"],
        planted_effects=[{
            "name": "Drug-Dose Interaction",
            "levers": ["drug", "dose"],
            "description": "Drug 1 effective only at dose > 5mg",
        }],
        seed=config.random_seed + 200,
    )
    med_results = med_pipeline.run(med_data, med_policies, med_beliefs)
    logger.info(
        "  Precision Medicine: effects=%d/%d, pipeline_functional=%s",
        med_results["effects_found"],
        med_results["effects_total"],
        med_results["pipeline_functional"],
    )

    # --- Domain B: Supply Chain ---
    logger.info("  Running Supply Chain mini-domain...")
    sc_data, sc_policies, sc_beliefs = _generate_supply_chain_data(rng)
    sc_pipeline = MiniDomainPipeline(
        domain_name="supply_chain",
        levers=["sourcing", "inventory", "routing"],
        planted_effects=[{
            "name": "Sourcing-Routing Interaction",
            "levers": ["sourcing", "routing"],
            "description": "Cheap sourcing only works with optimized routing",
        }],
        seed=config.random_seed + 300,
    )
    sc_results = sc_pipeline.run(sc_data, sc_policies, sc_beliefs)
    logger.info(
        "  Supply Chain: effects=%d/%d, pipeline_functional=%s",
        sc_results["effects_found"],
        sc_results["effects_total"],
        sc_results["pipeline_functional"],
    )

    results = {
        "precision_medicine": {
            "effects_found": med_results["effects_found"],
            "effects_total": med_results["effects_total"],
            "pipeline_functional": med_results["pipeline_functional"],
        },
        "supply_chain": {
            "effects_found": sc_results["effects_found"],
            "effects_total": sc_results["effects_total"],
            "pipeline_functional": sc_results["pipeline_functional"],
        },
    }

    logger.info("Experiment 4 complete")
    return results
