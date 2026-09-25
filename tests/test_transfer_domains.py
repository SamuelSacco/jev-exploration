"""Tests for the issue #9 cross-domain transfer experiment.

The runner cannot be exercised here without a credential, so the parts that can
go wrong silently are tested directly: the dataset's controls, the analysis
arithmetic against data with a slope planted in it, and the verdict logic in
both directions. A test that can only pass proves nothing, so each verdict has a
companion that makes it fail.
"""
import json
import math
import os
import random

import pytest

from analysis import transfer_domains as td
from jevlab.calibration import PlattMap
from lab import exp_transfer as ex
from lab.domains import baselines as bl
from lab.domains import generate as gen

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------- dataset


def test_dataset_rebuilds_byte_for_byte():
    """The committed file must be the generator's output, not an edited copy."""
    with open(os.path.join(HERE, "lab", "domains", "dataset.jsonl"), encoding="utf-8") as fh:
        committed = [json.loads(line) for line in fh if line.strip()]
    assert committed == gen.generate()


def test_labels_are_assigned_before_the_text_exists():
    """Same property analysis/circularity.py checks for the gradient."""
    with open(os.path.join(HERE, "lab", "domains", "generate.py"), encoding="utf-8") as fh:
        src = fh.read()
    assign = src.index("positive = i in positives")
    build = src.index("built = build(spec, i, positive, rng)")
    assert assign < build
    for token in ("JevClient", "jevlab.client", "urllib", "requests", "api.typesafe"):
        assert token not in src


def test_every_slice_is_balanced_as_specified():
    rows = bl.load()
    for spec in gen.SLICES:
        got = [r for r in rows if r["slice"] == spec["name"]]
        positives = sum(1 for r in got if r["is_positive"])
        assert positives / len(got) == pytest.approx(spec["base_rate"])


def test_the_two_code_security_slices_differ_only_in_base_rate():
    """H2 is only interpretable if the domain really is held fixed."""
    rows = bl.load()
    a = [r for r in rows if r["slice"] == "code_security"]
    b = [r for r in rows if r["slice"] == "code_security_rare"]
    assert {r["domain"] for r in a} == {r["domain"] for r in b} == {"code_security"}
    assert {r["question"] for r in a} == {r["question"] for r in b}
    assert a[0]["base_rate"] != b[0]["base_rate"]


def test_cues_do_not_carry_the_label():
    """The rejected design: label-specific cue pools made this 100%."""
    rows = bl.load()
    for name in bl.SLICE_ORDER:
        if name.endswith("_rare"):
            continue  # a skewed base rate moves an accuracy figure on its own
        got = bl.cue_leakage([r for r in rows if r["slice"] == name])
        assert got["accuracy"] < 0.60, f"{name} leaks the label through its cues"


def test_the_leakage_check_catches_a_leak():
    """Planted: a cue that appears only beside positives."""
    rows = [
        dict(r, cues=["LEAK"] if r["is_positive"] else ["ordinary"])
        for r in bl.load()
        if r["slice"] == "code_security"
    ]
    assert bl.cue_leakage(rows)["accuracy"] > 0.95


def test_crossval_folds_are_stratified():
    """An index-parity split put one label in each fold and scored 0.0%."""
    rows = [r for r in bl.load() if r["slice"] == "code_security"]
    assert bl.crossval(rows, "text")["accuracy"] > 0.5


def test_lexical_bar_is_reported_and_beatable_in_principle():
    rows = bl.load()
    for name in bl.SLICE_ORDER:
        bar = bl.lexical([r for r in rows if r["slice"] == name])
        assert 0.5 < bar["accuracy"] < 1.0


# --------------------------------------------------------------------- analysis


def synthetic(slope: float, intercept: float, n: int = 120, base: float = 0.5, seed: int = 7):
    """Probabilities carrying a known Platt distortion of a calibrated signal.

    Draw a true probability, flip the outcome from it, then push the stated
    probability through the inverse map so that fitting Platt on the result
    should recover (slope, intercept).
    """
    rng = random.Random(seed)
    pairs = []
    for _ in range(n):
        true_p = rng.random() * 0.98 + 0.01
        true_p = min(0.99, max(0.01, true_p * base * 2))
        outcome = rng.random() < true_p
        z = (math.log(true_p / (1 - true_p)) - intercept) / slope
        stated = 1 / (1 + math.exp(-z))
        pairs.append((min(0.99, max(0.01, stated)), outcome))
    return pairs


def test_fit_recovers_a_planted_slope():
    pairs = synthetic(slope=2.34, intercept=0.0, n=600)
    got = td.fit_slice(pairs)
    assert got["slope"] == pytest.approx(2.34, abs=0.5)


def test_h1_is_proven_when_every_slope_sits_in_the_email_band():
    fits = {s: {"slope": 2.3, "intercept": 0.1} for s in
            ("code_security", "lab_safety", "contract_liability")}
    assert td.verdicts(fits, {})["H1_slope_transfers"]["verdict"] == "PROVEN"


def test_h1_is_refuted_when_a_slope_leaves_the_falsifying_band():
    fits = {
        "code_security": {"slope": 2.3, "intercept": 0.1},
        "lab_safety": {"slope": 4.9, "intercept": 0.1},
        "contract_liability": {"slope": 2.4, "intercept": 0.1},
    }
    block = td.verdicts(fits, {})["H1_slope_transfers"]
    assert block["verdict"] == "REFUTED"
    assert block["outside_falsifying_band"] == ["lab_safety"]


def test_h1_is_partial_when_a_slope_is_outside_the_band_but_not_falsifying():
    fits = {
        "code_security": {"slope": 2.3, "intercept": 0.1},
        "lab_safety": {"slope": 2.9, "intercept": 0.1},
        "contract_liability": {"slope": 2.4, "intercept": 0.1},
    }
    assert td.verdicts(fits, {})["H1_slope_transfers"]["verdict"] == "PARTIAL"


def _h2_boot(slope_ci, intercept_ci):
    """A canned h2_bootstrap output for testing the verdict rule."""
    return {
        "resamples": 2000,
        "resamples_used": 2000,
        "resamples_skipped": 0,
        "seed": 0,
        "alpha": 0.05,
        "stable": True,
        "slope_ci": slope_ci,
        "intercept_ci": intercept_ci,
    }


def test_h2_is_proven_only_when_the_cis_clear_the_thresholds():
    """H2's preregistered thresholds are intercept > 0.8 and slope < 0.5. The
    verdict is PROVEN only when the point estimates clear them AND the 95%
    bootstrap CIs clear them too: the intercept CI's lower bound above 0.8,
    the slope CI's upper bound below 0.5."""
    moved_intercept = {
        "code_security": {"slope": 2.30, "intercept": 0.10, "identified": True},
        "code_security_rare": {"slope": 2.35, "intercept": -1.20, "identified": True},
    }
    clearing = _h2_boot(slope_ci=(0.01, 0.40), intercept_ci=(0.95, 1.60))
    block = td.verdicts(moved_intercept, {}, h2=clearing)["H2_decomposition_is_real"]
    assert block["verdict"] == "PROVEN"
    assert block["slope_moved_ci95"] == [0.01, 0.40]
    assert block["intercept_moved_ci95"] == [0.95, 1.60]

    moved_slope = {
        "code_security": {"slope": 2.30, "intercept": 0.10, "identified": True},
        "code_security_rare": {"slope": 4.00, "intercept": 0.15, "identified": True},
    }
    block = td.verdicts(moved_slope, {})["H2_decomposition_is_real"]
    assert block["verdict"] == "REFUTED"


def test_h2_is_partial_when_point_estimates_clear_but_cis_straddle():
    """The downgrade the review asked for: thresholds cleared by the point
    estimates alone earn PARTIAL, never PROVEN."""
    fits = {
        "code_security": {"slope": 2.30, "intercept": 0.10, "identified": True},
        "code_security_rare": {"slope": 2.35, "intercept": -1.20, "identified": True},
    }
    straddling = _h2_boot(slope_ci=(0.02, 0.62), intercept_ci=(0.71, 1.90))
    block = td.verdicts(fits, {}, h2=straddling)["H2_decomposition_is_real"]
    assert block["verdict"] == "PARTIAL"
    assert "bootstrap" in block["why"]
    assert "0.71" in block["why"] and "0.62" in block["why"]


def test_h2_without_cis_cannot_be_proven():
    """The unit-test seam: without a bootstrap the best H2 can do is PARTIAL,
    even when the point estimates clear the thresholds."""
    fits = {
        "code_security": {"slope": 2.30, "intercept": 0.10, "identified": True},
        "code_security_rare": {"slope": 2.35, "intercept": -1.20, "identified": True},
    }
    block = td.verdicts(fits, {})["H2_decomposition_is_real"]
    assert block["verdict"] == "PARTIAL"
    assert "bootstrap" in block["why"]


def test_h3_is_refuted_by_any_increase_however_small():
    recipes = {
        "code_security": {"ece_before": 0.10, "ece_after": 0.03, "reduction": 0.70},
        "lab_safety": {"ece_before": 0.10, "ece_after": 0.1001, "reduction": -0.001},
    }
    block = td.verdicts({}, recipes)["H3_recipe_works_out_of_domain"]
    assert block["verdict"] == "REFUTED"
    assert block["increased_in"] == ["lab_safety"]


def test_h3_is_partial_when_it_helps_but_by_less_than_half():
    recipes = {"code_security": {"ece_before": 0.10, "ece_after": 0.07, "reduction": 0.30}}
    assert td.verdicts({}, recipes)["H3_recipe_works_out_of_domain"]["verdict"] == "PARTIAL"


def test_recipe_reports_how_many_positives_its_label_budget_bought():
    """The preregistered risk on the rare slice: ~12 positives in 50 labels."""
    rows = bl.load()
    gold = {r["id"]: r["is_positive"] for r in rows if r["slice"] == "code_security_rare"}
    pairs = [(0.7 if g else 0.3, g) for _, g in sorted(gold.items())]
    got = td.recipe(pairs)
    assert got["refit_labels"] == 50
    assert 5 <= got["refit_positives"] <= 20


def test_recipe_scores_only_the_held_out_remainder(monkeypatch):
    """A3 regression: recipe() used to refit on the first 50 items and then
    score all of them again -- live train-on-test. The probabilities handed to
    ece_with_floor must never intersect the refit set's probabilities."""
    seen = []

    def spy(pairs, trials=300):
        seen.append({p for p, _ in pairs})
        return {"ece": 0.1, "floor_mean": 0.05, "ratio": 0.5}

    monkeypatch.setattr(td, "ece_with_floor", spy)
    pairs = synthetic(slope=2.34, intercept=0.0, n=100, seed=7)
    labels = 50
    out = td.recipe(pairs, labels=labels)
    refit_probs = {p for p, _ in pairs[:labels]}
    assert len(seen) == 2  # before and after, both on held-out pairs
    for probs in seen:
        assert not (probs & refit_probs)
    assert out["n_scored"] == len(pairs) - labels


def test_analyse_end_to_end_on_planted_answers():
    rows = bl.load()
    doc = {"started_at": "test", "transport": "test", "slices": {}}
    for name in ("code_security", "lab_safety", "contract_liability"):
        gold = {r["id"]: r["is_positive"] for r in rows if r["slice"] == name}
        mapping = PlattMap(a=1 / 2.34, b=0.0)
        doc["slices"][name] = {
            "probabilities": {
                qid: mapping(0.88 if g else 0.12) for qid, g in gold.items()
            }
        }
    result = td.analyse(doc, rows)
    assert set(result["fits"]) == {"code_security", "lab_safety", "contract_liability"}
    for name, fit in result["fits"].items():
        assert fit["slope"] > 0, name
    assert result["verdicts"]["H2_decomposition_is_real"]["verdict"] == "UNVERIFIABLE"


def test_h2_pins_the_bootstrapped_cis_on_planted_answers():
    """The honest end-to-end on committed fixtures.

    Answers are planted from the committed dataset labels (the runner's real
    input was never committed): a Platt distortion with slope ~2.34 on every
    slice and an intercept shift planted on code_security_rare. The bootstrap
    is seeded, so the verdict and the CI numbers below are exactly what the
    script produces -- pinned here so any change to the verdict rule or the
    bootstrap breaks loudly instead of drifting silently.
    """
    rows = bl.load()
    doc = {"started_at": "test", "transport": "test", "slices": {}}
    for name in ("code_security", "lab_safety", "contract_liability"):
        gold = {r["id"]: r["is_positive"] for r in rows if r["slice"] == name}
        mapping = PlattMap(a=1 / 2.34, b=0.0)
        doc["slices"][name] = {
            "probabilities": {
                qid: mapping(0.88 if g else 0.12) for qid, g in gold.items()
            }
        }
    gold = {r["id"]: r["is_positive"] for r in rows if r["slice"] == "code_security_rare"}
    mapping = PlattMap(a=1 / 2.34, b=1.3)
    doc["slices"]["code_security_rare"] = {
        "probabilities": {
            qid: mapping(0.88 if g else 0.12) for qid, g in gold.items()
        }
    }
    result = td.analyse(doc, rows)
    block = result["verdicts"]["H2_decomposition_is_real"]
    assert block["verdict"] == "PROVEN"
    assert block["slope_moved"] == pytest.approx(0.1626, abs=1e-4)
    assert block["intercept_moved"] == pytest.approx(6.6034, abs=1e-4)
    assert block["slope_moved_ci95"] == pytest.approx([0.059, 0.3046], abs=1e-4)
    assert block["intercept_moved_ci95"] == pytest.approx([6.4473, 6.7553], abs=1e-4)
    assert block["bootstrap_resamples_used"] == 2000
    assert block["bootstrap_resamples_skipped"] == 0


def test_h2_downgrade_triggers_on_a_real_bootstrap_with_wide_cis():
    """Noisy synthetic data at n=120 where the point estimates clear the 0.8/0.5
    thresholds but the paired bootstrap CIs straddle them: the verdict must be
    PARTIAL, the honest downgrade, not PROVEN."""
    base = synthetic(2.34, 0.0, n=120, seed=21)
    rare = synthetic(2.34, -1.3, n=120, seed=22)
    fits = {
        "code_security": td.fit_slice(base),
        "code_security_rare": td.fit_slice(rare),
    }
    assert fits["code_security"]["identified"]
    assert fits["code_security_rare"]["identified"]
    d_slope = abs(fits["code_security_rare"]["slope"] - fits["code_security"]["slope"])
    d_int = abs(fits["code_security_rare"]["intercept"] - fits["code_security"]["intercept"])
    assert d_int > td.H2_INTERCEPT_MOVED and d_slope < td.H2_SLOPE_STABLE

    h2 = td.h2_bootstrap(base, rare)
    assert h2["stable"] is True
    s_lo, s_hi = h2["slope_ci"]
    i_lo, i_hi = h2["intercept_ci"]
    assert s_hi > td.H2_SLOPE_STABLE or i_lo < td.H2_INTERCEPT_MOVED

    block = td.verdicts(fits, {}, h2=h2)["H2_decomposition_is_real"]
    assert block["verdict"] == "PARTIAL"
    assert "bootstrap" in block["why"]


# ----------------------------------------------------------------------- runner


def test_runner_sizes_itself_without_a_credential(capsys):
    assert ex.main(["--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "Total calls: 36" in out
    assert "H1_slope_transfers" in out


def test_runner_refuses_to_spend_when_the_gate_fails(monkeypatch, capsys):
    monkeypatch.setattr(ex, "check_gate", lambda rows: {
        "lexical_bar": {}, "cue_only": {}, "slices_comparable": False
    })
    assert ex.main([]) == 2
    assert "Dataset gate failed" in capsys.readouterr().err


def test_runner_batches_without_leaking_ids_between_questions():
    rows = [r for r in bl.load() if r["slice"] == "code_security"][:4]
    state, questions = ex.build(rows)
    assert set(questions) == {r["id"] for r in rows}
    for row in rows:
        assert row["id"] in state
        assert questions[row["id"]]["type"] == "noul"
        assert set(questions[row["id"]]["criteria"]) == {"true", "false"}


def test_runner_carries_its_preregistration_into_the_results_file():
    """So the hypotheses cannot be edited after the numbers arrive."""
    assert set(ex.PREREGISTERED) == set(td.verdicts({}, {}))


# ---------------------------------------------------------- identifiability guard


def test_a_nondiscriminating_slice_is_unverifiable_not_refuted():
    """The trap the first smoke run walked into.

    Newton's method on probabilities that carry no signal returns a slope in the
    billions. Read naively that is "the slope did not transfer", which would be
    a finding manufactured from a numerical failure.
    """
    rng = random.Random(5)
    noise = [(round(rng.random(), 2), rng.random() < 0.5) for _ in range(120)]
    fit = td.fit_slice(noise)
    assert fit["identified"] is False
    assert fit["discriminates"] is False
    assert fit["slope_plausible"] is False

    block = td.verdicts({"code_security": fit}, {})["H1_slope_transfers"]
    assert block["verdict"] == "UNVERIFIABLE"
    assert block["unidentified"] == ["code_security"]


def test_a_discriminating_slice_is_identified():
    rng = random.Random(5)
    pairs = []
    for _ in range(200):
        gold = rng.random() < 0.5
        pairs.append((0.85 if gold else 0.15, gold))
    fit = td.fit_slice(pairs)
    assert fit["identified"] is True
    assert fit["auc"] > 0.9
    assert abs(fit["slope"]) < 25


def test_h2_needs_both_slices_identified():
    rng = random.Random(6)
    noise = td.fit_slice([(round(rng.random(), 2), rng.random() < 0.5) for _ in range(120)])
    good = {"slope": 2.3, "intercept": 0.1, "identified": True, "auc": 0.9}
    block = td.verdicts(
        {"code_security": good, "code_security_rare": noise}, {}
    )["H2_decomposition_is_real"]
    assert block["verdict"] == "UNVERIFIABLE"


def test_the_discrimination_threshold_scales_with_the_sample():
    """A fixed threshold passes a coin flip at n=120 and fails real signal at n=20."""
    from jevlab.stats import auc_null_se

    big = [(0.5, i % 2 == 0) for i in range(600)]
    small = [(0.5, i % 2 == 0) for i in range(20)]
    assert auc_null_se(big) < auc_null_se(small)
    assert auc_null_se([(0.5, True)]) == 0.0  # one class only


def test_auc_is_half_with_no_signal_and_one_with_perfect_separation():
    from jevlab.stats import auc

    assert auc([(0.9, True), (0.1, False)]) == 1.0
    assert auc([(0.1, True), (0.9, False)]) == 0.0
    assert auc([(0.5, True), (0.5, False)]) == 0.5
    assert auc([(0.7, True)]) == 0.5  # one class only: undefined, reported as chance
