"""Tests for jevlab/run_meta.py and the dataset versioning in task 3.

Everything here is offline: the metadata emitter is stdlib-only and the
dataset fingerprints are computed from the committed files.
"""
from __future__ import annotations

import hashlib
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from jevlab.run_meta import emit, format_header  # noqa: E402
from lab.domains import baselines as domains_baselines  # noqa: E402
from lab.tiers import baselines as tiers_baselines  # noqa: E402

REQUIRED_KEYS = {
    "run_id",
    "timestamp_utc",
    "repo_commit",
    "python",
    "packages",
    "datasets",
    "task",
    "args",
    "model_id",
    "transport",
}


def test_emit_returns_the_documented_schema():
    meta = emit("analysis.test", args={"x": 1}, datasets={"tiers": "1.0.0"})
    assert set(meta) == REQUIRED_KEYS


def test_run_ids_are_unique():
    assert emit("t")["run_id"] != emit("t")["run_id"]
    assert re.fullmatch(r"[0-9a-f]{32}", emit("t")["run_id"])


def test_timestamp_is_utc_iso_with_z():
    ts = emit("t")["timestamp_utc"]
    assert ts.endswith("Z")
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", ts)


def test_repo_commit_is_hex_or_unknown():
    commit = emit("t")["repo_commit"]
    assert commit == "unknown" or re.fullmatch(r"[0-9a-f]{40}", commit)


def test_python_version_format():
    assert re.fullmatch(r"\d+\.\d+\.\d+", emit("t")["python"])


def test_packages_reports_pytest():
    packages = emit("t")["packages"]
    assert "pytest" in packages
    for version in packages.values():
        assert version == "not installed" or isinstance(version, str)


def test_unknowns_when_source_records_nothing():
    meta = emit("t")
    assert meta["model_id"] == "unknown"
    assert meta["transport"] == "unknown"
    assert meta["datasets"] == {}
    assert meta["args"] == {}


def test_format_header_renders_every_field():
    meta = emit(
        "analysis.test",
        args={"method": "platt"},
        datasets={"tiers": "1.0.0 sha256:abc"},
        model_id="jev-1.13.0",
        transport={"jev": "sender", "local": "(unset)"},
    )
    header = format_header(meta)
    for needle in (
        "run_id",
        "timestamp_utc",
        "repo_commit",
        "python",
        "pytest",
        "dataset       tiers 1.0.0 sha256:abc",
        "task          analysis.test",
        "args",
        "model_id      jev-1.13.0",
        "transport",
        "jev: sender",
        "local: (unset)",
    ):
        assert needle in header, needle


def test_format_header_string_transport():
    header = format_header(emit("t", transport="some.sender"))
    assert "transport     some.sender" in header


def test_dataset_version_constants_exist():
    assert tiers_baselines.DATASET_NAME == "tiers"
    assert tiers_baselines.DATASET_VERSION == "1.0.0"
    assert domains_baselines.DATASET_NAME == "domains"
    assert domains_baselines.DATASET_VERSION == "1.0.0"


def test_fingerprint_matches_the_committed_file():
    for module in (tiers_baselines, domains_baselines):
        path = os.path.join(
            os.path.dirname(module.__file__), "dataset.jsonl"
        )
        with open(path, "rb") as fh:
            expected = hashlib.sha256(fh.read()).hexdigest()
        assert module.fingerprint() == expected
        assert module.fingerprint(path) == expected


def test_dataset_version_pins_semver_and_content():
    for module in (tiers_baselines, domains_baselines):
        version = module.dataset_version()
        assert version.startswith("1.0.0 sha256:")
        assert version == f"1.0.0 sha256:{module.fingerprint()}"


def test_fingerprint_is_stable_across_calls():
    assert tiers_baselines.fingerprint() == tiers_baselines.fingerprint()
    assert domains_baselines.fingerprint() == domains_baselines.fingerprint()
