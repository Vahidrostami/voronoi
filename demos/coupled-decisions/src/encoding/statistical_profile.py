"""Encode quantitative data into StatisticalProfile objects.

Transforms 1-D numeric arrays (e.g. weekly sales for one SKU) into
reasoning-ready statistical representations with:
  * Distribution parameters (mean, std, skew, kurtosis)
  * Confidence intervals (t-distribution based)
  * Trend / seasonality decomposition (SMA + Fourier)
  * Structural break detection (CUSUM-like)

Only depends on stdlib + numpy + scipy.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

import numpy as np
from scipy import stats as sp_stats

from ..core.types import StatisticalProfile
from ..core.config import Config


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encode_quantitative(
    data: "np.ndarray",
    *,
    ci_level: float = 0.95,
    seasonality_period: int = 52,
    break_sensitivity: float = 2.0,
    fourier_harmonics: int = 3,
) -> StatisticalProfile:
    """Encode a 1-D numeric array into a :class:`StatisticalProfile`.

    Parameters
    ----------
    data : array-like
        1-D array of observations (e.g. weekly sales for one SKU).
    ci_level : float
        Confidence interval level (default 0.95).
    seasonality_period : int
        Expected seasonality period in observations (default 52 weeks).
    break_sensitivity : float
        Sigma multiplier for CUSUM structural break detection.
    fourier_harmonics : int
        Number of Fourier harmonics for seasonality extraction.

    Returns
    -------
    StatisticalProfile
    """
    data = np.asarray(data, dtype=np.float64).ravel()
    n = len(data)
    if n == 0:
        return StatisticalProfile()

    # --- Distribution parameters ---
    mean = float(np.mean(data))
    std = float(np.std(data, ddof=1)) if n > 1 else 0.0
    skew = float(sp_stats.skew(data, bias=False)) if n > 2 else 0.0
    kurtosis = float(sp_stats.kurtosis(data, bias=False)) if n > 3 else 0.0

    # --- Confidence interval (t-distribution) ---
    ci_lower, ci_upper = _confidence_interval(mean, std, n, ci_level)

    # --- Trend: centred simple moving average ---
    trend = _extract_trend(data, seasonality_period)

    # --- Seasonality: Fourier-based extraction from detrended series ---
    trend_arr = np.array(trend)
    detrended = data - trend_arr
    seasonality = _extract_seasonality(
        detrended, seasonality_period, fourier_harmonics,
    )

    # --- Residual ---
    season_tiled = np.tile(seasonality, (n // len(seasonality)) + 1)[:n]
    residual = (data - trend_arr - season_tiled).tolist()

    # --- Structural breaks (CUSUM) ---
    breaks = _detect_structural_breaks(data, mean, break_sensitivity)

    return StatisticalProfile(
        mean=mean,
        std=std,
        skew=skew,
        kurtosis=kurtosis,
        ci_lower=ci_lower,
        ci_upper=ci_upper,
        ci_level=ci_level,
        trend=trend,
        seasonality=seasonality,
        residual=residual,
        structural_breaks=breaks,
        n_observations=n,
        metadata={
            "seasonality_period": seasonality_period,
            "fourier_harmonics": fourier_harmonics,
            "break_sensitivity": break_sensitivity,
        },
    )


def encode_quantitative_from_config(
    data: "np.ndarray",
    config: Config,
) -> StatisticalProfile:
    """Convenience wrapper using parameters from a :class:`Config`."""
    return encode_quantitative(
        data,
        ci_level=config.confidence_interval_level,
        break_sensitivity=config.temporal_break_sensitivity,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _confidence_interval(
    mean: float, std: float, n: int, level: float,
) -> tuple[float, float]:
    """Compute a *level*-confidence interval using the t-distribution."""
    if n > 1 and std > 0:
        alpha = 1.0 - level
        t_crit = float(sp_stats.t.ppf(1.0 - alpha / 2, df=n - 1))
        margin = t_crit * std / math.sqrt(n)
        return mean - margin, mean + margin
    return mean, mean


def _extract_trend(data: np.ndarray, period: int) -> List[float]:
    """Extract trend via centred simple moving average."""
    n = len(data)
    window = min(period, max(3, n // 4))
    if n >= window:
        kernel = np.ones(window) / window
        return np.convolve(data, kernel, mode="same").tolist()
    return data.tolist()


def _extract_seasonality(
    detrended: np.ndarray,
    period: int,
    n_harmonics: int,
) -> List[float]:
    """Extract seasonality using Fourier decomposition.

    Fits *n_harmonics* sine/cosine pairs at the fundamental frequency
    and its harmonics.  Falls back to cycle-averaging when the series
    is shorter than one full period.
    """
    n = len(detrended)

    if n >= period and n_harmonics > 0:
        # Fourier approach
        t = np.arange(n, dtype=np.float64)
        reconstructed = np.zeros(period, dtype=np.float64)
        for k in range(1, n_harmonics + 1):
            freq = 2.0 * np.pi * k / period
            cos_basis = np.cos(freq * t)
            sin_basis = np.sin(freq * t)
            a_k = 2.0 / n * np.dot(detrended, cos_basis)
            b_k = 2.0 / n * np.dot(detrended, sin_basis)
            t_period = np.arange(period, dtype=np.float64)
            reconstructed += a_k * np.cos(freq * t_period) + b_k * np.sin(freq * t_period)
        return reconstructed.tolist()

    # Fallback: simple cycle average
    if n >= period:
        season = np.zeros(period)
        counts = np.zeros(period)
        for i in range(n):
            idx = i % period
            season[idx] += detrended[i]
            counts[idx] += 1
        counts[counts == 0] = 1
        return (season / counts).tolist()

    return detrended.tolist()


def _detect_structural_breaks(
    data: np.ndarray,
    mean: float,
    sensitivity: float,
) -> List[int]:
    """Detect structural breaks using a CUSUM-like approach.

    Computes the cumulative sum of deviations from the mean.  A break
    is flagged when the change in CUSUM between consecutive observations
    exceeds ``sensitivity * cusum_std``.
    """
    n = len(data)
    if n <= 10:
        return []

    cusum = np.cumsum(data - mean)
    cusum_std = float(np.std(cusum))
    if cusum_std <= 0:
        return []

    threshold = sensitivity * cusum_std
    breaks: List[int] = []
    for i in range(1, n):
        if abs(cusum[i] - cusum[i - 1]) > threshold:
            breaks.append(i)
    return breaks
