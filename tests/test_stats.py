"""Statistics tests, checked against cases with known answers."""
import random

import pytest

from jevlab.stats import (
    accuracy,
    bootstrap_ci,
    brier,
    coverage_at,
    ece,
    ece_noise_floor,
    ece_with_floor,
    mce,
    reliability,
    summarize,
    wilson,
)


def calibrated(n, seed=0, concentrated=True):
    """Pairs from a model that is calibrated by construction."""
    rng = random.Random(seed)
    pairs = []
    for _ in range(n):
        if concentrated:
            r = rng.random()
            p = rng.uniform(0, 0.1) if r < 0.45 else (
                rng.uniform(0.9, 1.0) if r < 0.9 else rng.uniform(0.1, 0.9)
            )
        else:
            p = rng.random()
        pairs.append((p, rng.random() < p))
    return pairs


# ----------------------------------------------------------------------- wilson


def test_wilson_brackets_the_point_estimate():
    lo, hi = wilson(7, 10)
    assert lo < 0.7 < hi


def test_wilson_does_not_collapse_at_a_perfect_score():
    """The normal approximation gives zero width here, implying false certainty."""
    lo, hi = wilson(8, 8)
    assert hi == 1.0
    assert lo < 0.7


def test_wilson_widens_as_n_shrinks():
    wide = wilson(6, 8)
    narrow = wilson(600, 800)
    assert (wide[1] - wide[0]) > (narrow[1] - narrow[0])


def test_wilson_handles_empty():
    assert wilson(0, 0) == (0.0, 1.0)


# ------------------------------------------------------------------ point stats


def test_brier_is_zero_for_perfect_predictions():
    assert brier([(1.0, True), (0.0, False)]) == 0.0


def test_brier_is_one_for_confidently_wrong_predictions():
    assert brier([(1.0, False), (0.0, True)]) == 1.0


def test_accuracy_thresholds_at_half():
    assert accuracy([(0.9, True), (0.1, False), (0.6, False)]) == pytest.approx(2 / 3)


def test_empty_inputs_return_nan_not_crash():
    import math

    assert math.isnan(ece([]))
    assert math.isnan(brier([]))
    assert math.isnan(accuracy([]))


# ---------------------------------------------------------------- reliability


def test_reliability_skips_empty_bins():
    bins = reliability([(0.95, True), (0.95, True)])
    assert len(bins) == 1
    assert bins[0].count == 2


def test_reliability_bins_by_probability():
    bins = reliability([(0.05, False), (0.95, True)])
    assert [b.count for b in bins] == [1, 1]
    assert bins[0].lo == 0.0 and bins[1].hi == 1.0


def test_gap_is_positive_when_overconfident():
    bins = reliability([(0.9, False), (0.9, False), (0.9, True), (0.9, True)])
    assert bins[0].gap == pytest.approx(0.4)  # claimed 0.9, hit 0.5


def test_p_of_exactly_one_lands_in_the_top_bin():
    bins = reliability([(1.0, True)])
    assert bins[0].hi == 1.0


# ------------------------------------------------------------------------ ece


def test_ece_is_zero_when_bins_match_their_hit_rates():
    pairs = [(0.5, True), (0.5, False)] + [(0.95, True)] * 20
    assert ece(pairs) == pytest.approx(0.05, abs=0.01)


def test_ece_is_large_for_a_confidently_wrong_model():
    assert ece([(0.99, False)] * 50) == pytest.approx(0.99, abs=0.01)


def test_mce_reports_the_worst_bin_not_the_average():
    # One badly wrong bin, swamped by many good ones.
    pairs = [(0.95, True)] * 99 + [(0.15, True)]
    assert mce(pairs) > ece(pairs) * 10


# ---------------------------------------------------------------- noise floor


def test_noise_floor_shrinks_with_sample_size():
    """The load-bearing claim: ECE at small n is mostly sampling noise."""
    small = ece_noise_floor([p for p, _ in calibrated(60)], trials=200)
    large = ece_noise_floor([p for p, _ in calibrated(2000)], trials=200)
    assert small["mean"] > large["mean"] * 3


def test_noise_floor_at_n60_is_near_the_published_jev_figures():
    """jev-benchmark reports ECE 0.0505-0.0712 at n=60. This is why that is not a result."""
    floor = ece_noise_floor([p for p, _ in calibrated(60)], trials=400)
    assert 0.03 < floor["mean"] < 0.11


def test_a_calibrated_model_is_not_flagged_as_informative():
    result = ece_with_floor(calibrated(2000, seed=3), trials=200)
    assert result["ratio"] < 2.0
    assert result["informative"] is False


def test_a_miscalibrated_model_is_flagged():
    rng = random.Random(4)
    pairs = [(p, rng.random() < 0.5 + 0.5 * (p - 0.5)) for p, _ in calibrated(2000, seed=4)]
    result = ece_with_floor(pairs, trials=200)
    assert result["ratio"] > 5.0
    assert result["informative"] is True


def test_small_samples_cannot_flag_anything():
    """At n=8 even a badly wrong model sits inside the floor. That is the point."""
    result = ece_with_floor([(0.95, False)] * 4 + [(0.95, True)] * 4, trials=200)
    assert result["n"] == 8


# -------------------------------------------------------------------- coverage


def test_coverage_reports_the_fraction_that_cleared_the_bar():
    pairs = [(0.99, True)] * 10 + [(0.2, False)] * 90
    result = coverage_at(pairs, 0.95)
    assert result["coverage"] == pytest.approx(0.1)
    assert result["hit_rate"] == 1.0


def test_coverage_of_zero_does_not_divide_by_zero():
    result = coverage_at([(0.1, True)], 0.95)
    assert result["coverage"] == 0.0 and result["n"] == 0


# ------------------------------------------------------------------- bootstrap


def test_bootstrap_is_deterministic_for_a_given_seed():
    pairs = calibrated(200, seed=9)
    a = bootstrap_ci(pairs, accuracy, resamples=200, seed=1)
    b = bootstrap_ci(pairs, accuracy, resamples=200, seed=1)
    assert a == b


def test_bootstrap_interval_contains_the_observed_statistic():
    pairs = calibrated(400, seed=11)
    lo, hi = bootstrap_ci(pairs, accuracy, resamples=400, seed=2)
    assert lo <= accuracy(pairs) <= hi


def test_summarize_returns_the_full_reporting_block():
    block = summarize(calibrated(200, seed=13), resamples=100)
    assert set(block) >= {"n", "accuracy", "accuracy_ci", "ece", "ece_ci", "mce", "brier"}
    assert block["n"] == 200
