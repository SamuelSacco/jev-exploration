"""Which published figures are backed by committed raw responses, and which are not.

    python3 analysis/provenance.py          # report
    python3 analysis/provenance.py --strict # exit 1 if any claim is unbacked

No API key and no network.

`lab/runs/README.md` states the rule: every number this repo publishes from a
live run has its raw responses committed, because summaries cannot be re-binned
or re-checked afterwards. The rule was stated and then not enforced, so it broke
quietly. An audit of main on 2026-09-24 found four runs published with no raw
data behind them at all.

This makes the rule checkable. Each entry names a claim, the run that produced
it, the raw files that would back it, and where it is published. A claim whose
files are absent is UNVERIFIABLE from this repository, whoever ran it and
however carefully they reported it.

The point is not to delete those claims. It is that a reader should be able to
tell, without knowing the project's history, which numbers they can recompute
and which they are taking on trust.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "lab", "runs")

# Every figure in this repo that came from a live call. Extend this when a new
# experiment publishes a number; test_provenance_covers_every_runner keeps it
# honest by failing when a runner exists with no entry here.
CLAIMS = [
    {
        "claim": "Difficulty gradient: accuracy and ECE per tier (B1, B2)",
        "run": "20260918T013027Z",
        "pattern": "20260918T013027Z-tiers-*.jsonl",
        "published_in": ["lab/tiers/FINDINGS.md", "docs/claims-audit.md", "README.md"],
        "runner": "lab/run_tiers.py",
    },
    {
        "claim": "Negation probe: 80/80 items, 40/40 pairs resolved",
        "run": "20260918T014148Z",
        "pattern": "20260918T014148Z-negation.jsonl",
        "published_in": ["docs/claims-audit.md", "README.md"],
        "runner": "lab/run_demos.py",
    },
    {
        "claim": "Triage demo: n=12, every result overlapping a trivial baseline",
        "run": "20260918T005803Z",
        "pattern": "20260918T005803Z-triage.jsonl",
        "published_in": ["README.md", "docs/claims-audit.md"],
        "runner": "lab/run_demos.py",
    },
    {
        "claim": "Numeric resolution: 0.01 grid, per-primitive endpoint rates (rows 16-17)",
        "run": "(derived from every committed run)",
        "pattern": "*.jsonl",
        "published_in": ["docs/claims-audit.md", "analysis/quantisation.py"],
        "runner": "analysis/quantisation.py",
    },
    {
        "claim": "Calibration label budget: 50 is a safety floor, 75 a plateau",
        "run": "(derived from the committed gradient run)",
        "pattern": "20260918T013027Z-tiers-*.jsonl",
        "published_in": ["analysis/CALIBRATION-TRANSFER.md"],
        "runner": "analysis/calibration_set_size.py",
    },
    {
        "claim": "Circularity premium +0.005 across four tiers",
        "run": "2026-09-20, run by the operator",
        "pattern": "*-circularity-*.jsonl",
        "published_in": ["analysis/CIRCULARITY.md"],
        "runner": "lab/exp_circularity.py",
    },
    {
        "claim": "Question isolation: 0.02 against 0.99 (row 18)",
        "run": "2026-09-20, run by the operator",
        "pattern": "*-probe-isolation.jsonl",
        "published_in": ["lab/PROBES.md", "docs/claims-audit.md"],
        "runner": "lab/probe_structure.py",
    },
    {
        "claim": "Batching: ~0.33 ms per question on ~1.4 s overhead (row 19)",
        "run": "2026-09-20, run by the operator",
        "pattern": "*-probe-batching.jsonl",
        "published_in": ["lab/PROBES.md", "docs/claims-audit.md"],
        "runner": "lab/probe_structure.py",
    },
    {
        "claim": "Choice vs Noul: 0.29 distractor mass (row 20)",
        "run": "2026-09-20, run by the operator",
        "pattern": "*-probe-formulation.jsonl",
        "published_in": ["lab/PROBES.md", "docs/claims-audit.md"],
        "runner": "lab/probe_structure.py",
    },
    {
        "claim": "BBQ and SMS figures recomputed to this repo's standard",
        "run": "not yet run; the corpora are not bundled",
        "pattern": "*-corpora-*.jsonl",
        "published_in": [],
        "runner": "lab/corpora/bbq.py",
    },
    {
        "claim": "BBQ and SMS: the SMS half",
        "run": "not yet run; the corpora are not bundled",
        "pattern": "*-corpora-sms-*.jsonl",
        "published_in": [],
        "runner": "lab/corpora/sms.py",
    },
    {
        "claim": "Endpoint origin and option-order effects",
        "run": "not yet run",
        "pattern": "*-shape-*.jsonl",
        "published_in": [],
        "runner": "lab/exp_response_shape.py",
    },
    {
        "claim": "Cross-domain transfer (issue #9)",
        "run": "not yet run",
        "pattern": "*-transfer-*.jsonl",
        "published_in": [],
        "runner": "lab/exp_transfer.py",
    },
    {
        "claim": "Jev vs local 4B head-to-head",
        "run": "not yet run",
        "pattern": "*-h2h-*.jsonl",
        "published_in": [],
        "runner": "lab/exp_headtohead.py",
    },
]


def backing(pattern: str) -> list:
    return sorted(
        os.path.basename(p) for p in glob.glob(os.path.join(RUNS, pattern))
    )


def audit() -> list:
    out = []
    for entry in CLAIMS:
        files = backing(entry["pattern"])
        published = bool(entry["published_in"])
        out.append(
            {
                **entry,
                "files": files,
                "lines": sum(
                    sum(1 for line in open(os.path.join(RUNS, f), encoding="utf-8") if line.strip())
                    for f in files
                ),
                "status": (
                    "BACKED" if files
                    else ("UNVERIFIABLE" if published else "not yet run")
                ),
            }
        )
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 if a published claim has no raw data")
    ap.add_argument("--json", help="write the audit here")
    args = ap.parse_args(argv)

    rows = audit()
    header = f"{'status':<14} {'lines':>6}  claim"
    print(header)
    print("-" * 78)
    for row in rows:
        print(f"{row['status']:<14} {row['lines']:>6}  {row['claim']}")

    missing = [r for r in rows if r["status"] == "UNVERIFIABLE"]
    if missing:
        print(f"\n{len(missing)} published claim(s) have no committed raw responses:\n")
        for row in missing:
            print(f"  {row['claim']}")
            print(f"    run       {row['run']}")
            print(f"    expected  lab/runs/{row['pattern']}")
            print(f"    cited in  {', '.join(row['published_in'])}")
        print(
            "\nThese cannot be recomputed, re-binned or checked from this repository.\n"
            "Either commit the raw responses or mark the figures as externally\n"
            "sourced where they are published. lab/runs/README.md states the rule."
        )
    else:
        print("\nEvery published figure is backed by committed raw responses.")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, indent=2, sort_keys=True)
            fh.write("\n")
    return 1 if (args.strict and missing) else 0


if __name__ == "__main__":
    raise SystemExit(main())
