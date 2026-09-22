"""Regression tests on the calibration-transfer result, against the real run.

Skipped if the committed raw responses are absent. These pin findings, not
implementation: if a refactor quietly changes the conclusion, this fails.
"""
import os

import pytest

from analysis.calibration_transfer import TIER_RUN, negation_pairs
from jevlab.calibration import apply_map, fit_platt, fit_platt_intercept
from jevlab.stats import ece
from lab.tiers.analyse import read_pass
from lab.tiers.baselines import TIER_ORDER, load

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="module")
def tiers():
    path = os.path.join(HERE, "lab", "runs", f"{TIER_RUN}-tiers-t1_trivial.jsonl")
    if not os.path.exists(path):
        pytest.skip("tier run not committed")
    gold = {r["id"]: r["is_phishing"] for r in load()}
    return {t: read_pass(TIER_RUN, t, 0, gold) for t in TIER_ORDER}


def test_slope_is_stable_across_tiers(tiers):
    """The transferable part. Fitted independently on four tiers it stays in a
    narrow band, which is what makes one correction reusable."""
    slopes = [fit_platt(tiers[t]).a for t in TIER_ORDER]
    assert min(slopes) > 2.0 and max(slopes) < 2.8
    assert max(slopes) - min(slopes) < 0.6


def test_intercept_is_not_stable_across_tiers(tiers):
    """The part that does not transfer, and the reason full-map transfer can hurt."""
    intercepts = [fit_platt(tiers[t]).b for t in TIER_ORDER]
    assert max(intercepts) - min(intercepts) > 1.5


def test_full_map_transfer_can_make_calibration_worse(tiers):
    """t3 -> t4 is the failure case, consistent across all three passes. Pinned so
    it is not forgotten when someone recommends transferring a whole map."""
    worse = ece(apply_map(tiers["t4_adversarial"], fit_platt(tiers["t3_hard"])))
    assert worse > ece(tiers["t4_adversarial"])


def test_slope_only_transfer_never_makes_it_worse(tiers):
    """The recommendation. Every one of the twelve transfers must improve."""
    for fit_tier in TIER_ORDER:
        slope = fit_platt(tiers[fit_tier]).a
        for test_tier in TIER_ORDER:
            if fit_tier == test_tier:
                continue
            test = tiers[test_tier]
            mapping = fit_platt_intercept(test[:50], slope)
            after = ece(apply_map(test, mapping))
            assert after < ece(test), f"{fit_tier} -> {test_tier} got worse"


def test_slope_only_beats_the_full_map_on_average(tiers):
    full, slope_only = [], []
    for fit_tier in TIER_ORDER:
        slope = fit_platt(tiers[fit_tier]).a
        for test_tier in TIER_ORDER:
            if fit_tier == test_tier:
                continue
            test = tiers[test_tier]
            full.append(ece(apply_map(test, fit_platt(tiers[fit_tier]))))
            slope_only.append(ece(apply_map(test, fit_platt_intercept(test[:50], slope))))
    assert sum(slope_only) / len(slope_only) < sum(full) / len(full)


def test_transfer_does_not_change_accuracy(tiers):
    """Monotone maps cannot reorder, so the 0.5 threshold decision is preserved
    only if the map does not cross it -- worth asserting rather than assuming."""
    mapping = fit_platt(tiers["t1_trivial"])
    before = tiers["t4_adversarial"]
    after = apply_map(before, mapping)
    acc = lambda pairs: sum(1 for p, h in pairs if (p >= 0.5) == h) / len(pairs)
    assert acc(after) == pytest.approx(acc(before), abs=0.02)


def test_transfer_reaches_a_different_task(tiers):
    """The negation probe: different wording, different construction, 100% accuracy."""
    negation = negation_pairs()
    if not negation:
        pytest.skip("negation run not committed")
    mapping = fit_platt(tiers["t1_trivial"])
    assert ece(apply_map(negation, mapping)) < ece(negation)
