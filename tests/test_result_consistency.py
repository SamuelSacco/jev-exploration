"""Prose figures must agree with the analysis scripts, checked against a fresh
recompute from the committed fixtures.

The repo's recurring failure mode is a corrected number fixed in the script but
left stale in a table, the README, the claims ledger, or a docstring (the
74% -> 61.7% calibration fix had to touch seven files by hand). These tests
make that staleness fail loudly: the headline figures in
analysis/CALIBRATION-TRANSFER.md and the claims ledger in docs/claims-audit.md
are recomputed here from the committed tier responses, through the same
function the script uses (analysis.calibration_set_size.headline_figures), and
compared to what the prose says, within rounding.

Skipped if the committed raw responses are absent. These pin findings, not
implementation: if a rerun legitimately moves the numbers, regenerate the JSON
(`python3 analysis/calibration_set_size.py --draws 40 --json
analysis/calibration_set_size.json`), update the prose from it, and see
docs/CORRECTION-CHECKLIST.md for the propagation order.
"""
import json
import os
import re

import pytest

from analysis import calibration_set_size as css

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def md_table_rows(text):
    """Every markdown table row as a list of stripped cells.

    Pipe-delimited rows only; the |---|---| separator line is skipped. Tiny and
    regex-based on purpose: it must not depend on a markdown library that could
    itself drift from what a human reads in the rendered doc.
    """
    rows = []
    for line in text.splitlines():
        match = re.match(r"\s*\|(.*)\|\s*$", line)
        if not match:
            continue
        cells = [cell.strip() for cell in match.group(1).split("|")]
        if cells and all(re.fullmatch(r":?-{2,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    return rows


def read_md(*parts):
    with open(os.path.join(HERE, *parts), encoding="utf-8") as fh:
        return fh.read()


@pytest.fixture(scope="module")
def fresh_sweep():
    """The sweep rerun from the committed fixtures, through the script's own
    main(), so the prose is checked against what the script would write today
    rather than against a stale committed JSON."""
    run = os.path.join(HERE, "lab", "runs", f"{css.TIER_RUN}-tiers-t1_trivial.jsonl")
    if not os.path.exists(run):
        pytest.skip("tier run not committed")
    out = os.path.join(HERE, ".tmp_fresh_sweep.json")
    try:
        assert css.main(["--draws", "40", "--json", out]) == 0
        with open(out, encoding="utf-8") as fh:
            return json.load(fh)
    finally:
        if os.path.exists(out):
            os.remove(out)


def budget_row(rows, budget):
    return next(r for r in rows if r and r[0] == str(budget))


def test_slope_only_row_matches_the_recomputed_sweep(fresh_sweep):
    """The headline row: budget 50, mean held-out ECE 0.0512, worst draw 0.1236,
    reduction 61.7%. If a table cell disagrees with the recomputed script
    output, this fails."""
    rows = md_table_rows(read_md("analysis", "CALIBRATION-TRANSFER.md"))
    row = budget_row(rows, 50)
    expected = css.headline_figures(fresh_sweep["transfers"], 50)
    assert row[1] == f"{expected['mean_held_out_ece']:.4f}", (
        f"table says {row[1]}, recomputed {expected['mean_held_out_ece']:.4f}"
    )
    assert row[2] == f"{expected['worst_draw']:.4f}", (
        f"table says {row[2]}, recomputed {expected['worst_draw']:.4f}"
    )


def test_every_budget_row_matches_the_recomputed_sweep(fresh_sweep):
    """All four numeric columns of every budget row, not just the headline."""
    rows = md_table_rows(read_md("analysis", "CALIBRATION-TRANSFER.md"))
    for budget in css.SIZES:
        expected = css.headline_figures(fresh_sweep["transfers"], budget)
        row = budget_row(rows, budget)
        assert row[1] == f"{expected['mean_held_out_ece']:.4f}", f"budget {budget} mean"
        assert row[2] == f"{expected['worst_draw']:.4f}", f"budget {budget} worst"
        assert row[3] == f"{expected['worst_multiple_of_baseline']:.1f}x", (
            f"budget {budget} multiple: table says {row[3]}"
        )
        assert row[4] == f"{expected['transfers_worse_than_nothing']} of 12", (
            f"budget {budget} worse-count: table says {row[4]}"
        )


def test_published_reduction_pct_is_the_held_out_number(fresh_sweep):
    """The prose claim 'the same budget gives **61.7%**' must be the held-out
    reduction the script computes, within rounding -- not the old contaminated
    74% figure."""
    text = read_md("analysis", "CALIBRATION-TRANSFER.md")
    match = re.search(r"gives \*\*([\d.]+)%\*\*", text)
    assert match, "could not find the published reduction figure in the prose"
    published = float(match.group(1))
    recomputed = fresh_sweep["headlines"]["reduction_pct"]
    assert abs(published - recomputed) <= 0.05, (
        f"prose says {published}%, recomputed {recomputed}%"
    )


def test_ledger_row_23_quotes_the_held_out_reduction(fresh_sweep):
    """docs/claims-audit.md row 23 says '62% held-out reduction at 50'. The
    ledger rounds to whole percent, so this asserts within one point."""
    rows = md_table_rows(read_md("docs", "claims-audit.md"))
    row = next(r for r in rows if r and r[0] == "23")
    evidence = " ".join(row)
    match = re.search(r"(\d+)% held-out reduction", evidence)
    assert match, f"row 23 does not state a held-out reduction: {row}"
    assert abs(int(match.group(1)) - fresh_sweep["headlines"]["reduction_pct"]) <= 0.5, (
        f"ledger says {match.group(1)}%, recomputed "
        f"{fresh_sweep['headlines']['reduction_pct']}%"
    )


def test_committed_results_artifact_is_fresh(fresh_sweep):
    """analysis/calibration_set_size.json must be what the script writes today.
    If the script is corrected and the JSON is not regenerated, the prose
    checks above would compare against a stale artifact -- this fails first."""
    with open(
        os.path.join(HERE, "analysis", "calibration_set_size.json"), encoding="utf-8"
    ) as fh:
        committed = json.load(fh)
    assert committed == fresh_sweep, (
        "committed analysis/calibration_set_size.json differs from a fresh rerun; "
        "regenerate it: python3 analysis/calibration_set_size.py --draws 40 "
        "--json analysis/calibration_set_size.json"
    )


def test_negation_table_is_held_out_slope_only():
    """N3: the negation table is the held-out slope-only procedure, not the old
    full-map numbers. Pins wiring, not just floats: (a) the slope came from
    the tier fit, not refit on negation, (b) the refit and score index sets
    are disjoint and cover the 80 items, (c) the four doc figures match a fresh
    recompute of negation_slope_only. Fails on the old code, which had no such
    function and printed full-map figures scored on all 80 items."""
    from analysis.calibration_transfer import (
        TIER_ORDER,
        TIER_RUN,
        negation_pairs,
        negation_slope_only,
    )
    from jevlab.calibration import fit_platt
    from lab.tiers.analyse import read_pass
    from lab.tiers.baselines import load

    run = os.path.join(HERE, "lab", "runs", "20260918T014148Z-negation.jsonl")
    if not os.path.exists(run):
        pytest.skip("negation run not committed")
    gold = {r["id"]: r["is_phishing"] for r in load()}
    tiers = {t: read_pass(TIER_RUN, t, 0, gold) for t in TIER_ORDER}
    negation = negation_pairs()
    assert len(negation) == 80

    text = read_md("analysis", "CALIBRATION-TRANSFER.md")
    section = text.split("## Does it reach a different task?", 1)[1]
    section = section.split("\n## ", 1)[0]
    doc_rows = {r[0]: r for r in md_table_rows(section) if r and r[0] in TIER_ORDER}
    assert len(doc_rows) == 4, (
        f"expected four tier rows in the negation table, got {list(doc_rows)}"
    )
    for fit_tier in TIER_ORDER:
        r = negation_slope_only(tiers[fit_tier], negation)
        assert r["slope"] == fit_platt(tiers[fit_tier]).a, (
            f"{fit_tier}: slope not from the tier fit"
        )
        assert not set(r["refit_idx"]) & set(r["score_idx"]), (
            f"{fit_tier}: refit and score sets overlap"
        )
        assert set(r["refit_idx"]) | set(r["score_idx"]) == set(range(80))
        row = doc_rows[fit_tier]
        assert row[1] == f"{r['ece_before']:.3f}", f"{fit_tier} before"
        assert row[2] == f"{r['ece_after']:.3f}", f"{fit_tier} after"
        assert row[3] == f"{r['ece_reduction']:.0%}", f"{fit_tier} reduction"
