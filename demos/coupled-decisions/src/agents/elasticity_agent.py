"""Elasticity diagnostic agent.

Analyzes own-price and cross-price elasticities per SKU × region.
Identifies significant lever sensitivities. Prunes insensitive
combinations from the candidate space.

Only depends on stdlib + numpy + scipy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np
from scipy import stats as sp_stats

from ..core.config import Config
from ..core.types import (
    Direction,
    EvidencePacket,
    StatisticalProfile,
)


class ElasticityAgent:
    """Diagnostic agent for own-price and cross-price elasticity analysis."""

    AGENT_ID = "elasticity_agent"

    def __init__(self, config: Config, encoded_knowledge: Dict[str, Any]) -> None:
        self.config = config
        self.encoded_knowledge = encoded_knowledge
        self._evidence: List[EvidencePacket] = []
        self._pruned: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def diagnose(self) -> List[EvidencePacket]:
        """Run elasticity diagnostic, return evidence packets."""
        self._evidence = []
        self._pruned = {"sensitive": [], "insensitive": [], "cross_signals": []}

        elasticities = self.encoded_knowledge.get("elasticities", {})
        profiles = self._get_profiles()

        if elasticities:
            self._analyze_own_price_elasticities(elasticities)
            self._analyze_cross_price_elasticities(elasticities)
        if profiles:
            self._analyze_profile_sensitivities(profiles)

        return self._evidence

    def get_pruned_space(self) -> Dict[str, Any]:
        """Return the reduced candidate space."""
        if not self._evidence:
            self.diagnose()
        return self._pruned

    # ------------------------------------------------------------------
    # Internal analysis methods
    # ------------------------------------------------------------------

    def _get_profiles(self) -> List[Dict[str, Any]]:
        """Extract statistical profiles from encoded knowledge."""
        raw = self.encoded_knowledge.get("quantitative", [])
        return raw if isinstance(raw, list) else []

    def _analyze_own_price_elasticities(
        self, elasticities: Dict[str, Any],
    ) -> None:
        """Analyze own-price elasticities per SKU × region."""
        sku_i = np.asarray(elasticities.get("sku_i", []))
        sku_j = np.asarray(elasticities.get("sku_j", []))
        regions = np.asarray(elasticities.get("region", []))
        elast_vals = np.asarray(elasticities.get("elasticity", []), dtype=np.float64)
        types = np.asarray(elasticities.get("type", []))

        if len(sku_i) == 0:
            return

        own_mask = types == "own"
        own_sku = sku_i[own_mask]
        own_region = regions[own_mask]
        own_elast = elast_vals[own_mask]

        unique_skus = np.unique(own_sku)
        unique_regions = np.unique(own_region)

        sig_threshold = self.config.elasticity_significance

        for sku in unique_skus:
            sku_mask = own_sku == sku
            sku_elast = own_elast[sku_mask]
            sku_regions = own_region[sku_mask]

            mean_elast = float(np.mean(sku_elast))
            std_elast = float(np.std(sku_elast, ddof=1)) if len(sku_elast) > 1 else 0.0
            n = len(sku_elast)

            # Test if elasticity is significantly different from zero
            if n > 1 and std_elast > 0:
                t_stat = mean_elast / (std_elast / np.sqrt(n))
                p_value = float(2 * sp_stats.t.sf(abs(t_stat), df=n - 1))
            else:
                p_value = 0.0 if abs(mean_elast) > 0.1 else 1.0

            is_significant = p_value < sig_threshold

            if is_significant:
                direction = Direction.DECREASE if mean_elast < -1.0 else Direction.MAINTAIN
                confidence = min(1.0, 1.0 - p_value)

                self._evidence.append(EvidencePacket(
                    agent_id=self.AGENT_ID,
                    lever="pricing",
                    direction=direction,
                    magnitude=abs(mean_elast),
                    confidence=confidence,
                    mechanism=(
                        f"SKU {sku} has significant own-price elasticity "
                        f"({mean_elast:.3f} ± {std_elast:.3f}, p={p_value:.4f}). "
                        f"{'Highly elastic' if abs(mean_elast) > 1.5 else 'Moderately elastic'}."
                    ),
                    source_types=["quantitative"],
                    data={
                        "sku_id": int(sku),
                        "mean_elasticity": mean_elast,
                        "std_elasticity": std_elast,
                        "p_value": p_value,
                        "n_regions": n,
                        "analysis_type": "own_price_elasticity",
                    },
                ))
                self._pruned["sensitive"].append({
                    "sku_id": int(sku),
                    "lever": "pricing",
                    "elasticity": mean_elast,
                    "p_value": p_value,
                })
            else:
                self._pruned["insensitive"].append({
                    "sku_id": int(sku),
                    "lever": "pricing",
                    "elasticity": mean_elast,
                    "p_value": p_value,
                    "reason": "own-price elasticity not significant",
                })

            # Check for regional heterogeneity
            if n >= 3 and std_elast > 0:
                cv = std_elast / abs(mean_elast) if abs(mean_elast) > 1e-9 else 0.0
                if cv > 0.3:
                    # Significant regional variation
                    min_region = sku_regions[np.argmin(sku_elast)]
                    max_region = sku_regions[np.argmax(sku_elast)]
                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever="pricing",
                        direction=Direction.MAINTAIN,
                        magnitude=cv,
                        confidence=0.7,
                        mechanism=(
                            f"SKU {sku} shows significant regional heterogeneity "
                            f"in own-price elasticity (CV={cv:.2f}). "
                            f"Most elastic in {min_region}, "
                            f"least in {max_region}. "
                            f"Regional pricing strategy warranted."
                        ),
                        source_types=["quantitative"],
                        data={
                            "sku_id": int(sku),
                            "coefficient_of_variation": cv,
                            "min_region": str(min_region),
                            "max_region": str(max_region),
                            "elasticity_by_region": {
                                str(r): float(e)
                                for r, e in zip(sku_regions, sku_elast)
                            },
                            "analysis_type": "regional_heterogeneity",
                        },
                    ))

    def _analyze_cross_price_elasticities(
        self, elasticities: Dict[str, Any],
    ) -> None:
        """Analyze cross-price elasticities to detect substitution/complement patterns."""
        sku_i = np.asarray(elasticities.get("sku_i", []))
        sku_j = np.asarray(elasticities.get("sku_j", []))
        regions = np.asarray(elasticities.get("region", []))
        elast_vals = np.asarray(elasticities.get("elasticity", []), dtype=np.float64)
        types = np.asarray(elasticities.get("type", []))

        if len(sku_i) == 0:
            return

        cross_mask = types == "cross"
        c_sku_i = sku_i[cross_mask]
        c_sku_j = sku_j[cross_mask]
        c_elast = elast_vals[cross_mask]
        c_region = regions[cross_mask]

        # Group by (sku_i, sku_j) pair
        pairs: Dict[tuple, List[float]] = {}
        for i, j, e in zip(c_sku_i, c_sku_j, c_elast):
            key = (int(i), int(j))
            pairs.setdefault(key, []).append(float(e))

        sig_threshold = self.config.elasticity_significance

        for (si, sj), values in pairs.items():
            vals = np.array(values)
            mean_cross = float(np.mean(vals))
            n = len(vals)

            if n > 1:
                std_cross = float(np.std(vals, ddof=1))
                if std_cross > 0:
                    t_stat = mean_cross / (std_cross / np.sqrt(n))
                    p_value = float(2 * sp_stats.t.sf(abs(t_stat), df=n - 1))
                else:
                    p_value = 0.0 if abs(mean_cross) > 0.05 else 1.0
            else:
                p_value = 0.0 if abs(mean_cross) > 0.1 else 1.0

            # Only report significant cross-elasticities
            if p_value < sig_threshold and abs(mean_cross) > 0.05:
                pattern = "substitution" if mean_cross > 0 else "complement"
                strength = "strong" if abs(mean_cross) > 0.3 else "moderate"

                self._evidence.append(EvidencePacket(
                    agent_id=self.AGENT_ID,
                    lever="pricing",
                    related_levers=["pack_price", "assortment"],
                    direction=Direction.MAINTAIN,
                    magnitude=abs(mean_cross),
                    confidence=min(1.0, 1.0 - p_value),
                    mechanism=(
                        f"SKU {si} → SKU {sj}: {strength} {pattern} "
                        f"(cross-ε={mean_cross:.3f}, p={p_value:.4f}). "
                        f"Price changes on SKU {si} will affect SKU {sj}."
                    ),
                    source_types=["quantitative"],
                    data={
                        "sku_i": si,
                        "sku_j": sj,
                        "mean_cross_elasticity": mean_cross,
                        "p_value": p_value,
                        "pattern": pattern,
                        "strength": strength,
                        "n_regions": n,
                        "analysis_type": "cross_price_elasticity",
                    },
                ))
                self._pruned["cross_signals"].append({
                    "sku_i": si,
                    "sku_j": sj,
                    "cross_elasticity": mean_cross,
                    "pattern": pattern,
                })

    def _analyze_profile_sensitivities(
        self, profiles: List[Dict[str, Any]],
    ) -> None:
        """Use StatisticalProfile data to identify lever sensitivities."""
        for entry in profiles:
            if isinstance(entry, dict):
                profile = entry.get("profile")
                key = entry.get("key", "")
                metadata = entry.get("metadata", {})
            elif isinstance(entry, StatisticalProfile):
                profile = entry
                key = ""
                metadata = {}
            else:
                continue

            if profile is None or not isinstance(profile, StatisticalProfile):
                continue

            if profile.n_observations < 10:
                continue

            # High variance → sensitive to lever changes
            if profile.std > 0 and abs(profile.mean) > 1e-9:
                cv = profile.std / abs(profile.mean)
                if cv > 0.25:
                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever=metadata.get("lever", "pricing"),
                        direction=Direction.MAINTAIN,
                        magnitude=cv,
                        confidence=min(0.9, 0.5 + 0.4 * min(1.0, profile.n_observations / 52)),
                        mechanism=(
                            f"High variability detected (CV={cv:.2f}) in "
                            f"{key or 'metric'}, suggesting sensitivity to "
                            f"lever changes. n={profile.n_observations}."
                        ),
                        source_types=["quantitative"],
                        data={
                            "key": key,
                            "coefficient_of_variation": cv,
                            "mean": profile.mean,
                            "std": profile.std,
                            "n_observations": profile.n_observations,
                            "analysis_type": "profile_sensitivity",
                        },
                    ))
