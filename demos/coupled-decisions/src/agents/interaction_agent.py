"""Interaction diagnostic agent.

Detects statistical interaction effects between all lever pairs.
Uses PARTIAL correlations (not raw) to handle multi-collinearity.
Flags collinear pairs, synergies, and conflicts.

Only depends on stdlib + numpy + scipy.
"""

from __future__ import annotations

from itertools import combinations
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from scipy import stats as sp_stats

from ..core.config import Config
from ..core.types import (
    Direction,
    EvidencePacket,
    LeverName,
    StatisticalProfile,
)


# Lever columns expected in sales data
_LEVER_COLUMNS = (
    "price_paid",
    "promo_depth",
    "display_flag",
    "facings",
    "pack_size",
)

_LEVER_TO_NAME = {
    "price_paid": "pricing",
    "promo_depth": "promotion",
    "display_flag": "distribution",
    "facings": "distribution",
    "pack_size": "pack_price",
}


class InteractionAgent:
    """Diagnostic agent for lever-pair interaction detection."""

    AGENT_ID = "interaction_agent"

    def __init__(self, config: Config, encoded_knowledge: Dict[str, Any]) -> None:
        self.config = config
        self.encoded_knowledge = encoded_knowledge
        self._evidence: List[EvidencePacket] = []
        self._pruned: Dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def diagnose(self) -> List[EvidencePacket]:
        """Run interaction diagnostic, return evidence packets."""
        self._evidence = []
        self._pruned = {
            "interacting_pairs": [],
            "collinear_pairs": [],
            "non_interacting_pairs": [],
        }

        sales = self.encoded_knowledge.get("sales", {})
        if sales:
            self._analyze_lever_interactions(sales)
        else:
            # Fall back to profile-based analysis
            profiles = self.encoded_knowledge.get("quantitative", [])
            if profiles:
                self._analyze_profile_interactions(profiles)

        return self._evidence

    def get_pruned_space(self) -> Dict[str, Any]:
        """Return the reduced candidate space."""
        if not self._evidence:
            self.diagnose()
        return self._pruned

    # ------------------------------------------------------------------
    # Sales-data-based analysis
    # ------------------------------------------------------------------

    def _analyze_lever_interactions(self, sales: Dict[str, Any]) -> None:
        """Analyze lever pair interactions from sales transaction data."""
        outcome = np.asarray(sales.get("units_sold", sales.get("revenue", [])),
                             dtype=np.float64)
        if len(outcome) == 0:
            return

        # Build lever matrix from available columns
        lever_data: Dict[str, np.ndarray] = {}
        for col in _LEVER_COLUMNS:
            if col in sales:
                arr = np.asarray(sales[col], dtype=np.float64)
                if len(arr) == len(outcome):
                    lever_data[col] = arr

        if len(lever_data) < 2:
            return

        lever_names = list(lever_data.keys())
        lever_matrix = np.column_stack([lever_data[c] for c in lever_names])
        n_obs, n_levers = lever_matrix.shape

        # Subsample for computational efficiency
        max_obs = 50_000
        if n_obs > max_obs:
            rng = np.random.default_rng(self.config.random_seed)
            idx = rng.choice(n_obs, max_obs, replace=False)
            lever_matrix = lever_matrix[idx]
            outcome = outcome[idx]
            n_obs = max_obs

        # Step 1: Compute raw and partial correlation matrices
        raw_corr = self._raw_correlation_matrix(lever_matrix)
        partial_corr = self._partial_correlation_matrix(lever_matrix)

        # Step 2: Flag collinear pairs (high raw correlation)
        self._detect_collinearity(lever_names, raw_corr, partial_corr)

        # Step 3: Test interaction effects for each lever pair
        self._test_interaction_effects(
            lever_names, lever_matrix, outcome, partial_corr,
        )

    def _raw_correlation_matrix(self, X: np.ndarray) -> np.ndarray:
        """Compute Pearson correlation matrix."""
        n = X.shape[1]
        # Handle constant columns
        stds = np.std(X, axis=0)
        mask = stds > 1e-12
        corr = np.eye(n)
        if mask.sum() >= 2:
            valid_idx = np.where(mask)[0]
            sub = X[:, valid_idx]
            sub_corr = np.corrcoef(sub, rowvar=False)
            for ii, i in enumerate(valid_idx):
                for jj, j in enumerate(valid_idx):
                    corr[i, j] = sub_corr[ii, jj]
        return corr

    def _partial_correlation_matrix(self, X: np.ndarray) -> np.ndarray:
        """Compute partial correlation matrix via precision matrix.

        Partial correlation between i and j controls for all other
        variables, addressing multi-collinearity.
        """
        n_vars = X.shape[1]
        corr = self._raw_correlation_matrix(X)

        try:
            # Regularize to ensure invertibility
            reg = corr + 1e-6 * np.eye(n_vars)
            precision = np.linalg.inv(reg)

            partial = np.zeros_like(precision)
            diag = np.sqrt(np.abs(np.diag(precision)))
            diag[diag < 1e-12] = 1.0

            for i in range(n_vars):
                for j in range(n_vars):
                    if i == j:
                        partial[i, j] = 1.0
                    else:
                        partial[i, j] = -precision[i, j] / (diag[i] * diag[j])

            return np.clip(partial, -1.0, 1.0)
        except np.linalg.LinAlgError:
            return corr

    def _detect_collinearity(
        self,
        lever_names: List[str],
        raw_corr: np.ndarray,
        partial_corr: np.ndarray,
    ) -> None:
        """Flag collinear lever pairs where |raw_ρ| > 0.5."""
        n = len(lever_names)
        collinearity_threshold = 0.5

        for i in range(n):
            for j in range(i + 1, n):
                raw_rho = raw_corr[i, j]
                partial_rho = partial_corr[i, j]

                if abs(raw_rho) > collinearity_threshold:
                    name_a = _LEVER_TO_NAME.get(lever_names[i], lever_names[i])
                    name_b = _LEVER_TO_NAME.get(lever_names[j], lever_names[j])

                    self._pruned["collinear_pairs"].append({
                        "lever_a": lever_names[i],
                        "lever_b": lever_names[j],
                        "raw_correlation": float(raw_rho),
                        "partial_correlation": float(partial_rho),
                    })

                    # Emit evidence: collinearity means naive analysis will mislead
                    spurious = abs(raw_rho) > 0.5 and abs(partial_rho) < 0.2
                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever=name_a,
                        related_levers=[name_b],
                        direction=Direction.MAINTAIN,
                        magnitude=abs(raw_rho),
                        confidence=0.85,
                        mechanism=(
                            f"Collinearity detected: {lever_names[i]}↔{lever_names[j]} "
                            f"(raw ρ={raw_rho:.3f}, partial ρ={partial_rho:.3f}). "
                            f"{'Mostly spurious — controlled correlation is weak.' if spurious else 'Genuine coupling persists after controlling for other levers.'}"
                        ),
                        source_types=["quantitative"],
                        data={
                            "lever_a": lever_names[i],
                            "lever_b": lever_names[j],
                            "raw_correlation": float(raw_rho),
                            "partial_correlation": float(partial_rho),
                            "spurious": spurious,
                            "analysis_type": "collinearity",
                        },
                    ))

    def _test_interaction_effects(
        self,
        lever_names: List[str],
        lever_matrix: np.ndarray,
        outcome: np.ndarray,
        partial_corr: np.ndarray,
    ) -> None:
        """Test whether effect(A×B) ≠ effect(A) + effect(B) for each lever pair.

        Bins each lever into high/low and compares the joint effect
        against the sum of marginal effects.
        """
        n_obs = len(outcome)
        n_levers = len(lever_names)
        min_effect = self.config.interaction_effect_min
        overall_mean = float(np.mean(outcome))

        if overall_mean == 0:
            return

        for i in range(n_levers):
            for j in range(i + 1, n_levers):
                a = lever_matrix[:, i]
                b = lever_matrix[:, j]

                med_a = float(np.median(a))
                med_b = float(np.median(b))

                hi_a = a >= med_a
                lo_a = a < med_a
                hi_b = b >= med_b
                lo_b = b < med_b

                # Marginal effects (normalized)
                mean_hi_a = np.mean(outcome[hi_a]) if hi_a.sum() > 10 else overall_mean
                mean_lo_a = np.mean(outcome[lo_a]) if lo_a.sum() > 10 else overall_mean
                effect_a = (mean_hi_a - mean_lo_a) / overall_mean

                mean_hi_b = np.mean(outcome[hi_b]) if hi_b.sum() > 10 else overall_mean
                mean_lo_b = np.mean(outcome[lo_b]) if lo_b.sum() > 10 else overall_mean
                effect_b = (mean_hi_b - mean_lo_b) / overall_mean

                # Joint effect
                joint_hh = hi_a & hi_b
                joint_ll = lo_a & lo_b
                mean_hh = np.mean(outcome[joint_hh]) if joint_hh.sum() > 10 else overall_mean
                mean_ll = np.mean(outcome[joint_ll]) if joint_ll.sum() > 10 else overall_mean
                effect_joint = (mean_hh - mean_ll) / overall_mean

                # Interaction = joint − (marginal_A + marginal_B)
                additive = effect_a + effect_b
                interaction = effect_joint - additive

                if abs(interaction) < min_effect:
                    self._pruned["non_interacting_pairs"].append({
                        "lever_a": lever_names[i],
                        "lever_b": lever_names[j],
                        "interaction_effect": float(interaction),
                    })
                    continue

                # Determine synergy vs conflict
                if interaction > 0:
                    pattern = "synergy"
                    description = "combined effect exceeds sum of individual effects"
                else:
                    pattern = "conflict"
                    description = "combined effect is less than sum of individual effects"

                name_a = _LEVER_TO_NAME.get(lever_names[i], lever_names[i])
                name_b = _LEVER_TO_NAME.get(lever_names[j], lever_names[j])

                # Statistical test: permutation-based p-value approximation
                n_perm = 500
                rng = np.random.default_rng(self.config.random_seed + i * 100 + j)
                perm_interactions = np.empty(n_perm)
                for p in range(n_perm):
                    shuffled = rng.permutation(outcome)
                    p_mean_hh = np.mean(shuffled[joint_hh]) if joint_hh.sum() > 0 else overall_mean
                    p_mean_ll = np.mean(shuffled[joint_ll]) if joint_ll.sum() > 0 else overall_mean
                    perm_interactions[p] = (p_mean_hh - p_mean_ll) / overall_mean - additive

                p_value = float(np.mean(np.abs(perm_interactions) >= abs(interaction)))
                confidence = min(0.95, 1.0 - p_value)

                self._evidence.append(EvidencePacket(
                    agent_id=self.AGENT_ID,
                    lever=name_a,
                    related_levers=[name_b],
                    direction=Direction.MAINTAIN,
                    magnitude=abs(interaction),
                    confidence=confidence,
                    mechanism=(
                        f"Interaction {pattern} between {lever_names[i]}×"
                        f"{lever_names[j]}: {description}. "
                        f"effect(A)={effect_a:.4f}, effect(B)={effect_b:.4f}, "
                        f"effect(A×B)={effect_joint:.4f}, "
                        f"interaction={interaction:.4f} (p={p_value:.4f})."
                    ),
                    source_types=["quantitative"],
                    data={
                        "lever_a": lever_names[i],
                        "lever_b": lever_names[j],
                        "effect_a": float(effect_a),
                        "effect_b": float(effect_b),
                        "effect_joint": float(effect_joint),
                        "interaction_effect": float(interaction),
                        "additive_prediction": float(additive),
                        "pattern": pattern,
                        "p_value": p_value,
                        "partial_correlation": float(partial_corr[i, j]),
                        "analysis_type": "interaction_effect",
                    },
                ))
                self._pruned["interacting_pairs"].append({
                    "lever_a": lever_names[i],
                    "lever_b": lever_names[j],
                    "interaction_effect": float(interaction),
                    "pattern": pattern,
                    "p_value": p_value,
                })

    # ------------------------------------------------------------------
    # Fallback: profile-based analysis
    # ------------------------------------------------------------------

    def _analyze_profile_interactions(
        self, profiles: List[Dict[str, Any]],
    ) -> None:
        """Detect interaction signals from encoded StatisticalProfiles.

        When raw sales data is unavailable, look for correlated residual
        patterns across profiles as a proxy for interaction effects.
        """
        # Collect residuals from profiles
        residuals: List[Tuple[str, np.ndarray]] = []
        for entry in profiles:
            if isinstance(entry, dict):
                profile = entry.get("profile")
                key = entry.get("key", "")
            elif isinstance(entry, StatisticalProfile):
                profile = entry
                key = ""
            else:
                continue

            if profile is None or not isinstance(profile, StatisticalProfile):
                continue

            if profile.residual and len(profile.residual) > 10:
                residuals.append((key, np.array(profile.residual)))

        # Pairwise residual correlation as interaction proxy
        for i in range(len(residuals)):
            for j in range(i + 1, len(residuals)):
                key_a, res_a = residuals[i]
                key_b, res_b = residuals[j]

                min_len = min(len(res_a), len(res_b))
                if min_len < 10:
                    continue

                corr, p_val = sp_stats.pearsonr(res_a[:min_len], res_b[:min_len])

                if abs(corr) > 0.3 and p_val < self.config.elasticity_significance:
                    pattern = "synergy" if corr > 0 else "conflict"
                    self._evidence.append(EvidencePacket(
                        agent_id=self.AGENT_ID,
                        lever=key_a or "unknown",
                        related_levers=[key_b or "unknown"],
                        direction=Direction.MAINTAIN,
                        magnitude=abs(corr),
                        confidence=min(0.8, 1.0 - p_val),
                        mechanism=(
                            f"Residual correlation between {key_a} and {key_b} "
                            f"(ρ={corr:.3f}, p={p_val:.4f}) suggests "
                            f"interaction {pattern}."
                        ),
                        source_types=["quantitative"],
                        data={
                            "key_a": key_a,
                            "key_b": key_b,
                            "residual_correlation": float(corr),
                            "p_value": float(p_val),
                            "pattern": pattern,
                            "analysis_type": "residual_interaction",
                        },
                    ))
