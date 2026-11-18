"""Paired bootstrap confidence intervals for matched-scenario comparisons."""
from __future__ import annotations

import numpy as np


def paired_bootstrap_diff(a: list[float], b: list[float], n_boot: int = 10000, seed: int = 12345, ci: float = 0.95):
    """Bootstrap the mean paired difference (a - b) over matched units.

    Returns a dict with the point estimate, CI bounds, and the fraction of
    resamples with diff < 0 (a one-sided significance read).
    """
    a = np.asarray(a, dtype=float)
    b = np.asarray(b, dtype=float)
    if a.shape != b.shape:
        raise ValueError("paired arrays must have equal length")
    diff = a - b
    rng = np.random.default_rng(seed)
    n = len(diff)
    idx = rng.integers(0, n, size=(n_boot, n))
    boot_means = diff[idx].mean(axis=1)
    lo = float(np.quantile(boot_means, (1 - ci) / 2))
    hi = float(np.quantile(boot_means, 1 - (1 - ci) / 2))
    return {
        "n_pairs": int(n),
        "mean_diff": float(diff.mean()),
        "ci_low": lo,
        "ci_high": hi,
        "frac_diff_below_zero": float((boot_means < 0).mean()),
        "frac_diff_above_zero": float((boot_means > 0).mean()),
    }


def rate_ci(successes: int, total: int, n_boot: int = 10000, seed: int = 999, ci: float = 0.95):
    """Bootstrap CI for a simple rate."""
    if total == 0:
        return {"rate": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "n": 0}
    data = np.zeros(total)
    data[:successes] = 1.0
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, total, size=(n_boot, total))
    boot = data[idx].mean(axis=1)
    return {
        "rate": successes / total,
        "ci_low": float(np.quantile(boot, (1 - ci) / 2)),
        "ci_high": float(np.quantile(boot, 1 - (1 - ci) / 2)),
        "n": int(total),
    }
