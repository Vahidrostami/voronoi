"""Master experiment runner — run_all.py.

Generates data, runs all 4 experiments, collects results, and writes
output/results.json in the format specified by PROMPT.md.

Usage:
    python -m demos.coupled_decisions.src.experiments.run_all
    # or from the coupled-decisions directory:
    python -m src.experiments.run_all

Only depends on stdlib + numpy + scipy (via upstream modules).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from ..core.config import Config
from ..core.utils import get_logger, save_json, set_seed, output_dir
from ..pipeline.runner import PipelineRunner

from .experiment_1_encoding import run_experiment_1
from .experiment_2_ablation import run_experiment_2
from .experiment_3_pipeline import run_experiment_3
from .experiment_4_generalization import run_experiment_4

logger = get_logger("run_all")


def _build_top_interventions(pipeline_results: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract top interventions from pipeline run for the results JSON."""
    interventions = pipeline_results.get("interventions", [])
    top = []
    for rank, iv in enumerate(interventions[:10], start=1):
        quality = iv.get("quality", {})
        lever = iv.get("lever", "")
        direction = iv.get("direction", "maintain")
        scope = iv.get("scope", {})
        mechanism = iv.get("mechanism", "")

        scope_str = ", ".join(
            f"{k}: {v}" for k, v in scope.items() if v
        ) if isinstance(scope, dict) else str(scope)

        top.append({
            "rank": rank,
            "lever": lever,
            "direction": direction,
            "scope": scope_str or "all",
            "mechanism": mechanism[:100],
            "quality_score": round(quality.get("composite", 0.0), 2),
            "evidence_density": round(quality.get("evidence_density", 0.0), 2),
            "constraint_alignment": round(quality.get("constraint_alignment", 0.0), 2),
            "revenue_impact": f"+{round(iv.get('magnitude', 0.0) * 100, 1)}%",
        })
    return top


def run_all_experiments(config: Config | None = None) -> Dict[str, Any]:
    """Run all 4 experiments and assemble the final results.json.

    Parameters
    ----------
    config : Config, optional
        Configuration; defaults to standard BevCo config.

    Returns
    -------
    dict
        The complete results.json structure.
    """
    config = config or Config()
    set_seed(config.random_seed)
    t_start = time.time()

    logger.info("=" * 60)
    logger.info("COUPLED DECISIONS — FULL EXPERIMENT SUITE")
    logger.info("=" * 60)

    # --- Run the full pipeline first (needed for top interventions) ---
    logger.info("Running full pipeline for top interventions...")
    pipeline_runner = PipelineRunner(config)
    pipeline_results = pipeline_runner.run()
    logger.info("Full pipeline complete")

    # --- Experiment 1: Encoding Validation ---
    logger.info("-" * 40)
    exp1 = run_experiment_1(config)

    # --- Experiment 2: Ablation Study ---
    logger.info("-" * 40)
    exp2 = run_experiment_2(config)

    # --- Experiment 3: Progressive Reduction ---
    logger.info("-" * 40)
    exp3 = run_experiment_3(config)

    # --- Experiment 4: Generalization ---
    logger.info("-" * 40)
    exp4 = run_experiment_4(config)

    # --- Assemble results.json ---
    top_interventions = _build_top_interventions(pipeline_results)

    # Build discovery text
    gt = pipeline_results.get("ground_truth", {})
    discovered = gt.get("discovered_effects", [])
    n_found = gt.get("effects_found", 0)
    n_total = gt.get("effects_total", 5)

    discovery_text = (
        f"The full coupled-decisions pipeline discovered {n_found} of {n_total} "
        f"planted ground-truth interaction effects. "
        f"Discovered: {', '.join(discovered) if discovered else 'none'}. "
        f"The progressive reduction pipeline compressed a ~10^18 combinatorial "
        f"decision space to {exp3.get('stage_3_quality_gate', 0)} final "
        f"recommendations while maintaining ground-truth coverage. "
        f"Cross-domain generalization succeeded in "
        f"{'2' if (exp4.get('precision_medicine', {}).get('effects_found', 0) > 0 and exp4.get('supply_chain', {}).get('effects_found', 0) > 0) else '1 or fewer'}/2 "
        f"secondary domains."
    )

    results = {
        "scenario": {
            "name": "BevCo Revenue Growth Management",
            "skus": config.n_skus,
            "stores": config.n_stores,
            "weeks": config.n_weeks,
            "levers": ["pricing", "promotion", "assortment", "distribution", "pack_price"],
            "knowledge_sources": ["quantitative", "policy", "expert"],
            "decision_space_size": "~10^18",
        },
        "experiments": {
            "encoding_validation": exp1,
            "ablation": exp2,
            "pipeline_reduction": exp3,
            "generalization": exp4,
        },
        "top_interventions": top_interventions,
        "discovery_text": discovery_text,
        "metadata": {
            "total_elapsed_seconds": round(time.time() - t_start, 1),
            "random_seed": config.random_seed,
            "python_version": _python_version(),
        },
    }

    # --- Write to output/results.json ---
    out = output_dir()
    results_path = save_json(results, out / "results.json")
    logger.info("Results written to %s", results_path)

    logger.info("=" * 60)
    logger.info("ALL EXPERIMENTS COMPLETE in %.1fs", time.time() - t_start)
    logger.info("=" * 60)

    return results


def _python_version() -> str:
    """Return the Python version string."""
    import sys
    return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    results = run_all_experiments()
    print(json.dumps(results, indent=2, default=str))
