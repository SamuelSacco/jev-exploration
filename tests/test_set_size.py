"""Tests for the calibration label-budget sweep.

The sweep exists because the published recipe's "about 50 labels" was never
measured. Its own first version had two methodological faults, both of which
these tests pin so they cannot come back: the refit set leaking into the
evaluation set, and the evaluation set shrinking as the budget grew.
"""
import random

import pytest

from analysis import calibration_set_size as css
from jevlab.calibration import PlattMap, apply_map
from jevlab.stats import ece


def squeezed(n=400, slope=2.3, seed=0):
    """Probabilities carrying a known squeeze, so a correction has work to do."""
    rng = random.Random(seed)
    inverse = PlattMap(a=1 / slope, b=0.0)
    pairs = []
    for _ in range(n):
        true_p = 0.02 + 0.96 * rng.random()
        pairs.append((inverse(true_p), rng.random() < true_p))
    return pairs


def test_the_evaluation_set_does_not_shrink_with_the_budget():
    """The artefact that made the curve turn back up at 150 labels."""
    pairs = squeezed()
    block = css.sweep_pair(squeezed(seed=1), pairs, [10, 50, 100], draws=3, eval_size=100)
    assert block["eval_size"] == 100
    assert {v["n_eval"] for v in block["sizes"].values()} == {100}


def test_budgets_that_do_not_fit_beside_the_evaluation_set_are_skipped():
    pairs = squeezed(n=120)
    block = css.sweep_pair(squeezed(seed=1), pairs, [10, 50, 100], draws=2, eval_size=100)
    assert set(block["sizes"]) == {10}


def test_held_out_scoring_is_not_the_contaminated_scoring():
    """If these were the same number the held-out fix would be doing nothing."""
    block = css.sweep_pair(squeezed(seed=1), squeezed(), [20], draws=25, eval_size=100)
    row = block["sizes"][20]
    assert row["held_out_ece"] != row["contaminated_ece"]


def test_the_correction_helps_on_average_at_a_reasonable_budget():
    block = css.sweep_pair(squeezed(seed=1), squeezed(), [75], draws=20, eval_size=100)
    assert block["sizes"][75]["held_out_ece"] < block["baseline_ece"]
    assert block["sizes"][75]["reduction"] > 0


def test_safe_budget_is_the_smallest_with_no_harmful_draw():
    results = {
        "a": {
            "baseline_ece": 0.10,
            "sizes": {
                10: {"held_out_worst": 0.40},
                50: {"held_out_worst": 0.09},
            },
        },
        "b": {
            "baseline_ece": 0.12,
            "sizes": {
                10: {"held_out_worst": 0.05},
                50: {"held_out_worst": 0.06},
            },
        },
    }
    assert css.safe_budget(results, [10, 50]) == 50


def test_safe_budget_is_zero_when_every_budget_can_harm():
    results = {
        "a": {"baseline_ece": 0.10, "sizes": {10: {"held_out_worst": 0.40},
                                              50: {"held_out_worst": 0.30}}},
    }
    assert css.safe_budget(results, [10, 50]) == 0


def test_knee_finds_the_smallest_budget_near_the_best():
    block = {
        "sizes": {
            10: {"held_out_ece": 0.10},
            30: {"held_out_ece": 0.051},
            50: {"held_out_ece": 0.050},
        }
    }
    assert css.knee(block, tolerance=0.05) == 30
    assert css.knee(block, tolerance=0.0) == 50


def test_a_tiny_budget_can_be_worse_than_no_correction_at_all():
    """The operational finding: below ~30 labels the recipe can backfire."""
    block = css.sweep_pair(squeezed(seed=1), squeezed(), [10], draws=40, eval_size=100)
    assert block["sizes"][10]["held_out_worst"] > block["sizes"][10]["held_out_ece"]


def test_the_sweep_is_deterministic_for_a_seed():
    a = css.sweep_pair(squeezed(seed=1), squeezed(), [30], draws=5, eval_size=100, seed=7)
    b = css.sweep_pair(squeezed(seed=1), squeezed(), [30], draws=5, eval_size=100, seed=7)
    assert a == b


def test_main_runs_on_the_committed_data(tmp_path, capsys):
    out = tmp_path / "sweep.json"
    assert css.main(["--draws", "3", "--json", str(out)]) == 0
    text = capsys.readouterr().out
    assert "worse than doing nothing" in text
    import json

    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["safe_budget"] in css.SIZES or doc["safe_budget"] == 0
    assert doc["published_budget"] == 50
