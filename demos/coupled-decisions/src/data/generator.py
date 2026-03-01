"""Master synthetic-data generator for the BevCo scenario.

Produces three datasets:
  * sales_transactions.csv  (~1 040 000 rows)
  * price_elasticity.csv    (own + cross-price elasticities with noise)
  * market_share.csv        (weekly category-level share by region)

All five ground-truth interaction effects and the four multi-collinearity
structures are embedded deterministically via the random seed.
"""

from __future__ import annotations

import csv
import io
import os
import pathlib
from typing import Any, Dict, Optional, Tuple

import numpy as np

from . import ground_truth as gt

# ---------------------------------------------------------------------------
# Configuration constants (aligned with src.core.config when available)
# ---------------------------------------------------------------------------

N_SKUS = 50
N_STORES = 200
N_WEEKS = 104
N_CATEGORIES = 5
N_REGIONS = 4
SKUS_PER_CATEGORY = N_SKUS // N_CATEGORIES  # 10
STORES_PER_REGION = N_STORES // N_REGIONS     # 50
CATEGORIES = ("A", "B", "C", "D", "E")
REGIONS = ("North", "South", "East", "West")

PROMO_TYPES = (
    "BOGO", "pct_off", "dollar_off", "bundle", "loyalty",
    "clearance", "seasonal", "flash", "coupon", "rebate",
    "multi_buy", "gift_with_purchase",
)
PACK_SIZES = (1, 4, 6, 12, 24)

ELASTICITY_NOISE_SIGMA = 0.15
DEFAULT_SEED = 42

# ---------------------------------------------------------------------------
# SKU catalogue helpers
# ---------------------------------------------------------------------------

_CATEGORY_BASE_PRICES = {
    "A": (2.50, 0.60),   # mean, std
    "B": (3.00, 0.80),
    "C": (1.80, 0.40),
    "D": (4.50, 1.00),
    "E": (6.50, 1.20),   # premium
}

_CATEGORY_BASE_DEMAND = {
    "A": 25.0,
    "B": 18.0,
    "C": 30.0,
    "D": 15.0,
    "E": 10.0,
}

_BRAND_TIERS = ("value", "mainstream", "premium")


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------

class BevCoGenerator:
    """Deterministic synthetic data generator for the BevCo scenario."""

    def __init__(self, seed: int = DEFAULT_SEED) -> None:
        self.seed = seed
        self.rng = np.random.default_rng(seed)
        self._sku = self._build_sku_catalog()
        self._store = self._build_store_catalog()

    # ------------------------------------------------------------------
    # Catalogue builders
    # ------------------------------------------------------------------

    def _build_sku_catalog(self) -> Dict[str, np.ndarray]:
        """Create static attributes for 50 SKUs."""
        rng = np.random.default_rng(self.seed + 1)
        cat_idx = np.repeat(np.arange(N_CATEGORIES), SKUS_PER_CATEGORY)
        cat_labels = np.array([CATEGORIES[i] for i in cat_idx])
        brand_tier_idx = np.tile(np.arange(3), N_SKUS // 3 + 1)[:N_SKUS]
        brand_tiers = np.array([_BRAND_TIERS[i] for i in brand_tier_idx])

        # Base prices per category with per-SKU jitter
        base_price = np.empty(N_SKUS)
        for ci, cat in enumerate(CATEGORIES):
            mu, sigma = _CATEGORY_BASE_PRICES[cat]
            sl = slice(ci * SKUS_PER_CATEGORY, (ci + 1) * SKUS_PER_CATEGORY)
            base_price[sl] = rng.normal(mu, sigma, SKUS_PER_CATEGORY).clip(0.50, 8.00)

        # Primary pack size (correlated with price — larger pack → lower per-unit)
        primary_pack = np.ones(N_SKUS, dtype=int)
        for i in range(N_SKUS):
            pack_probs = np.array([0.05, 0.15, 0.35, 0.30, 0.15])  # 1,4,6,12,24
            if base_price[i] > 5.0:
                pack_probs = np.array([0.02, 0.08, 0.20, 0.40, 0.30])
            elif base_price[i] < 2.5:
                pack_probs = np.array([0.15, 0.30, 0.35, 0.15, 0.05])
            pack_probs /= pack_probs.sum()
            primary_pack[i] = rng.choice(PACK_SIZES, p=pack_probs)

        # Per-unit price (pack_size–price collinearity ρ≈0.85)
        per_unit_price = base_price / np.sqrt(primary_pack.astype(float))

        # Base demand per SKU (units/store/week before any lever effects)
        base_demand = np.empty(N_SKUS)
        for ci, cat in enumerate(CATEGORIES):
            sl = slice(ci * SKUS_PER_CATEGORY, (ci + 1) * SKUS_PER_CATEGORY)
            base_demand[sl] = rng.normal(
                _CATEGORY_BASE_DEMAND[cat],
                _CATEGORY_BASE_DEMAND[cat] * 0.20,
                SKUS_PER_CATEGORY,
            ).clip(2.0, 80.0)
        # Low-velocity SKUs for Effect 2
        for sid in gt.LOW_VELOCITY_SKU_IDS:
            base_demand[sid] *= 0.15

        # Elasticities
        own_price_elast = rng.uniform(-2.5, -0.8, N_SKUS)
        # Cat A: more elastic to enable Effect 1
        own_price_elast[:SKUS_PER_CATEGORY] = rng.uniform(-2.8, -1.8, SKUS_PER_CATEGORY)

        promo_multiplier = rng.uniform(0.6, 1.8, N_SKUS)
        # Cat A high promo response (trap)
        promo_multiplier[:SKUS_PER_CATEGORY] = rng.uniform(1.4, 2.0, SKUS_PER_CATEGORY)

        display_lift = rng.uniform(0.15, 0.40, N_SKUS)
        facings_elast = rng.uniform(0.10, 0.35, N_SKUS)
        # Boost facings elasticity for top sellers in C/D (Effect 2)
        for ci in (2, 3):
            sl = slice(ci * SKUS_PER_CATEGORY, (ci + 1) * SKUS_PER_CATEGORY)
            top_mask = base_demand[sl] > np.median(base_demand[sl])
            facings_elast[sl][top_mask] *= 2.0

        base_facings = rng.integers(2, 6, N_SKUS).astype(float)

        # Cost fraction of base price (for margin calculations)
        cost_frac = rng.uniform(0.40, 0.65, N_SKUS)
        # Premium SKUs: most have tight margin (<= 25% headroom)
        for sid in gt.PREMIUM_SKU_IDS:
            if sid < N_SKUS:
                cost_frac[sid] = rng.uniform(0.70, 0.80)
        # 3 premium SKUs with headroom for Effect 5
        for sid in gt.PREMIUM_SKUS_WITH_HEADROOM:
            if sid < N_SKUS:
                cost_frac[sid] = rng.uniform(0.50, 0.60)

        return {
            "category_idx": cat_idx,
            "category": cat_labels,
            "brand_tier_idx": brand_tier_idx,
            "brand_tier": brand_tiers,
            "base_price": base_price,
            "primary_pack": primary_pack,
            "per_unit_price": per_unit_price,
            "base_demand": base_demand,
            "own_price_elast": own_price_elast,
            "promo_multiplier": promo_multiplier,
            "display_lift": display_lift,
            "facings_elast": facings_elast,
            "base_facings": base_facings,
            "cost_frac": cost_frac,
        }

    def _build_store_catalog(self) -> Dict[str, np.ndarray]:
        """Create static attributes for 200 stores."""
        rng = np.random.default_rng(self.seed + 2)
        region_idx = np.repeat(np.arange(N_REGIONS), STORES_PER_REGION)
        region_labels = np.array([REGIONS[i] for i in region_idx])
        # Store scale factor (size-driven demand multiplier)
        store_scale = rng.lognormal(0.0, 0.25, N_STORES).clip(0.4, 2.5)
        return {
            "region_idx": region_idx,
            "region": region_labels,
            "scale": store_scale,
        }

    # ------------------------------------------------------------------
    # Correlated lever generation
    # ------------------------------------------------------------------

    def _generate_lever_states(
        self, n: int, sku_ids: np.ndarray, week: np.ndarray
    ) -> Dict[str, np.ndarray]:
        """Generate correlated lever realisations for *n* observations.

        Returns arrays of length *n* for price_paid, promo_flag,
        promo_depth, promo_type, display_flag, facings, pack_size.

        Multi-collinearity is injected *directly* between observables
        (not just through the latent z-space) so the measured correlations
        match the spec targets after discretisation and clipping.
        """
        # Independent random draws used as building blocks
        u = self.rng.random((n, 6))
        z = self.rng.standard_normal((n, 6))

        bp = self._sku["base_price"][sku_ids]
        pp = self._sku["primary_pack"][sku_ids].astype(float)
        bf = self._sku["base_facings"][sku_ids]

        # --- promo_flag and promo_depth ---
        # Higher-priced SKUs get deeper promos (Price-Promo collinearity).
        # Normalised base price used as a driver of promo propensity.
        bp_z = (bp - bp.mean()) / (bp.std() + 1e-9)  # z-scored base price
        promo_propensity = z[:, 1] + 0.5 * bp_z  # higher price → more likely promo
        promo_flag = (promo_propensity > 0.6).astype(np.int8)
        # Depth also scales with base price: expensive SKUs get deeper cuts
        raw_depth = 0.15 + 0.20 * u[:, 1] + 0.06 * bp_z
        promo_depth = np.where(promo_flag, raw_depth.clip(0.10, 0.50), 0.0)
        # Cat A: higher promo frequency and depth (Effect 1 setup)
        cat_a_mask = self._sku["category_idx"][sku_ids] == 0
        promo_flag = np.where(
            cat_a_mask & (promo_propensity > 0.3), 1, promo_flag,
        ).astype(np.int8)
        promo_depth = np.where(
            cat_a_mask & (promo_flag == 1),
            np.maximum(promo_depth, 0.28 + 0.04 * u[:, 0]),
            promo_depth,
        )

        promo_type_idx = self.rng.integers(0, len(PROMO_TYPES), n)
        promo_type = np.where(promo_flag, promo_type_idx, -1)

        # --- price_paid ---
        # Collinearity: Price–Promotion ρ≈−0.6  (higher base → deeper promo)
        # We make base-price jitter *negatively* driven by promo presence/depth.
        price_noise = 0.06 * z[:, 0]
        # Inject: when promo is deep, base price tends to be higher
        price_shift = price_noise + 0.40 * promo_depth  # +bias toward higher list price when promo
        price_paid = (bp * (1.0 + price_shift)).clip(0.50, 8.00)

        # --- display_flag (Promotion–Display ρ≈0.7) ---
        # Direct coupling: promoted SKUs almost always get display
        display_base = (z[:, 2] > 1.1).astype(np.int8)  # ~13 % random baseline
        display_from_promo = (promo_flag == 1) & (u[:, 2] < 0.88)  # 88 % of promo obs
        display_flag = np.where(display_from_promo, 1, display_base).astype(np.int8)

        # --- facings ---
        facings_raw = bf + 1.2 * z[:, 4]
        facings = np.round(facings_raw).clip(1, 8).astype(int)

        # --- pack_size (Pack-Size–Price ρ≈0.85) ---
        # Allow observation-level pack variation: ~20 % of observations
        # use an adjacent pack size, creating within-SKU variation.
        pack_size = self._sku["primary_pack"][sku_ids].copy()
        alt_pack_mask = u[:, 4] < 0.20  # 20 % get an alternative pack
        for ps_from, ps_to in [(1, 4), (4, 6), (6, 12), (12, 24), (24, 12)]:
            swap = alt_pack_mask & (pack_size == ps_from)
            pack_size = np.where(swap, ps_to, pack_size)

        # Effect 3 setup: introduce 12-packs in Cat D after week 52
        cat_d_mask = self._sku["category_idx"][sku_ids] == 3
        late_mask = week >= 52
        twelve_pack_mask = cat_d_mask & late_mask & (u[:, 3] < 0.35)
        pack_size = np.where(twelve_pack_mask, 12, pack_size)

        # Scale price by pack size (economies of scale)
        # per-unit price decreases with pack size → strong collinearity
        pack_ratio = pack_size.astype(float) / pp  # pp = primary_pack
        price_paid = price_paid * np.power(np.maximum(pack_ratio, 0.1), 0.60)

        # Apply promo price discount to price_paid
        price_paid = np.where(promo_flag, price_paid * (1.0 - promo_depth), price_paid)

        return {
            "price_paid": price_paid,
            "promo_flag": promo_flag,
            "promo_depth": promo_depth,
            "promo_type": promo_type,
            "display_flag": display_flag,
            "facings": facings,
            "pack_size": pack_size,
        }

    # ------------------------------------------------------------------
    # Seasonal and trend patterns
    # ------------------------------------------------------------------

    @staticmethod
    def _seasonal_factor(week: np.ndarray, cat_idx: np.ndarray) -> np.ndarray:
        """Annual seasonality multiplier (1-centred)."""
        t = 2.0 * np.pi * (week % 52) / 52.0
        base_season = 1.0 + 0.12 * np.sin(t) + 0.05 * np.cos(2 * t)
        # Category B: strong Q3 peak (Effect 4: "seasonal, will reverse Q3")
        cat_b = (cat_idx == 1).astype(float)
        q3_peak = 0.25 * np.exp(-((week % 52 - 32) ** 2) / 50.0)
        return base_season + cat_b * q3_peak

    @staticmethod
    def _trend_factor(week: np.ndarray, cat_idx: np.ndarray) -> np.ndarray:
        """Linear + category-specific trends."""
        # Slight overall growth
        trend = 1.0 + 0.001 * week
        # Category B declining outside Q3 (Effect 4)
        cat_b = (cat_idx == 1).astype(float)
        trend = trend - cat_b * 0.0015 * week
        return trend

    # ------------------------------------------------------------------
    # Interaction effects
    # ------------------------------------------------------------------

    def _interaction_effects(
        self,
        week: np.ndarray,
        sku_ids: np.ndarray,
        store_ids: np.ndarray,
        promo_flag: np.ndarray,
        promo_depth: np.ndarray,
        facings: np.ndarray,
        pack_size: np.ndarray,
    ) -> np.ndarray:
        """Multiplicative interaction term embedding all 5 ground-truth effects."""
        n = len(week)
        effect = np.ones(n)
        cat = self._sku["category_idx"][sku_ids]
        bp = self._sku["base_price"][sku_ids]

        # -- Effect 1: Price-Promotion Trap (Cat A) --
        # Loyal-customer subsidy: promos inflate apparent lift but erode margin.
        # Post-promo dip simulates forward buying / stockpiling.
        cat_a = cat == 0
        promo_on = promo_flag == 1
        # During promo: inflated unit lift (captured by promo_multiplier),
        # but we add margin-erosion proxy as a slight demand pull-forward.
        # In the 2 weeks following a promo burst, demand dips.
        # We approximate this with a week-parity trick since promos are
        # clustered: odd weeks after promo → −8% demand.
        post_promo_dip = cat_a & ~promo_on & ((week % 4) < 2)
        effect = np.where(post_promo_dip, effect * 0.92, effect)

        # -- Effect 2: Assortment-Distribution Synergy (Cat C, D) --
        # Low-velocity SKUs have low base demand (set in catalog).
        # Top SKUs in C/D have amplified facings elasticity (set in catalog).
        # The synergy emerges: removing low-velocity SKUs + reallocating
        # facings to top SKUs produces super-linear benefit.
        # We add an extra boost when top-SKU facings exceed 5.
        is_cd = (cat == 2) | (cat == 3)
        is_low_vel = np.isin(sku_ids, gt.LOW_VELOCITY_SKU_IDS)
        is_top = is_cd & ~is_low_vel & (self._sku["base_demand"][sku_ids] >
                                         np.median(self._sku["base_demand"]))
        high_facings = facings >= 5
        effect = np.where(is_top & high_facings, effect * 1.12, effect)

        # -- Effect 3: Pack-Price Cannibalization Mask (Cat D, week≥52) --
        # 12-packs introduced after week 52. They boost own volume but
        # cannibalise 6-packs in the same category.
        cat_d = cat == 3
        is_12pack = pack_size == 12
        is_6pack = pack_size == 6
        late = week >= 52
        # 12-pack gets a volume boost
        effect = np.where(cat_d & is_12pack & late, effect * 1.15, effect)
        # 6-pack suffers cannibalization
        effect = np.where(cat_d & is_6pack & late, effect * 0.78, effect)

        # -- Effect 4: Cross-Source Signal (Cat B) --
        # Declining trend already embedded via _trend_factor.
        # Seasonal Q3 reversal embedded via _seasonal_factor.
        # Higher-margin B SKUs (top 3 by base_price) benefit from shelf
        # reallocation when overall B declines.
        cat_b = cat == 1
        b_prices = self._sku["base_price"][10:20]  # Cat B sku_ids 10-19
        b_high_margin_threshold = np.sort(b_prices)[-3]
        is_high_margin_b = cat_b & (bp >= b_high_margin_threshold)
        # High-margin B SKUs hold demand better during decline
        effect = np.where(is_high_margin_b & (week >= 26), effect * 1.06, effect)

        # -- Effect 5: Constraint-Coupling Conflict (Cat E / premium) --
        # Premium SKUs with margin headroom respond positively to price
        # aggression; others would violate the 25% margin floor.
        # We give the 3 headroom SKUs a small demand bonus when their
        # price is lower than their category average (simulating the
        # "aggressive pricing works here" signal).
        is_premium_headroom = np.isin(sku_ids, gt.PREMIUM_SKUS_WITH_HEADROOM)
        cat_e_avg_price = np.mean(self._sku["base_price"][40:50])
        below_avg = bp < cat_e_avg_price
        effect = np.where(
            is_premium_headroom & below_avg,
            effect * 1.08,
            effect,
        )

        return effect

    # ------------------------------------------------------------------
    # Sales generation
    # ------------------------------------------------------------------

    def generate_sales(self) -> Dict[str, np.ndarray]:
        """Generate ~1M rows of sales transactions."""
        n_obs = N_WEEKS * N_SKUS * N_STORES

        # Index arrays
        weeks = np.repeat(np.arange(N_WEEKS), N_SKUS * N_STORES)
        sku_ids = np.tile(np.repeat(np.arange(N_SKUS), N_STORES), N_WEEKS)
        store_ids = np.tile(np.arange(N_STORES), N_WEEKS * N_SKUS)

        # Lever states (correlated)
        levers = self._generate_lever_states(n_obs, sku_ids, weeks)

        # Base demand
        base = self._sku["base_demand"][sku_ids] * self._store["scale"][store_ids]

        # Seasonal + trend
        cat_idx = self._sku["category_idx"][sku_ids]
        seasonal = self._seasonal_factor(weeks, cat_idx)
        trend = self._trend_factor(weeks, cat_idx)

        # Price effect
        price_ratio = levers["price_paid"] / self._sku["base_price"][sku_ids]
        price_effect = np.power(
            price_ratio.clip(0.3, 3.0),
            self._sku["own_price_elast"][sku_ids],
        )

        # Promo effect
        promo_effect = 1.0 + (
            levers["promo_flag"]
            * levers["promo_depth"]
            * self._sku["promo_multiplier"][sku_ids]
        )

        # Display effect
        display_effect = 1.0 + levers["display_flag"] * self._sku["display_lift"][sku_ids]

        # Facings effect
        facings_ratio = levers["facings"].astype(float) / self._sku["base_facings"][sku_ids]
        facings_effect = np.power(
            facings_ratio.clip(0.2, 5.0),
            self._sku["facings_elast"][sku_ids],
        )

        # Interaction effects (ground truth)
        interaction = self._interaction_effects(
            weeks, sku_ids, store_ids,
            levers["promo_flag"], levers["promo_depth"],
            levers["facings"], levers["pack_size"],
        )

        # Regional demand adjustment
        region_idx = self._store["region_idx"][store_ids]
        region_factor = 1.0 + 0.05 * (region_idx - 1.5)  # slight regional variation

        # Combine
        mu = (
            base * seasonal * trend * price_effect * promo_effect
            * display_effect * facings_effect * interaction * region_factor
        )
        noise = self.rng.lognormal(0.0, 0.08, n_obs)
        units_sold = np.maximum(0, np.round(mu * noise)).astype(int)

        revenue = units_sold * levers["price_paid"]

        # Map promo_type index to string (or empty)
        pt = levers["promo_type"]
        promo_type_str = np.where(
            pt >= 0,
            np.array(PROMO_TYPES)[pt.clip(0, len(PROMO_TYPES) - 1)],
            "",
        )

        return {
            "week": weeks,
            "store_id": store_ids,
            "sku_id": sku_ids,
            "region": self._store["region"][store_ids],
            "category": self._sku["category"][sku_ids],
            "units_sold": units_sold,
            "revenue": np.round(revenue, 2),
            "price_paid": np.round(levers["price_paid"], 2),
            "promo_flag": levers["promo_flag"],
            "promo_type": promo_type_str,
            "promo_depth": np.round(levers["promo_depth"], 3),
            "display_flag": levers["display_flag"],
            "facings": levers["facings"],
            "pack_size": levers["pack_size"],
        }

    # ------------------------------------------------------------------
    # Price elasticity matrix
    # ------------------------------------------------------------------

    def generate_elasticities(self) -> Dict[str, np.ndarray]:
        """Generate estimated own/cross-price elasticity matrix with noise.

        Returns one row per (sku_i, sku_j, region) triple where sku_i ≠ sku_j
        for cross-elasticities, plus own-elasticity rows (sku_i == sku_j).
        """
        rng = np.random.default_rng(self.seed + 10)
        rows_sku_i = []
        rows_sku_j = []
        rows_region = []
        rows_elast = []
        rows_type = []

        for r in range(N_REGIONS):
            for i in range(N_SKUS):
                # Own-price elasticity (with noise + occasional bias)
                true_own = self._sku["own_price_elast"][i]
                bias = 0.0
                # Systematic upward bias for Cat A (makes promo look better)
                if self._sku["category_idx"][i] == 0:
                    bias = 0.15
                est = true_own + bias + rng.normal(0, ELASTICITY_NOISE_SIGMA)
                rows_sku_i.append(i)
                rows_sku_j.append(i)
                rows_region.append(REGIONS[r])
                rows_elast.append(round(est, 4))
                rows_type.append("own")

                # Cross-price elasticities (within same category only)
                cat = self._sku["category_idx"][i]
                for j in range(N_SKUS):
                    if j == i or self._sku["category_idx"][j] != cat:
                        continue
                    # Small positive cross elasticity (substitutes)
                    true_cross = rng.uniform(0.02, 0.20)
                    # Effect 3 boosted cross-elast between 6pk and 12pk in Cat D
                    if cat == 3 and (
                        (self._sku["primary_pack"][i] == 6 and self._sku["primary_pack"][j] == 12)
                        or (self._sku["primary_pack"][i] == 12 and self._sku["primary_pack"][j] == 6)
                    ):
                        true_cross = rng.uniform(0.35, 0.55)
                    est = true_cross + rng.normal(0, ELASTICITY_NOISE_SIGMA)
                    rows_sku_i.append(i)
                    rows_sku_j.append(j)
                    rows_region.append(REGIONS[r])
                    rows_elast.append(round(est, 4))
                    rows_type.append("cross")

        return {
            "sku_i": np.array(rows_sku_i),
            "sku_j": np.array(rows_sku_j),
            "region": np.array(rows_region),
            "elasticity": np.array(rows_elast),
            "type": np.array(rows_type),
        }

    # ------------------------------------------------------------------
    # Market share
    # ------------------------------------------------------------------

    def generate_market_share(self) -> Dict[str, np.ndarray]:
        """Weekly category-level market share by region (includes competitor)."""
        rng = np.random.default_rng(self.seed + 20)
        n = N_WEEKS * N_CATEGORIES * N_REGIONS
        weeks = np.repeat(np.arange(N_WEEKS), N_CATEGORIES * N_REGIONS)
        cats = np.tile(np.repeat(np.arange(N_CATEGORIES), N_REGIONS), N_WEEKS)
        regs = np.tile(np.arange(N_REGIONS), N_WEEKS * N_CATEGORIES)

        # Base market share per category
        base_share = np.array([0.22, 0.18, 0.25, 0.20, 0.15])
        share = base_share[cats].copy()

        # Seasonal variation
        t = 2.0 * np.pi * (weeks % 52) / 52.0
        share += 0.02 * np.sin(t + 0.5 * cats)

        # Category B decline + Q3 bump (Effect 4)
        cat_b = cats == 1
        share = np.where(cat_b, share - 0.0003 * weeks, share)
        q3_bump = 0.04 * np.exp(-((weeks % 52 - 32) ** 2) / 50.0)
        share = np.where(cat_b, share + q3_bump, share)

        # Regional jitter
        share += rng.normal(0, 0.008, n)

        # Competitor erosion (general)
        share -= 0.0001 * weeks

        share = share.clip(0.02, 0.50)

        cat_labels = np.array([CATEGORIES[c] for c in cats])
        reg_labels = np.array([REGIONS[r] for r in regs])

        return {
            "week": weeks,
            "category": cat_labels,
            "region": reg_labels,
            "market_share": np.round(share, 4),
        }

    # ------------------------------------------------------------------
    # I/O
    # ------------------------------------------------------------------

    @staticmethod
    def _write_csv(data: Dict[str, np.ndarray], path: str) -> None:
        """Write a dict-of-arrays to CSV."""
        keys = list(data.keys())
        n = len(data[keys[0]])
        with open(path, "w", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(keys)
            for i in range(n):
                writer.writerow([data[k][i] for k in keys])

    def generate_all(self, output_dir: str) -> None:
        """Generate all datasets and write to *output_dir*."""
        os.makedirs(output_dir, exist_ok=True)

        sales = self.generate_sales()
        self._write_csv(sales, os.path.join(output_dir, "sales_transactions.csv"))

        elast = self.generate_elasticities()
        self._write_csv(elast, os.path.join(output_dir, "price_elasticity.csv"))

        ms = self.generate_market_share()
        self._write_csv(ms, os.path.join(output_dir, "market_share.csv"))


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main(output_dir: str = "data", seed: int = DEFAULT_SEED) -> None:
    """Generate all BevCo datasets."""
    gen = BevCoGenerator(seed=seed)
    gen.generate_all(output_dir)


if __name__ == "__main__":
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "data"
    main(output_dir=out)
