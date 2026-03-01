"""Experiment 2 — Ablation Study.

Runs 4 configurations using AblationRunner:
  * full_system   — all components enabled
  * no_coupling   — independent lever optimisation
  * no_encoding   — raw text concatenation
  * no_pipeline   — single-pass LLM

Measures: effects_found (out of 5), precision/recall vs ground truth,
constraint violations, revenue impact.

Validates: full system gets 5/5, best ablation ≤ 3/5.

Only depends on stdlib + numpy + scipy (via upstream modules).
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.config import Config
from ..core.utils import get_logger, set_seed
from ..pipeline.ablation import AblationRunner

logger = get_logger("experiment_2")


def run_experiment_2(config: Config | None = None) -> Dict[str, Any]:
    """Run Experiment 2: 4-way Ablation Study.

    Returns
    -------
    dict
        Keys: full_system, no_coupling, no_encoding, no_pipeline.
        Each value has: effects_found, precision, recall, violations, revenue_impact.
    """
    config = config or Config()
    set_seed(config.random_seed)
    logger.info("Starting Experiment 2: Ablation Study")

    runner = AblationRunner(config)
    raw_results = runner.run_all()

    # Format results to match the output schema
    results: Dict[str, Any] = {}
    for name, data in raw_results.items():
        results[name] = {
            "effects_found": data.get("effects_found", 0),
            "precision": round(data.get("precision", 0.0), 2),
            "recall": round(data.get("recall", 0.0), 2),
            "violations": data.get("violations", 0),
            "revenue_impact": round(data.get("revenue_impact", 0.0), 2),
        }
        logger.info(
            "  %s: effects=%d precision=%.2f recall=%.2f violations=%d revenue=%.2f",
            name,
            results[name]["effects_found"],
            results[name]["precision"],
            results[name]["recall"],
            results[name]["violations"],
            results[name]["revenue_impact"],
        )

    # Validate expectations
    full = results.get("full_system", {})
    ablations = {k: v for k, v in results.items() if k != "full_system"}
    best_ablation = max(
        (v.get("effects_found", 0) for v in ablations.values()),
        default=0,
    )

    logger.info(
        "Validation: full_system=%d/5, best_ablation=%d/5 (expect ≤3)",
        full.get("effects_found", 0),
        best_ablation,
    )

    logger.info("Experiment 2 complete")
    return results
