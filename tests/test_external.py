"""Re-analysis tests. Skipped unless the source repos are cloned.

The point of these is that we reproduce each study's published figure before
reinterpreting it. A number we cannot reproduce is one we have no standing to
reinterpret, and an edge-convention mistake silently produced a plausible but
wrong ECE the first time this ran.
"""
import os

import pytest

from analysis.external.loaders import (
    load_jev_benchmark,
    load_phishing_bench,
    load_spam_eval,
)
from analysis.external.run import evaluate

BASE = os.environ.get("JEV_SOURCES", "/home/user")


def _require(path):
    full = os.path.join(BASE, path)
    if not os.path.isdir(full):
        pytest.skip(f"{path} not cloned; see analysis/external/loaders.py")
    return full


def test_jev_benchmark_ece_reproduces():
    """Right-closed bins. Left-closed gives 0.0488, which looks just as plausible."""
    studies = load_jev_benchmark(_require("themsquared/jev-benchmark"))
    assert studies, "no jev-benchmark results found"
    for study in studies:
        result = evaluate(study, trials=50)
        assert result["reproduced"], (
            f"{study.name}: recomputed {result['ece']}, "
            f"published {study.reported_ece}"
        )


def test_jev_benchmark_accuracy_reproduces():
    """55/60 = 91.7%. Thresholding a confidence at 0.5 gives 56/60 instead."""
    studies = load_jev_benchmark(_require("themsquared/jev-benchmark"))
    for study in studies:
        assert evaluate(study, trials=50)["accuracy"] == pytest.approx(0.917, abs=0.001)


def test_jev_benchmark_is_at_its_noise_floor():
    """The finding: at n=60 this study cannot measure calibration either way."""
    studies = load_jev_benchmark(_require("themsquared/jev-benchmark"))
    for study in studies:
        result = evaluate(study, trials=300)
        assert result["informative"] is False
        assert result["ratio"] < 2.0


def test_phishing_bench_ece_reproduces_from_published_bins():
    studies = load_phishing_bench(_require("anisselbd/jev-phishing-bench"))
    confidence = next(s for s in studies if s.variant == "verdict confidence")
    result = evaluate(confidence, trials=50)
    assert result["reproduced"], result
    assert result["bin_range"] == [0.5, 1.0], "their bins are not ours"


def test_phishing_bench_miscalibration_is_real():
    studies = load_phishing_bench(_require("anisselbd/jev-phishing-bench"))
    confidence = next(s for s in studies if s.variant == "verdict confidence")
    result = evaluate(confidence, trials=300)
    assert result["informative"] is True
    assert result["ratio"] > 4.0


def test_spam_eval_miscalibration_is_real_despite_clean_extremes():
    """The study reports only its extremes, which look excellent. At n=19.5k the
    middle of the distribution is far enough off to be unambiguous."""
    studies = load_spam_eval(_require("bitnovus/jev-spam-eval"))
    assert studies, "no spam-eval results found"
    best = next(s for s in studies if s.variant == "spam_structured_criteria")
    result = evaluate(best, trials=200)
    assert result["accuracy"] == pytest.approx(0.983, abs=0.002)
    assert result["informative"] is True


def test_every_loaded_study_declares_its_binning():
    for loader, path in (
        (load_jev_benchmark, "themsquared/jev-benchmark"),
        (load_phishing_bench, "anisselbd/jev-phishing-bench"),
    ):
        for study in loader(_require(path)):
            assert study.bins > 0
            assert study.edge in ("left", "right")
            assert study.quantity in ("confidence", "probability")
