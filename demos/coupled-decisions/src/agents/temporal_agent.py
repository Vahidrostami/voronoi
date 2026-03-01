"""Temporal diagnostic agent.

Analyzes time series: trends, seasonality, structural breaks from
StatisticalProfiles. Identifies which levers are trending. Compares
expert TemporalBeliefs with data trajectories for alignment/conflict.

Only depends on stdlib + numpy + scipy.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import stats as sp_stats

from ..core.config import Config
from ..core.types import (
    Direction,
    EvidencePacket,
    StatisticalProfile,
    TemporalBelief,
)


class TemporalAgent:
    """Diagnostic agent for temporal pattern analysis."""

    AGENT_ID = "temporal_agent"

    def __init__(self, config: Config, encoded_knowledge: Dict[str, Any]) -> None:
        self.config = config
        self.encoded_knowledge = encoded_knowledge
        self._evidence: List[EvidencePacket] = []
        self._pruned: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def diagnose(self) -> List[EvidencePacket]:
        """Run temporal diagnostic, return evidence packets."""
        self._evidence = []
        self._pruned = {
            "trending_levers": [],
            "seasonal_patterns": [],
            "structural_breaks": [],
            "expert_data_alignments": [],
            "expert_data_conflicts": [],
        }

        profiles = self._get_profiles()
        beliefs = self._get_beliefs()

        if profiles:
            self._analyze_trends(profiles)
            self._analyze_seasonality(profiles)
            self._analyze_structural_breaks(profiles)

        if beliefs and profiles:
            self._compare_expert_vs_data(beliefs, profiles)
        elif beliefs:
            self._analyze_beliefs_standalone(beliefs)

        return self._evidence

    def get_pruned_space(self) -> Dict[str, Any]:
        """Return the reduced candidate space."""
        if not self._evidence:
            self.diagnose()
        return self._pruned

    # ------------------------------------------------------------------
    # Data extraction
    # ------------------------------------------------------------------

    def _get_profiles(self) -> List[Dict[str, Any]]:
        """Extract statistical profiles from encoded knowledge."""
        raw = self.encoded_knowledge.get("quantitative", [])
        result = []
        for entry in raw:
            if isinstance(entry, dict):
                result.append(entry)
            elif isinstance(entry, StatisticalProfile):
                result.append({"profile": entry, "key": "", "metadata": {}})
        return result

    def _get_beliefs(self) -> List[TemporalBelief]:
        """Extract temporal beliefs from encoded knowledge."""
        raw = self.encoded_knowledge.get("expert", [])
        result = []
        for item in raw:
            if isinstance(item, TemporalBelief):
                result.append(item)
            elif isinstance(item, dict):
                result.append(TemporalBelief.from_dict(item))
        return result

    # ------------------------------------------------------------------
    # Trend analysis
    # ------------------------------------------------------------------

    def _analyze_trends(self, profiles: List[Dict[str, Any]]) -> None:
        """Identify significant trends in StatisticalProfiles."""
        for entry in profiles:
            profile = entry.get("profile")
            key = entry.get("key", "")
            metadata = entry.get("metadata", {})

            if not isinstance(profile, StatisticalProfile):
                continue
            if not profile.trend or len(profile.trend) < 4:
                continue

            trend = np.array(profile.trend)
            n = len(trend)

            # Linear regression on trend component
            t = np.arange(n, dtype=np.float64)
            slope, intercept, r_value, p_value, std_err = sp_stats.linregress(t, trend)

            # Relative slope (per observation, normalized by mean)
            mean_level = abs(profile.mean) if abs(profile.mean) > 1e-9 else 1.0
            relative_slope = slope / mean_level

            is_significant = p_value < self.config.elasticity_significance

            if is_significant and abs(relative_slope) > 0.001:
                if slope > 0:
                    direction = Direction.INCREASE
                    trend_desc = "upward"
                else:
                    direction = Direction.DECREASE
                    trend_desc = "downward"

                lever = metadata.get("lever", "")
                self._evidence.append(EvidencePacket(
                    agent_id=self.AGENT_ID,
                    lever=lever,
                    direction=direction,
                    magnitude=abs(relative_slope),
                    confidence=min(0.95, abs(r_value)),
                    mechanism=(
                        f"Significant {trend_desc} trend in {key or 'metric'}: "
                        f"slope={slope:.4f}/period (relative={relative_slope:.4f}), "
                        f"R²={r_value**2:.3f}, p={p_value:.4f}. "
                        f"n={n} observations."
                    ),
                    source_types=["quantitative"],
                    data={
                        "key": key,
                        "slope": float(slope),
                        "relative_slope": float(relative_slope),
                        "r_squared": float(r_value ** 2),
                        "p_value": float(p_value),
                        "std_err": float(std_err),
                        "n_observations": n,
                        "analysis_type": "trend",
                        **metadata,
                    },
                ))
                self._pruned["trending_levers"].append({
                    "key": key,
                    "lever": lever,
                    "direction": trend_desc,
                    "relative_slope": float(relative_slope),
                    "p_value": float(p_value),
                })

    # ------------------------------------------------------------------
    # Seasonality analysis
    # ------------------------------------------------------------------

    def _analyze_seasonality(self, profiles: List[Dict[str, Any]]) -> None:
        """Identify significant seasonal patterns."""
        for entry in profiles:
            profile = entry.get("profile")
            key = entry.get("key", "")
            metadata = entry.get("metadata", {})

            if not isinstance(profile, StatisticalProfile):
                continue
            if not profile.seasonality or len(profile.seasonality) < 4:
                continue

            season = np.array(profile.seasonality)
            amplitude = float(np.max(season) - np.min(season))
            mean_level = abs(profile.mean) if abs(profile.mean) > 1e-9 else 1.0
            relative_amplitude = amplitude / mean_level

            if relative_amplitude > 0.05:
                peak_idx = int(np.argmax(season))
                trough_idx = int(np.argmin(season))
                period = len(season)

                lever = metadata.get("lever", "")
                self._evidence.append(EvidencePacket(
                    agent_id=self.AGENT_ID,
                    lever=lever,
                    direction=Direction.MAINTAIN,
                    magnitude=relative_amplitude,
                    confidence=min(0.9, 0.5 + relative_amplitude),
                    mechanism=(
                        f"Seasonal pattern in {key or 'metric'}: "
                        f"amplitude={relative_amplitude:.2%} of mean. "
                        f"Peak at period index {peak_idx}/{period}, "
                        f"trough at {trough_idx}/{period}."
                    ),
                    source_types=["quantitative"],
                    data={
                        "key": key,
                        "amplitude": amplitude,
                        "relative_amplitude": relative_amplitude,
                        "peak_index": peak_idx,
                        "trough_index": trough_idx,
                        "period": period,
                        "analysis_type": "seasonality",
                        **metadata,
                    },
                ))
                self._pruned["seasonal_patterns"].append({
                    "key": key,
                    "lever": lever,
                    "relative_amplitude": relative_amplitude,
                    "peak_index": peak_idx,
                    "period": period,
                })

    # ------------------------------------------------------------------
    # Structural break analysis
    # ------------------------------------------------------------------

    def _analyze_structural_breaks(self, profiles: List[Dict[str, Any]]) -> None:
        """Analyze structural breaks from StatisticalProfiles."""
        for entry in profiles:
            profile = entry.get("profile")
            key = entry.get("key", "")
            metadata = entry.get("metadata", {})

            if not isinstance(profile, StatisticalProfile):
                continue
            if not profile.structural_breaks:
                continue

            breaks = profile.structural_breaks
            n_breaks = len(breaks)
            n_obs = profile.n_observations

            lever = metadata.get("lever", "")

            # Analyze each break point
            for bp in breaks:
                if not profile.trend or bp >= len(profile.trend) or bp < 1:
                    continue

                trend = np.array(profile.trend)
                pre_mean = float(np.mean(trend[:bp]))
                post_mean = float(np.mean(trend[bp:]))
                shift = post_mean - pre_mean
                mean_level = abs(profile.mean) if abs(profile.mean) > 1e-9 else 1.0
                relative_shift = shift / mean_level

                if abs(relative_shift) > 0.02:
                    direction = Direction.INCREASE if shift > 0 else Direction.DECREASE

                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever=lever,
                        direction=direction,
                        magnitude=abs(relative_shift),
                        confidence=min(0.9, 0.6 + 0.3 * abs(relative_shift)),
                        mechanism=(
                            f"Structural break at period {bp}/{n_obs} in "
                            f"{key or 'metric'}: mean shifted by "
                            f"{relative_shift:+.2%}. "
                            f"Pre-break mean={pre_mean:.2f}, "
                            f"post-break mean={post_mean:.2f}."
                        ),
                        source_types=["quantitative"],
                        data={
                            "key": key,
                            "break_point": bp,
                            "pre_mean": pre_mean,
                            "post_mean": post_mean,
                            "shift": float(shift),
                            "relative_shift": float(relative_shift),
                            "total_breaks": n_breaks,
                            "n_observations": n_obs,
                            "analysis_type": "structural_break",
                            **metadata,
                        },
                    ))

            self._pruned["structural_breaks"].append({
                "key": key,
                "lever": lever,
                "break_points": breaks,
                "n_breaks": n_breaks,
            })

    # ------------------------------------------------------------------
    # Expert vs data comparison
    # ------------------------------------------------------------------

    def _compare_expert_vs_data(
        self,
        beliefs: List[TemporalBelief],
        profiles: List[Dict[str, Any]],
    ) -> None:
        """Compare expert beliefs with data trajectories."""
        # Build a map of lever → trend direction from data
        lever_trends: Dict[str, Dict[str, Any]] = {}
        for entry in profiles:
            profile = entry.get("profile")
            metadata = entry.get("metadata", {})
            lever = metadata.get("lever", "")
            key = entry.get("key", "")

            if not isinstance(profile, StatisticalProfile):
                continue
            if not profile.trend or len(profile.trend) < 4:
                continue

            trend = np.array(profile.trend)
            slope = trend[-1] - trend[0]
            if abs(slope) > 1e-6:
                data_dir = "increase" if slope > 0 else "decrease"
            else:
                data_dir = "maintain"

            lever_key = lever or key
            if lever_key:
                lever_trends[lever_key] = {
                    "direction": data_dir,
                    "slope": float(slope),
                    "mean": profile.mean,
                    "std": profile.std,
                    "n_observations": profile.n_observations,
                }

        for belief in beliefs:
            belief_dir = belief.lever_direction
            if belief_dir is None:
                continue

            # Check each domain lever against data trends
            for domain_lever in belief.domain:
                data_info = lever_trends.get(domain_lever)
                if data_info is None:
                    # Try partial matching
                    for k, v in lever_trends.items():
                        if domain_lever in k or k in domain_lever:
                            data_info = v
                            break

                if data_info is None:
                    continue

                data_dir = data_info["direction"]

                # Check alignment
                if belief_dir == data_dir:
                    # Aligned
                    alignment_conf = min(
                        belief.current_confidence,
                        0.8 * min(1.0, data_info["n_observations"] / 52),
                    )
                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever=domain_lever,
                        related_levers=list(belief.domain),
                        direction=Direction(belief_dir) if belief_dir in ("increase", "decrease") else Direction.MAINTAIN,
                        magnitude=belief.lever_magnitude or abs(data_info["slope"]),
                        confidence=alignment_conf,
                        mechanism=(
                            f"Expert-data ALIGNMENT on '{domain_lever}': "
                            f"expert says '{belief_dir}' "
                            f"(conf={belief.current_confidence:.2f}), "
                            f"data trend confirms '{data_dir}'. "
                            f"Belief: \"{belief.statement[:60]}...\""
                        ),
                        source_types=["quantitative", "expert"],
                        data={
                            "lever": domain_lever,
                            "belief_direction": belief_dir,
                            "data_direction": data_dir,
                            "belief_confidence": belief.current_confidence,
                            "data_slope": data_info["slope"],
                            "basis": belief.basis.value,
                            "analysis_type": "expert_data_alignment",
                        },
                    ))
                    self._pruned["expert_data_alignments"].append({
                        "lever": domain_lever,
                        "belief_direction": belief_dir,
                        "data_direction": data_dir,
                        "belief_statement": belief.statement[:80],
                    })

                elif (
                    belief_dir in ("increase", "decrease")
                    and data_dir in ("increase", "decrease")
                    and belief_dir != data_dir
                ):
                    # Conflict
                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever=domain_lever,
                        related_levers=list(belief.domain),
                        direction=Direction(data_dir),
                        magnitude=abs(data_info["slope"]),
                        confidence=max(
                            0.3,
                            0.8 - belief.current_confidence,
                        ),
                        mechanism=(
                            f"Expert-data CONFLICT on '{domain_lever}': "
                            f"expert says '{belief_dir}' "
                            f"(conf={belief.current_confidence:.2f}, "
                            f"basis={belief.basis.value}), "
                            f"but data shows '{data_dir}'. "
                            f"Belief: \"{belief.statement[:60]}...\""
                        ),
                        source_types=["quantitative", "expert"],
                        data={
                            "lever": domain_lever,
                            "belief_direction": belief_dir,
                            "data_direction": data_dir,
                            "belief_confidence": belief.current_confidence,
                            "data_slope": data_info["slope"],
                            "basis": belief.basis.value,
                            "conflicts_with_data": True,
                            "analysis_type": "expert_data_conflict",
                        },
                    ))
                    self._pruned["expert_data_conflicts"].append({
                        "lever": domain_lever,
                        "belief_direction": belief_dir,
                        "data_direction": data_dir,
                        "belief_statement": belief.statement[:80],
                        "belief_confidence": belief.current_confidence,
                    })

    # ------------------------------------------------------------------
    # Standalone belief analysis (when no profiles available)
    # ------------------------------------------------------------------

    def _analyze_beliefs_standalone(
        self, beliefs: List[TemporalBelief],
    ) -> None:
        """Analyze belief quality and temporal decay when no data is available."""
        for belief in beliefs:
            if belief.current_confidence < 0.3:
                self._evidence.append(EvidencePacket(
                    agent_id=self.AGENT_ID,
                    lever=belief.domain[0] if belief.domain else "",
                    related_levers=list(belief.domain),
                    direction=Direction.MAINTAIN,
                    magnitude=belief.current_confidence,
                    confidence=0.5,
                    mechanism=(
                        f"Low-confidence expert belief "
                        f"(decayed conf={belief.current_confidence:.2f}, "
                        f"basis={belief.basis.value}): "
                        f"\"{belief.statement[:60]}...\". "
                        f"Consider deprioritizing."
                    ),
                    source_types=["expert"],
                    data={
                        "statement": belief.statement[:100],
                        "original_confidence": belief.confidence,
                        "current_confidence": belief.current_confidence,
                        "basis": belief.basis.value,
                        "domain": list(belief.domain),
                        "analysis_type": "low_confidence_belief",
                    },
                ))
