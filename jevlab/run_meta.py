"""Standard run metadata for offline analyses.

Every offline analysis that reads committed experiment output emits the same
provenance header, so a printed figure can always be traced back to the
conditions that produced it: which code, which data, which arguments, and
which model the underlying responses came from.

Schema (all values are plain JSON types):

    run_id        UUID4 hex of THIS analysis invocation. It is not the
                  experiment's run id: rerunning the analysis emits a new one.
    timestamp_utc ISO-8601 UTC timestamp of emission, second precision,
                  trailing "Z".
    repo_commit   `git rev-parse HEAD` of the repo the analysis ran from, or
                  "unknown" when the tree is not a git checkout. Local only;
                  no network.
    python        sys.version split to "major.minor.micro".
    packages      {name: version} for the non-stdlib distributions this repo's
                  tooling relies on. The repo is stdlib-only by design
                  (pyproject declares no runtime dependencies), so today that
                  is just pytest; missing distributions report "not installed"
                  rather than raising. Versions are read with
                  importlib.metadata, never by importing the package.
    datasets      {dataset_name: version_string} for every dataset the
                  analysis read. Version strings come from the dataset
                  modules (e.g. lab.tiers.baselines.DATASET_VERSION) and
                  pin the exact file content as "1.0.0 sha256:<full hex>":
                  the semantic version marks the frozen label set, the hash
                  catches any silent edit. See task 3.
    task          Dotted path of the analysis, e.g.
                  "analysis.calibration_transfer".
    args          The parsed CLI arguments of this invocation, as a dict.
    model_id      The model that served the underlying experiment responses,
                  read from the committed raw data (e.g. "jev-1.13.0"), or
                  "unknown" when the source file records none. Never guessed.
    transport     How requests reached the model for the underlying run: a
                  string (see jevlab.transport.describe_sender) or, for
                  two-sided batteries, a {"jev": ..., "local": ...} dict.
                  "unknown" when the committed data records none.

`emit()` builds the dict. `print_header()` renders it as a stdout block the
three wired analyses print before their own output. Nothing here touches the
network.
"""
from __future__ import annotations

import datetime
import importlib.metadata
import os
import subprocess
import sys
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The repo is stdlib-only by design; these are the only non-stdlib
# distributions its tooling relies on. Keep the list honest: add a name here
# only when repo code actually needs that distribution.
KEY_PACKAGES = ("pytest",)


def _repo_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return out.stdout.strip() or "unknown"


def _package_versions() -> dict:
    versions = {}
    for name in KEY_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not installed"
    return versions


def emit(
    task: str,
    *,
    args: dict | None = None,
    datasets: dict | None = None,
    model_id: str | None = None,
    transport: str | dict | None = None,
) -> dict:
    """Build the run-metadata dict for one analysis invocation.

    All arguments are recorded, not interpreted: pass what the analysis's
    own data sources report, and leave model_id/transport as None (recorded
    as "unknown") when the committed data records nothing.
    """
    return {
        "run_id": uuid.uuid4().hex,
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "repo_commit": _repo_commit(),
        "python": ".".join(str(p) for p in sys.version_info[:3]),
        "packages": _package_versions(),
        "datasets": dict(datasets or {}),
        "task": task,
        "args": dict(args or {}),
        "model_id": model_id if model_id else "unknown",
        "transport": transport if transport is not None else "unknown",
    }


def format_header(meta: dict) -> str:
    """Render the metadata as a fixed stdout block."""
    lines = ["run metadata"]
    lines.append(f"  run_id        {meta['run_id']}")
    lines.append(f"  timestamp_utc {meta['timestamp_utc']}")
    lines.append(f"  repo_commit   {meta['repo_commit']}")
    lines.append(f"  python        {meta['python']}")
    for name, version in meta["packages"].items():
        lines.append(f"  package       {name} {version}")
    for name, version in meta["datasets"].items():
        lines.append(f"  dataset       {name} {version}")
    lines.append(f"  task          {meta['task']}")
    if meta["args"]:
        lines.append(f"  args          {meta['args']}")
    lines.append(f"  model_id      {meta['model_id']}")
    transport = meta["transport"]
    if isinstance(transport, dict):
        lines.append("  transport")
        for side, desc in transport.items():
            lines.append(f"    {side}: {desc}")
    else:
        lines.append(f"  transport     {transport}")
    return "\n".join(lines)


def print_header(meta: dict) -> None:
    """Print the metadata block, followed by a blank line."""
    print(format_header(meta))
    print()
