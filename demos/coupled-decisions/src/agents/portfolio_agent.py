"""Portfolio diagnostic agent.

Analyzes SKU-level portfolio effects: cannibalization, halo, and
substitution patterns. Identifies which assortment / pack-price changes
cascade to other SKUs. Outputs structured EvidencePackets.

Only depends on stdlib + numpy + scipy.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import stats as sp_stats

from ..core.config import Config
from ..core.types import (
    Direction,
    EvidencePacket,
    StatisticalProfile,
)


class PortfolioAgent:
    """Diagnostic agent for SKU-level portfolio effect analysis."""

    AGENT_ID = "portfolio_agent"

    def __init__(self, config: Config, encoded_knowledge: Dict[str, Any]) -> None:
        self.config = config
        self.encoded_knowledge = encoded_knowledge
        self._evidence: List[EvidencePacket] = []
        self._pruned: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def diagnose(self) -> List[EvidencePacket]:
        """Run portfolio diagnostic, return evidence packets."""
        self._evidence = []
        self._pruned = {
            "cannibalization_pairs": [],
            "halo_pairs": [],
            "substitution_groups": [],
            "cascade_risks": [],
        }

        sales = self.encoded_knowledge.get("sales", {})
        elasticities = self.encoded_knowledge.get("elasticities", {})

        if sales:
            self._analyze_cannibalization_from_sales(sales)
            self._analyze_halo_effects_from_sales(sales)
        if elasticities:
            self._analyze_substitution_from_elasticities(elasticities)
        if not sales and not elasticities:
            profiles = self.encoded_knowledge.get("quantitative", [])
            if profiles:
                self._analyze_portfolio_from_profiles(profiles)

        return self._evidence

    def get_pruned_space(self) -> Dict[str, Any]:
        """Return the reduced candidate space."""
        if not self._evidence:
            self.diagnose()
        return self._pruned

    # ------------------------------------------------------------------
    # Sales-based analysis
    # ------------------------------------------------------------------

    def _analyze_cannibalization_from_sales(
        self, sales: Dict[str, Any],
    ) -> None:
        """Detect cannibalization patterns from sales data.

        Looks for SKU pairs within the same category where one SKU's
        volume gain coincides with another's volume loss (negative
        correlation in detrended volume).
        """
        sku_ids = np.asarray(sales.get("sku_id", []))
        weeks = np.asarray(sales.get("week", []))
        units = np.asarray(sales.get("units_sold", []), dtype=np.float64)
        categories = np.asarray(sales.get("category", []))
        pack_sizes = np.asarray(sales.get("pack_size", []))

        if len(sku_ids) == 0:
            return

        unique_cats = np.unique(categories)
        threshold = self.config.portfolio_cannibalization_threshold

        for cat in unique_cats:
            cat_mask = categories == cat
            cat_skus = np.unique(sku_ids[cat_mask])

            if len(cat_skus) < 2:
                continue

            # Build weekly volume per SKU in this category
            unique_weeks = np.unique(weeks[cat_mask])
            n_weeks = len(unique_weeks)

            if n_weeks < 10:
                continue

            sku_weekly: Dict[int, np.ndarray] = {}
            sku_packs: Dict[int, int] = {}
            for sku in cat_skus:
                sku_cat_mask = cat_mask & (sku_ids == sku)
                vol = np.zeros(n_weeks)
                for wi, w in enumerate(unique_weeks):
                    w_mask = sku_cat_mask & (weeks == w)
                    vol[wi] = float(np.sum(units[w_mask]))
                sku_weekly[int(sku)] = vol

                # Dominant pack size for this SKU
                packs = pack_sizes[sku_cat_mask]
                if len(packs) > 0:
                    values, counts = np.unique(packs, return_counts=True)
                    sku_packs[int(sku)] = int(values[np.argmax(counts)])

            # Pairwise cannibalization check
            sku_list = list(sku_weekly.keys())
            for i in range(len(sku_list)):
                for j in range(i + 1, len(sku_list)):
                    si, sj = sku_list[i], sku_list[j]
                    vol_i = sku_weekly[si]
                    vol_j = sku_weekly[sj]

                    # Detrend: first difference
                    diff_i = np.diff(vol_i)
                    diff_j = np.diff(vol_j)

                    if len(diff_i) < 5:
                        continue

                    corr, p_val = sp_stats.pearsonr(diff_i, diff_j)

                    # Strong negative correlation = cannibalization
                    if corr < -threshold and p_val < 0.05:
                        pack_i = sku_packs.get(si, 0)
                        pack_j = sku_packs.get(sj, 0)

                        self._evidence.append(EvidencePacket(
                            agent_id=self.AGENT_ID,
                            lever="pack_price" if pack_i != pack_j else "assortment",
                            related_levers=["pricing", "assortment"],
                            direction=Direction.MAINTAIN,
                            magnitude=abs(corr),
                            confidence=min(0.9, 1.0 - p_val),
                            mechanism=(
                                f"Cannibalization in category {cat}: "
                                f"SKU {si} (pack={pack_i}) ↔ "
                                f"SKU {sj} (pack={pack_j}), "
                                f"Δvolume correlation={corr:.3f} (p={p_val:.4f}). "
                                f"Volume gains in one coincide with losses in the other."
                            ),
                            source_types=["quantitative"],
                            data={
                                "sku_i": si,
                                "sku_j": sj,
                                "category": str(cat),
                                "correlation": float(corr),
                                "p_value": float(p_val),
                                "pack_i": pack_i,
                                "pack_j": pack_j,
                                "n_weeks": int(n_weeks),
                                "analysis_type": "cannibalization",
                            },
                        ))
                        self._pruned["cannibalization_pairs"].append({
                            "sku_i": si,
                            "sku_j": sj,
                            "category": str(cat),
                            "correlation": float(corr),
                            "pack_i": pack_i,
                            "pack_j": pack_j,
                        })

    def _analyze_halo_effects_from_sales(
        self, sales: Dict[str, Any],
    ) -> None:
        """Detect halo effects: positive volume spillovers across SKU pairs.

        When one SKU gains volume and a nearby SKU also gains (strong
        positive correlation in volume changes), this is a halo effect.
        """
        sku_ids = np.asarray(sales.get("sku_id", []))
        weeks = np.asarray(sales.get("week", []))
        units = np.asarray(sales.get("units_sold", []), dtype=np.float64)
        categories = np.asarray(sales.get("category", []))

        if len(sku_ids) == 0:
            return

        unique_cats = np.unique(categories)

        for cat in unique_cats:
            cat_mask = categories == cat
            cat_skus = np.unique(sku_ids[cat_mask])

            if len(cat_skus) < 2:
                continue

            unique_weeks = np.unique(weeks[cat_mask])
            n_weeks = len(unique_weeks)
            if n_weeks < 10:
                continue

            # Build weekly volume per SKU
            sku_weekly: Dict[int, np.ndarray] = {}
            for sku in cat_skus:
                sku_mask = cat_mask & (sku_ids == sku)
                vol = np.zeros(n_weeks)
                for wi, w in enumerate(unique_weeks):
                    w_mask = sku_mask & (weeks == w)
                    vol[wi] = float(np.sum(units[w_mask]))
                sku_weekly[int(sku)] = vol

            # Pairwise halo check
            sku_list = list(sku_weekly.keys())
            for i in range(len(sku_list)):
                for j in range(i + 1, len(sku_list)):
                    si, sj = sku_list[i], sku_list[j]
                    diff_i = np.diff(sku_weekly[si])
                    diff_j = np.diff(sku_weekly[sj])

                    if len(diff_i) < 5:
                        continue

                    corr, p_val = sp_stats.pearsonr(diff_i, diff_j)

                    # Strong positive correlation in volume changes = halo
                    if corr > 0.4 and p_val < 0.05:
                        self._evidence.append(EvidencePacket(
                            agent_id=self.AGENT_ID,
                            lever="assortment",
                            related_levers=["distribution", "pricing"],
                            direction=Direction.INCREASE,
                            magnitude=corr,
                            confidence=min(0.85, 1.0 - p_val),
                            mechanism=(
                                f"Halo effect in category {cat}: "
                                f"SKU {si} ↔ SKU {sj}, "
                                f"Δvolume correlation={corr:.3f} (p={p_val:.4f}). "
                                f"Positive volume spillover — lifting one "
                                f"benefits the other."
                            ),
                            source_types=["quantitative"],
                            data={
                                "sku_i": si,
                                "sku_j": sj,
                                "category": str(cat),
                                "correlation": float(corr),
                                "p_value": float(p_val),
                                "n_weeks": int(n_weeks),
                                "analysis_type": "halo_effect",
                            },
                        ))
                        self._pruned["halo_pairs"].append({
                            "sku_i": si,
                            "sku_j": sj,
                            "category": str(cat),
                            "correlation": float(corr),
                        })

    # ------------------------------------------------------------------
    # Elasticity-based substitution analysis
    # ------------------------------------------------------------------

    def _analyze_substitution_from_elasticities(
        self, elasticities: Dict[str, Any],
    ) -> None:
        """Identify substitution groups from cross-price elasticity data."""
        sku_i = np.asarray(elasticities.get("sku_i", []))
        sku_j = np.asarray(elasticities.get("sku_j", []))
        elast = np.asarray(elasticities.get("elasticity", []), dtype=np.float64)
        types = np.asarray(elasticities.get("type", []))

        if len(sku_i) == 0:
            return

        cross_mask = types == "cross"
        c_i = sku_i[cross_mask]
        c_j = sku_j[cross_mask]
        c_e = elast[cross_mask]

        if len(c_i) == 0:
            return

        # Group by (i, j) and average across regions
        pair_elast: Dict[Tuple[int, int], List[float]] = {}
        for i, j, e in zip(c_i, c_j, c_e):
            key = (int(i), int(j))
            pair_elast.setdefault(key, []).append(float(e))

        # Find strong substitution pairs
        threshold = self.config.portfolio_cannibalization_threshold
        substitution_graph: Dict[int, List[Tuple[int, float]]] = {}

        for (si, sj), values in pair_elast.items():
            mean_e = float(np.mean(values))
            if mean_e > threshold:
                substitution_graph.setdefault(si, []).append((sj, mean_e))

                # Only emit evidence for strong substitution
                if mean_e > 0.15:
                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever="pricing",
                        related_levers=["assortment", "pack_price"],
                        direction=Direction.MAINTAIN,
                        magnitude=mean_e,
                        confidence=min(0.9, 0.5 + mean_e),
                        mechanism=(
                            f"Substitution: SKU {si} → SKU {sj}, "
                            f"cross-ε={mean_e:.3f}. A price increase on "
                            f"SKU {si} will shift demand to SKU {sj}. "
                            f"{'Strong' if mean_e > 0.3 else 'Moderate'} cascade risk."
                        ),
                        source_types=["quantitative"],
                        data={
                            "sku_i": si,
                            "sku_j": sj,
                            "mean_cross_elasticity": mean_e,
                            "n_observations": len(values),
                            "analysis_type": "substitution",
                        },
                    ))

        # Identify substitution clusters (connected components)
        visited: set = set()
        for root in substitution_graph:
            if root in visited:
                continue
            cluster: List[int] = []
            stack = [root]
            while stack:
                node = stack.pop()
                if node in visited:
                    continue
                visited.add(node)
                cluster.append(node)
                for neighbor, _ in substitution_graph.get(node, []):
                    if neighbor not in visited:
                        stack.append(neighbor)

            if len(cluster) >= 2:
                # Compute average within-cluster cross-elasticity
                within_elast = []
                for si in cluster:
                    for sj, e in substitution_graph.get(si, []):
                        if sj in cluster:
                            within_elast.append(e)

                avg_e = float(np.mean(within_elast)) if within_elast else 0.0

                self._pruned["substitution_groups"].append({
                    "skus": sorted(cluster),
                    "avg_cross_elasticity": avg_e,
                    "size": len(cluster),
                })

                if len(cluster) >= 3:
                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever="assortment",
                        related_levers=["pricing", "pack_price"],
                        direction=Direction.MAINTAIN,
                        magnitude=avg_e,
                        confidence=0.8,
                        mechanism=(
                            f"Substitution cluster of {len(cluster)} SKUs "
                            f"(IDs: {sorted(cluster)[:5]}{'...' if len(cluster) > 5 else ''}). "
                            f"Avg within-cluster cross-ε={avg_e:.3f}. "
                            f"Changes to any member will cascade."
                        ),
                        source_types=["quantitative"],
                        data={
                            "cluster_skus": sorted(cluster),
                            "avg_cross_elasticity": avg_e,
                            "cluster_size": len(cluster),
                            "analysis_type": "substitution_cluster",
                        },
                    ))

                    self._pruned["cascade_risks"].append({
                        "cluster": sorted(cluster),
                        "avg_cross_elasticity": avg_e,
                        "risk_level": "high" if avg_e > 0.3 else "moderate",
                    })

    # ------------------------------------------------------------------
    # Profile-based fallback
    # ------------------------------------------------------------------

    def _analyze_portfolio_from_profiles(
        self, profiles: List[Dict[str, Any]],
    ) -> None:
        """Detect portfolio effects from StatisticalProfiles.

        Uses residual correlation as a proxy when raw sales data is
        unavailable.
        """
        entries: List[Tuple[str, np.ndarray]] = []
        for entry in profiles:
            if isinstance(entry, dict):
                profile = entry.get("profile")
                key = entry.get("key", "")
            elif isinstance(entry, StatisticalProfile):
                profile = entry
                key = ""
            else:
                continue

            if not isinstance(profile, StatisticalProfile):
                continue
            if profile.residual and len(profile.residual) > 10:
                entries.append((key, np.array(profile.residual)))

        for i in range(len(entries)):
            for j in range(i + 1, len(entries)):
                key_a, res_a = entries[i]
                key_b, res_b = entries[j]
                min_len = min(len(res_a), len(res_b))
                if min_len < 10:
                    continue

                corr, p_val = sp_stats.pearsonr(
                    res_a[:min_len], res_b[:min_len],
                )

                if p_val < 0.05 and abs(corr) > 0.3:
                    if corr < 0:
                        pattern = "cannibalization"
                        direction = Direction.DECREASE
                    else:
                        pattern = "halo"
                        direction = Direction.INCREASE

                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever="assortment",
                        related_levers=["pricing"],
                        direction=direction,
                        magnitude=abs(corr),
                        confidence=min(0.75, 1.0 - p_val),
                        mechanism=(
                            f"Portfolio {pattern} signal between "
                            f"{key_a} and {key_b}: residual ρ={corr:.3f} "
                            f"(p={p_val:.4f})."
                        ),
                        source_types=["quantitative"],
                        data={
                            "key_a": key_a,
                            "key_b": key_b,
                            "residual_correlation": float(corr),
                            "p_value": float(p_val),
                            "pattern": pattern,
                            "analysis_type": "profile_portfolio",
                        },
                    ))
