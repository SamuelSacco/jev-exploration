"""Tests for the raw-data provenance audit.

`lab/runs/README.md` requires every published live-run figure to ship its raw
responses. The rule was stated and not enforced, and four runs reached main
without any. These tests make the rule mechanical.
"""
import glob
import os

import pytest

from analysis import provenance as pv

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_audit_classifies_every_claim():
    rows = pv.audit()
    assert rows
    for row in rows:
        assert row["status"] in {"BACKED", "UNVERIFIABLE", "not yet run"}
        assert row["claim"] and row["runner"] and row["pattern"]


def test_a_claim_with_raw_data_is_backed():
    rows = {r["claim"]: r for r in pv.audit()}
    gradient = next(r for c, r in rows.items() if c.startswith("Difficulty gradient"))
    assert gradient["status"] == "BACKED"
    assert gradient["files"]
    assert gradient["lines"] > 0


def test_unrun_experiments_are_not_reported_as_violations():
    rows = {r["claim"]: r["status"] for r in pv.audit()}
    for claim, status in rows.items():
        if "not yet run" in status:
            entry = next(r for r in pv.CLAIMS if r["claim"] == claim)
            assert entry["published_in"] == [], (
                f"{claim} is cited somewhere but has no data"
            )


def test_strict_mode_passes_when_every_published_claim_is_backed():
    """2026-09-24: the missing raw runs landed, so --strict is the gate now.

    If a future claim is published without its raw responses, --strict must
    fail again; CI runs it, and this test pins that expectation.
    """
    assert pv.main(["--strict"]) == 0
    assert pv.main([]) == 0


def test_provenance_covers_every_runner():
    """A new experiment that publishes a figure must appear in CLAIMS.

    Without this the audit rots: someone adds a runner, publishes its number,
    and the checker stays silent because it was never told to look.
    """
    runners = set()
    for pattern in ("lab/run_*.py", "lab/exp_*.py", "lab/probe_*.py"):
        for path in glob.glob(os.path.join(HERE, pattern)):
            runners.add(os.path.relpath(path, HERE))
    covered = {entry["runner"] for entry in pv.CLAIMS}
    assert runners <= covered, f"runners with no provenance entry: {runners - covered}"


@pytest.mark.parametrize("entry", pv.CLAIMS, ids=lambda e: e["runner"])
def test_every_cited_document_exists(entry):
    for doc in entry["published_in"]:
        assert os.path.exists(os.path.join(HERE, doc)), doc
