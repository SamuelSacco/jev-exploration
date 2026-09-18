"""Difficulty-gradient dataset tests.

These guard the two properties that make the experiment interpretable: labels
that are recoverable from the text, and tiers that actually differ in difficulty.
Both were violated by earlier versions of the generator; see lab/tiers/README.md.
"""
import json
import os
import re

import pytest

from lab.tiers import baselines, generate

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(HERE, "lab", "tiers", "dataset.jsonl")


@pytest.fixture(scope="module")
def rows():
    return baselines.load(DATASET)


# ------------------------------------------------------------------- structure


def test_dataset_is_the_committed_size(rows):
    assert len(rows) == 800
    for tier in baselines.TIER_ORDER:
        assert sum(1 for r in rows if r["tier"] == tier) == 200


def test_labels_are_balanced_in_every_tier(rows):
    """Chance is then 50% everywhere, so tiers are directly comparable."""
    for tier in baselines.TIER_ORDER:
        subset = [r for r in rows if r["tier"] == tier]
        assert sum(1 for r in subset if r["is_phishing"]) == len(subset) // 2


def test_ids_are_unique(rows):
    ids = [r["id"] for r in rows]
    assert len(set(ids)) == len(ids)


def test_generation_is_deterministic():
    """The committed file must be rebuildable, so it can be audited by rerunning."""
    a = generate.generate(per_tier=20, seed=7)
    b = generate.generate(per_tier=20, seed=7)
    assert a == b


def test_committed_dataset_matches_the_generator(rows):
    """If these drift, the dataset is no longer reproducible from source."""
    regenerated = generate.generate(per_tier=200, seed=20260918)
    assert [r["id"] for r in regenerated] == [r["id"] for r in rows]
    assert [r["text"] for r in regenerated] == [r["text"] for r in rows]


# ----------------------------------------------------------- label recoverability


def test_every_item_carries_a_decisive_element(rows):
    """The failure that made the first t4 unlabelable: items with nothing in them
    that determines the label."""
    assert all(r.get("decisive") for r in rows)


def test_decisive_topics_are_used_by_both_classes(rows):
    """Matched pairs. If a topic appeared on only one side, the topic itself would
    leak the label."""
    by_topic = {}
    for r in rows:
        by_topic.setdefault(r["decisive"], set()).add(r["label"])
    lopsided = {t for t, labels in by_topic.items() if len(labels) < 2}
    assert not lopsided, f"topics appearing on only one side: {lopsided}"


def test_cue_counts_match_the_tier_definition(rows):
    for r in rows:
        mix = generate.TIERS[r["tier"]]
        assert len(r["cues_with_label"]) == mix["with"]
        assert len(r["cues_against_label"]) == mix["against"]


def test_t3_has_no_cues_in_either_direction(rows):
    for r in (x for x in rows if x["tier"] == "t3_hard"):
        assert not r["cues_with_label"] and not r["cues_against_label"]


def test_t4_cues_all_point_against_the_label(rows):
    for r in (x for x in rows if x["tier"] == "t4_adversarial"):
        assert len(r["cues_against_label"]) == 2
        assert not r["cues_with_label"]


# ------------------------------------------------------- difficulty manipulation


def test_cue_baseline_collapses_across_tiers(rows):
    """The manipulation check. If this fails the tiers are not distinct and the
    experiment is void, so it is asserted rather than assumed."""
    scored = baselines.score(rows, baselines.CUE_RE)
    assert scored["t1_trivial"]["rate"] > 0.85
    assert scored["t4_adversarial"]["rate"] < 0.35
    assert baselines.gradient_is_real(scored)


def test_cue_baseline_is_below_chance_on_t4(rows):
    """Surface cues must point the wrong way, not merely be absent."""
    scored = baselines.score(rows, baselines.CUE_RE)
    assert scored["t4_adversarial"]["ci95"][1] < 0.5


def test_cue_baseline_is_monotone_across_tiers(rows):
    scored = baselines.score(rows, baselines.CUE_RE)
    rates = [scored[t]["rate"] for t in baselines.TIER_ORDER]
    assert rates == sorted(rates, reverse=True)


def test_decisive_baseline_is_not_flat(rows):
    """The second design failure: an unmatched decisive pool gave ~85% on every
    tier, which would have faked a 'calibration holds' result."""
    scored = baselines.score(rows, baselines.DECISIVE_RE)
    spread = scored["t1_trivial"]["rate"] - scored["t4_adversarial"]["rate"]
    assert spread > 0.05


def test_decisive_baseline_is_reported_not_hidden():
    """It is the number Jev must be read against, so it must reach the output."""
    import inspect

    source = inspect.getsource(baselines.main)
    assert "DECISIVE_RE" in source


# -------------------------------------------------------------------- the runner


def test_one_question_wording_for_every_item():
    """Difficulty must be the only thing that varies; a per-tier prompt would
    confound the manipulation with the measurement."""
    from lab import run_tiers

    assert "{id}" in run_tiers.INSTRUCTIONS
    assert set(run_tiers.CRITERIA) == {"true", "false"}


def test_batches_cover_every_item_exactly_once(rows):
    from lab import run_tiers

    items = [r for r in rows if r["tier"] == "t1_trivial"]
    chunks = run_tiers.batches(items, 40)
    flat = [i["id"] for c in chunks for i in c]
    assert flat == [i["id"] for i in items]


def test_payload_stays_well_under_the_token_budget(rows):
    """The documented request budget is ~32k tokens."""
    from lab import run_tiers

    for tier in baselines.TIER_ORDER:
        items = [r for r in rows if r["tier"] == tier]
        for chunk in run_tiers.batches(items, 40):
            state, questions = run_tiers.build_payload(chunk)
            assert len(state) / 4 < 16000, "state too close to the budget"
            assert len(questions) == len(chunk)


def test_dry_run_makes_no_calls(capsys, monkeypatch):
    from lab import run_tiers

    def explode(*a, **kw):
        raise AssertionError("--dry-run must not call the API")

    monkeypatch.setattr(run_tiers.JevClient, "ask", explode)
    assert run_tiers.main(["--dry-run"]) == 0
    assert "Total calls" in capsys.readouterr().out


def test_every_question_id_is_an_item_id(rows):
    from lab import run_tiers

    chunk = [r for r in rows if r["tier"] == "t4_adversarial"][:10]
    _, questions = run_tiers.build_payload(chunk)
    assert set(questions) == {i["id"] for i in chunk}
