"""Process output/results.json into paper-ready statistics, tables, and findings."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


class ResultsAnalyzer:
    """Loads experiment results and computes paper-ready statistics."""

    def __init__(self, results_path: str | Path | None = None):
        if results_path is None:
            results_path = Path(__file__).resolve().parents[2] / "output" / "results.json"
        self.results_path = Path(results_path)
        with open(self.results_path) as f:
            self.raw: Dict[str, Any] = json.load(f)
        self.scenario = self.raw["scenario"]
        self.experiments = self.raw["experiments"]
        self.top_interventions = self.raw["top_interventions"]
        self.metadata = self.raw.get("metadata", {})
        self.discovery_text = self.raw.get("discovery_text", "")

    # ------------------------------------------------------------------
    # Scenario stats
    # ------------------------------------------------------------------
    def scenario_stats(self) -> Dict[str, Any]:
        s = self.scenario
        return {
            "name": s["name"],
            "n_skus": s["skus"],
            "n_stores": s["stores"],
            "n_weeks": s["weeks"],
            "n_levers": len(s["levers"]),
            "levers": s["levers"],
            "n_knowledge_sources": len(s["knowledge_sources"]),
            "knowledge_sources": s["knowledge_sources"],
            "decision_space": s["decision_space_size"],
        }

    # ------------------------------------------------------------------
    # Encoding experiment
    # ------------------------------------------------------------------
    def encoding_stats(self) -> Dict[str, Any]:
        enc = self.experiments["encoding_validation"]
        fidelity = enc["fidelity_scores"]
        cross = enc["cross_type_query_success"]
        return {
            "fidelity": fidelity,
            "avg_fidelity": round(sum(fidelity.values()) / len(fidelity), 3),
            "cross_type": cross,
            "full_system_accuracy": cross["full_system"],
            "raw_concat_accuracy": cross["raw_concatenation"],
            "llm_baseline_accuracy": cross["llm_baseline"],
            "conflicts_detected": enc["conflicts_detected"],
            "conflicts_total": enc["conflicts_total"],
            "conflict_details": enc.get("conflict_details", []),
        }

    # ------------------------------------------------------------------
    # Ablation experiment
    # ------------------------------------------------------------------
    def ablation_stats(self) -> Dict[str, Any]:
        abl = self.experiments["ablation"]
        configs = ["full_system", "no_coupling", "no_encoding", "no_pipeline"]
        table_rows: List[Dict[str, Any]] = []
        for cfg in configs:
            d = abl[cfg]
            table_rows.append({
                "config": cfg,
                "effects_found": d["effects_found"],
                "precision": d["precision"],
                "recall": d["recall"],
                "violations": d["violations"],
                "revenue_impact": d["revenue_impact"],
            })
        full = abl["full_system"]
        best_ablation = max(
            (abl[c]["effects_found"] for c in configs if c != "full_system"),
            default=0,
        )
        return {
            "table": table_rows,
            "full_effects": full["effects_found"],
            "best_ablation_effects": best_ablation,
            "full_precision": full["precision"],
            "full_recall": full["recall"],
            "full_violations": full["violations"],
        }

    # ------------------------------------------------------------------
    # Pipeline reduction
    # ------------------------------------------------------------------
    def pipeline_stats(self) -> Dict[str, Any]:
        pipe = self.experiments["pipeline_reduction"]
        stages = [
            ("Input Space", pipe["stage_0_input"]),
            ("Diagnostic Agents", pipe["stage_1_diagnostic"]),
            ("Causal Synthesis", pipe["stage_2_synthesis"]),
            ("Quality Gate", pipe["stage_3_quality_gate"]),
        ]
        coverage = pipe["ground_truth_coverage_per_stage"]
        return {
            "stages": stages,
            "coverage": coverage,
            "compression_ratio": pipe["stage_0_input"] / max(pipe["stage_3_quality_gate"], 1),
            "final_count": pipe["stage_3_quality_gate"],
        }

    # ------------------------------------------------------------------
    # Generalization
    # ------------------------------------------------------------------
    def generalization_stats(self) -> Dict[str, Any]:
        gen = self.experiments["generalization"]
        domains = []
        for name, data in gen.items():
            domains.append({
                "domain": name.replace("_", " ").title(),
                "effects_found": data["effects_found"],
                "effects_total": data["effects_total"],
                "pipeline_functional": data["pipeline_functional"],
            })
        return {"domains": domains, "all_passed": all(d["pipeline_functional"] for d in domains)}

    # ------------------------------------------------------------------
    # Top interventions
    # ------------------------------------------------------------------
    def intervention_stats(self) -> List[Dict[str, Any]]:
        return self.top_interventions

    # ------------------------------------------------------------------
    # Summary for abstract / intro
    # ------------------------------------------------------------------
    def paper_summary(self) -> Dict[str, Any]:
        enc = self.encoding_stats()
        abl = self.ablation_stats()
        pipe = self.pipeline_stats()
        gen = self.generalization_stats()
        return {
            "effects_discovered": abl["full_effects"],
            "effects_total": 5,
            "cross_type_accuracy": enc["full_system_accuracy"],
            "baseline_accuracy": enc["raw_concat_accuracy"],
            "pipeline_input": f"$10^{{18}}$",
            "pipeline_output": pipe["final_count"],
            "compression_ratio": f"{pipe['compression_ratio']:.0e}",
            "constraint_violations": abl["full_violations"],
            "generalization_domains": len(gen["domains"]),
            "generalization_passed": sum(1 for d in gen["domains"] if d["pipeline_functional"]),
            "conflicts_detected": enc["conflicts_detected"],
            "conflicts_total": enc["conflicts_total"],
        }
