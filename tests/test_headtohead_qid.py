"""Regression tests for the head-to-head qid misalignment fix.

The bug: pairs() threw the qid away, returning bare (p, gold) tuples, and
difference_ci() sorted each arm separately and zipped by index, truncated to
the shorter side. The runner writes local probabilities as a dict keyed by
qid and drops unparseable local replies (never imputed), so one mid-array
drop silently paired every later local item with the wrong Jev item in the
paired bootstrap.

The fix: pairs() returns (qid, p, gold) triples and every paired statistic
inner-joins on qid before pairing. All synthetic, pre-existing entry points
only.
"""
import pytest

from analysis import headtohead as hh


def _battery():
    """20 items, all gold True.

    Jev hits the first half (q01..q10) and misses the second; local is the
    reverse, with q10 dropped mid-array (an unparseable reply: dropped, never
    imputed, recorded in local["unparsed"] by the runner).
    """
    qids = [f"q{i:02d}" for i in range(1, 21)]
    gold = {q: True for q in qids}
    jev = {"probabilities": {q: (0.9 if i < 10 else 0.1) for i, q in enumerate(qids)}}
    local = {
        "probabilities": {
            q: (0.1 if i < 10 else 0.9) for i, q in enumerate(qids) if q != "q10"
        },
        "unparsed": ["q10"],
        "latency_p50_s": 1.0,
    }
    return gold, jev, local


def test_qid_join_pairs_by_qid_not_by_index():
    """The mid-array drop must drop its pair, not shift every pair after it."""
    gold, jev_block, local_block = _battery()
    jev_pairs = hh.pairs(jev_block, gold)
    local_pairs = hh.pairs(local_block, gold)
    assert len(jev_pairs) == 20
    assert len(local_pairs) == 19
    ci, n_pairs, fallback = hh.paired_difference(local_pairs, jev_pairs)
    # Nine -1 deltas (q01..q09) then ten +1 deltas (q11..q20); deterministic
    # seeded bootstrap over that multiset.
    assert n_pairs == 19
    assert fallback is False
    assert ci == [-0.3684, 0.4737]
    assert hh.difference_ci(local_pairs, jev_pairs) == [-0.3684, 0.4737]


def test_pairs_keeps_the_qid_on_every_row():
    """pairs() returns (qid, p, gold) triples; side_scores reads both shapes."""
    gold, jev_block, _ = _battery()
    rows = hh.pairs(jev_block, gold)
    assert rows == [
        (q, p, True) for q, p in sorted(jev_block["probabilities"].items())
    ]
    assert all(len(row) == 3 for row in rows)
    # qids missing from gold are excluded, not carried through with a guess.
    assert hh.pairs({"probabilities": {"q01": 0.9, "zzz": 0.1}}, {"q01": True}) == [
        ("q01", 0.9, True)
    ]
    scores = hh.side_scores(rows)
    assert scores["n"] == 20 and scores["accuracy"] == 0.5
    legacy = hh.side_scores([(p, g) for _, p, g in rows])
    assert legacy == scores


def test_analyse_records_pair_counts_pairing_key_and_unparsed():
    gold, jev_block, local_block = _battery()
    # The adversarial arm's Jev side drops a qid too, so the typed-vs-
    # adversarial paired statistic also exercises the inner join.
    adv_jev = {
        "probabilities": {
            q: p for q, p in jev_block["probabilities"].items() if q != "q05"
        }
    }
    arms = {}
    for arm in ("typed", "adversarial"):
        arms[arm] = {
            "n": 20,
            "primitive": "noul",
            "gold": gold,
            "jev": adv_jev if arm == "adversarial" else jev_block,
            "local": local_block,
        }
    doc = {
        "started_at": "t",
        "transport_jev": "j",
        "transport_local": "l",
        "preregistered": {"x": 1},
        "arms": arms,
    }
    result = hh.analyse(doc)
    entry = result["arms"]["typed"]
    assert entry["difference_ci"] == [-0.3684, 0.4737]
    assert entry["difference_pairs_n"] == 19
    assert entry["paired_by"] == "qid"
    assert entry["local_unparsed"] == 1
    # The typed-vs-adversarial paired statistic gets the same treatment.
    assert entry["vs_adversarial_pairs_n"] == 19
    assert entry["vs_adversarial_paired_by"] == "qid"


def test_disjoint_qids_give_an_empty_interval():
    """A qid in only one arm drops its pair; none shared means no pairs."""
    a = [("qa1", 0.9, True), ("qa2", 0.1, False)]
    b = [("qb1", 0.9, True), ("qb2", 0.1, False)]
    assert hh.difference_ci(a, b) == [0.0, 0.0]
    ci, n_pairs, fallback = hh.paired_difference(a, b)
    assert (ci, n_pairs, fallback) == ([0.0, 0.0], 0, False)


def test_legacy_rows_without_qids_fall_back_to_index_pairing_loudly(capsys):
    """Old bare pairs keep the old index-pairing behavior -- never silently."""
    gold, jev_block, local_block = _battery()
    jev_pairs = hh.pairs(jev_block, gold)
    local_pairs = hh.pairs(local_block, gold)
    bare_jev = [(p, g) for _, p, g in jev_pairs]
    bare_local = [(p, g) for _, p, g in local_pairs]
    # The buggy pairing: truncated to 19, q11..q20 shifted one slot against
    # q10..q19 -- this is exactly the number the old code would have printed.
    assert hh.difference_ci(bare_local, bare_jev) == [-0.4211, 0.4211]
    err = capsys.readouterr().err
    assert (
        "headtohead: pairing 19 items by INDEX (no qids present) -- "
        "a dropped item misaligns every pair after it" in err
    )
