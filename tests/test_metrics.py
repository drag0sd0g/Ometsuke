"""Known-answer tests.

Every assertion here is a case where the right answer is known in advance, independent
of the implementation. That is the whole point: reading the code more carefully is a
weak defence against a metric that runs clean and returns a plausible wrong number.
"""

from __future__ import annotations

import numpy as np
import pytest

from ometsuke import metrics


def test_perfect_classifier_scores_exactly_one():
    labels = [0, 0, 0, 1, 1, 1]
    scores = [0.1, 0.2, 0.3, 0.7, 0.8, 0.9]
    assert metrics.auc(labels, scores) == 1.0


def test_inverted_classifier_scores_exactly_zero():
    labels = [0, 0, 0, 1, 1, 1]
    scores = [0.9, 0.8, 0.7, 0.3, 0.2, 0.1]
    assert metrics.auc(labels, scores) == 0.0


def test_random_scores_sit_near_half_and_the_interval_covers_it():
    rng = np.random.default_rng(0)
    labels = rng.integers(0, 2, size=400).tolist()
    scores = rng.random(400).tolist()
    result = metrics.bootstrap_ci(metrics.auc, labels, scores, draws=500, seed=1)
    assert abs(result["point"] - 0.5) < 0.08
    assert result["low"] < 0.5 < result["high"], "a coin flip must not look like signal"


def test_shuffled_labels_destroy_mcc():
    rng = np.random.default_rng(7)
    labels = rng.integers(0, 2, size=600)
    predictions = rng.permutation(labels)
    assert abs(metrics.mcc(labels.tolist(), predictions.tolist())) < 0.1


def test_clustered_interval_is_wider_than_the_naive_one():
    """The assertion the whole clustering argument rests on.

    Twenty companies, five near-identical filings each. Treating those 100 filings as
    independent draws understates the uncertainty; resampling companies does not. If
    this ever fails, `groups=` is not doing anything and every published interval is
    too narrow.
    """
    rng = np.random.default_rng(3)
    labels, scores, groups = [], [], []
    for company in range(20):
        label = company % 2
        base = rng.normal(0.6 if label else 0.4, 0.05)
        for _ in range(5):
            labels.append(label)
            scores.append(base + rng.normal(0, 0.005))
            groups.append(f"E{company:04d}")

    naive = metrics.bootstrap_ci(metrics.auc, labels, scores, draws=1000, seed=5)
    clustered = metrics.bootstrap_ci(metrics.auc, labels, scores, groups=groups,
                                     draws=1000, seed=5)
    naive_width = naive["high"] - naive["low"]
    clustered_width = clustered["high"] - clustered["low"]
    assert clustered_width > naive_width, (
        f"clustered {clustered_width:.3f} should exceed naive {naive_width:.3f}"
    )


def test_bootstrap_refuses_a_single_class_sample():
    with pytest.raises(ValueError, match="no usable bootstrap draws"):
        metrics.bootstrap_ci(metrics.auc, [1, 1, 1, 1], [0.1, 0.2, 0.3, 0.4], draws=50)


def test_wilson_matches_published_values():
    low, high = metrics.wilson_interval(38, 50)
    assert (round(low, 3), round(high, 3)) == (0.626, 0.857)
    # Degenerate counts must stay inside [0, 1] rather than running off the end.
    assert metrics.wilson_interval(0, 10)[0] == 0.0
    assert metrics.wilson_interval(10, 10)[1] == 1.0


def test_paired_bootstrap_finds_no_difference_between_identical_systems():
    rng = np.random.default_rng(11)
    labels = rng.integers(0, 2, size=200).tolist()
    scores = rng.random(200).tolist()
    result = metrics.paired_bootstrap(metrics.auc, labels, scores, scores, draws=400)
    assert result["point"] == 0.0
    assert not result["excludes_zero"]


def test_paired_bootstrap_detects_a_real_difference():
    rng = np.random.default_rng(13)
    labels = rng.integers(0, 2, size=300)
    strong = (labels + rng.normal(0, 0.35, size=300)).tolist()
    weak = rng.random(300).tolist()
    result = metrics.paired_bootstrap(metrics.auc, labels.tolist(), strong, weak, draws=400)
    assert result["point"] > 0.2
    assert result["excludes_zero"]
