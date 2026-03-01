"""Configuration and hyperparameters for the coupled-decisions framework.

All tuneable parameters live here so experiments are reproducible and
ablations only require config changes.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict


@dataclass
class Config:
    """Central configuration for the BevCo RGM scenario."""

    # -----------------------------------------------------------------------
    # Scenario dimensions
    # -----------------------------------------------------------------------
    n_skus: int = 50
    n_categories: int = 5
    n_stores: int = 200
    n_regions: int = 4
    n_weeks: int = 104  # 2 years
    n_store_clusters: int = 20

    # -----------------------------------------------------------------------
    # Lever ranges
    # -----------------------------------------------------------------------
    price_min: float = 0.50
    price_max: float = 8.00
    promo_types: int = 12
    promo_max_per_month: int = 4
    promo_depth_min: float = 0.10  # 10 %
    promo_depth_max: float = 0.50  # 50 %
    facings_min: int = 1
    facings_max: int = 8
    pack_sizes_min: int = 3
    pack_sizes_max: int = 6

    # -----------------------------------------------------------------------
    # Noise levels (for data generation)
    # -----------------------------------------------------------------------
    elasticity_noise_std: float = 0.15
    sales_noise_std: float = 0.10
    market_share_noise_std: float = 0.05
    expert_confidence_noise: float = 0.10

    # -----------------------------------------------------------------------
    # Multi-collinearity targets (Pearson ρ)
    # -----------------------------------------------------------------------
    collinearity_price_promotion: float = -0.60
    collinearity_assortment_distribution: float = 0.50
    collinearity_promotion_display: float = 0.70
    collinearity_packsize_price: float = 0.85

    # -----------------------------------------------------------------------
    # Agent thresholds
    # -----------------------------------------------------------------------
    elasticity_significance: float = 0.05  # p-value threshold
    interaction_effect_min: float = 0.02   # minimum detectable interaction
    constraint_slack_tolerance: float = 0.01
    temporal_break_sensitivity: float = 2.0  # σ multiplier for CUSUM
    portfolio_cannibalization_threshold: float = 0.05

    # -----------------------------------------------------------------------
    # Pipeline parameters
    # -----------------------------------------------------------------------
    diagnostic_top_k: int = 1000   # candidates after Stage 1
    synthesis_top_k: int = 50      # interventions after Stage 2
    quality_gate_top_k: int = 10   # final recommendations

    # Quality gate weights
    quality_weight_evidence_density: float = 0.25
    quality_weight_constraint_alignment: float = 0.25
    quality_weight_actionability: float = 0.20
    quality_weight_testability: float = 0.15
    quality_weight_novelty: float = 0.15

    # Minimum margin threshold (hard constraint)
    min_margin_pct: float = 0.25  # 25 %

    # -----------------------------------------------------------------------
    # Encoding parameters
    # -----------------------------------------------------------------------
    confidence_interval_level: float = 0.95
    expert_decay_rate: float = 0.05    # per-week exponential decay
    basis_quality_weights: Dict[str, float] = field(default_factory=lambda: {
        "analysis": 1.0,
        "experience": 0.7,
        "intuition": 0.4,
    })

    # -----------------------------------------------------------------------
    # Reproducibility
    # -----------------------------------------------------------------------
    random_seed: int = 42

    # -----------------------------------------------------------------------
    # Ground-truth effect flags (toggle for ablation)
    # -----------------------------------------------------------------------
    enable_price_promotion_trap: bool = True
    enable_assortment_distribution_synergy: bool = True
    enable_pack_price_cannibalization: bool = True
    enable_cross_source_signal: bool = True
    enable_constraint_coupling_conflict: bool = True

    # -----------------------------------------------------------------------
    # Serialization helpers
    # -----------------------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Config":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def quality_weights(self) -> Dict[str, float]:
        """Return quality gate weights as a dict matching QualityScore fields."""
        return {
            "evidence_density": self.quality_weight_evidence_density,
            "constraint_alignment": self.quality_weight_constraint_alignment,
            "actionability": self.quality_weight_actionability,
            "testability": self.quality_weight_testability,
            "novelty": self.quality_weight_novelty,
        }
