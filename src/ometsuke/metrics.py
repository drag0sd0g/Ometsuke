"""Scores, and the error bars that make them mean something.

The point estimates here are thin wrappers over scikit-learn, deliberately: the
benchmark's published figures come from the same functions, so ours are comparable by
construction. The real content of this module is the intervals.

Two things in here are places where a silent bug produces a plausible, wrong number:

  * **Clustering.** The 122 positives in the test split come from only 50 companies.
    Filings from one company describe one scandal in near-identical language. Resampling
    filings treats them as independent draws and produces an interval that is too narrow
    — confidently wrong, and nothing looks broken. `bootstrap_ci` therefore resamples
    *groups*, and `test_metrics.py` asserts a clustered interval comes out wider than a
    naive one on the same data. If that assertion ever fails, the clustering is not
    working.

  * **Pairing.** Comparing two systems scored on the same items by building two
    independent intervals throws away the pairing and badly loses power. `paired_bootstrap`
    resamples once and applies the same draw to both.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence

import numpy as np
from sklearn.metrics import matthews_corrcoef, roc_auc_score


def auc(labels: Sequence[int], scores: Sequence[float]) -> float:
    """Ranking quality: P(a random positive outranks a random negative), ties at 0.5."""
    return float(roc_auc_score(np.asarray(labels), np.asarray(scores)))


def mcc(labels: Sequence[int], predictions: Sequence[int]) -> float:
    """Decision quality over the confusion matrix, robust to class imbalance."""
    return float(matthews_corrcoef(np.asarray(labels), np.asarray(predictions)))


def wilson_interval(successes: int, trials: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a single proportion.

    Not the normal approximation, which misbehaves near 0 and 1, and not a bootstrap,
    which is unnecessary machinery for one proportion.
    """
    if trials <= 0:
        raise ValueError("trials must be positive")
    p = successes / trials
    denominator = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / denominator
    margin = (z / denominator) * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials))
    return max(0.0, centre - margin), min(1.0, centre + margin)


def _resample_indices(
    groups: Sequence[str] | None, n: int, rng: np.random.Generator
) -> np.ndarray:
    """One bootstrap draw: over groups when given, otherwise over rows."""
    if groups is None:
        return rng.integers(0, n, size=n)
    members: dict[str, list[int]] = {}
    for index, group in enumerate(groups):
        members.setdefault(group, []).append(index)
    keys = list(members)
    drawn = rng.integers(0, len(keys), size=len(keys))
    return np.concatenate([members[keys[k]] for k in drawn])


def bootstrap_ci(
    metric: Callable[[np.ndarray, np.ndarray], float],
    labels: Sequence[int],
    scores: Sequence[float],
    groups: Sequence[str] | None = None,
    draws: int = 2000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, float | int]:
    """Percentile bootstrap interval, clustered by `groups` when supplied.

    Draws that end up with a single class are skipped — the metric is undefined there —
    and counted, so a sample too small or too imbalanced to support an interval shows up
    as a small `draws_used` rather than as a confident number.
    """
    labels_array = np.asarray(labels)
    scores_array = np.asarray(scores)
    rng = np.random.default_rng(seed)
    values: list[float] = []
    for _ in range(draws):
        index = _resample_indices(groups, len(labels_array), rng)
        drawn_labels = labels_array[index]
        if len(np.unique(drawn_labels)) < 2:
            continue
        values.append(metric(drawn_labels, scores_array[index]))
    if not values:
        raise ValueError("no usable bootstrap draws — sample too small or single-class")
    ordered = np.sort(np.asarray(values))
    return {
        "point": float(metric(labels_array, scores_array)),
        "low": float(np.quantile(ordered, alpha / 2)),
        "high": float(np.quantile(ordered, 1 - alpha / 2)),
        "draws_used": len(values),
        "draws_requested": draws,
    }


def paired_bootstrap(
    metric: Callable[[np.ndarray, np.ndarray], float],
    labels: Sequence[int],
    scores_a: Sequence[float],
    scores_b: Sequence[float],
    groups: Sequence[str] | None = None,
    draws: int = 2000,
    seed: int = 42,
    alpha: float = 0.05,
) -> dict[str, float | int]:
    """Interval on the *difference* between two systems scored on the same items.

    An interval excluding zero is evidence the systems differ; one that straddles zero
    means the observed gap is within what resampling alone produces.
    """
    labels_array = np.asarray(labels)
    a_array = np.asarray(scores_a)
    b_array = np.asarray(scores_b)
    if not (len(labels_array) == len(a_array) == len(b_array)):
        raise ValueError("paired bootstrap needs both systems scored on the same items")
    rng = np.random.default_rng(seed)
    deltas: list[float] = []
    for _ in range(draws):
        index = _resample_indices(groups, len(labels_array), rng)
        drawn_labels = labels_array[index]
        if len(np.unique(drawn_labels)) < 2:
            continue
        deltas.append(
            metric(drawn_labels, a_array[index]) - metric(drawn_labels, b_array[index])
        )
    if not deltas:
        raise ValueError("no usable bootstrap draws")
    ordered = np.sort(np.asarray(deltas))
    return {
        "point": float(metric(labels_array, a_array) - metric(labels_array, b_array)),
        "low": float(np.quantile(ordered, alpha / 2)),
        "high": float(np.quantile(ordered, 1 - alpha / 2)),
        "draws_used": len(deltas),
        "excludes_zero": bool(
            np.quantile(ordered, alpha / 2) > 0 or np.quantile(ordered, 1 - alpha / 2) < 0
        ),
    }
