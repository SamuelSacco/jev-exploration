"""Re-derive every published Jev calibration figure against its own noise floor.

    python3 analysis/external/run.py --base /home/user
    python3 analysis/external/run.py --base ~/src --json analysis/external/summary.json

Each study is scored with the binning *it* used. Where the study published an
ECE, the reproduction is checked against it before anything else is reported:
a figure we cannot reproduce is not a figure we can reinterpret.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from analysis.external.loaders import load_all  # noqa: E402
from jevlab.stats import (  # noqa: E402
    accuracy,
    brier,
    coverage_at,
    ece,
    ece_noise_floor,
    mce,
    reliability,
    wilson,
)


def evaluate(study, trials: int = 600) -> dict:
    pairs = study.pairs
    probs = [p for p, _ in pairs]
    observed = ece(pairs, study.bins, study.bin_range, study.edge)
    floor = ece_noise_floor(
        probs,
        bins=study.bins,
        trials=trials,
        bin_range=study.bin_range,
        edge=study.edge,
    )
    occupied = len(reliability(pairs, study.bins, study.bin_range, study.edge))
    # For a "confidence" study the outcome already IS correctness, so accuracy is
    # its mean. Thresholding it at 0.5, as you would a P(event), silently counts
    # every low-confidence correct answer as a miss.
    if study.quantity == "confidence":
        hits = sum(1 for _, hit in pairs if hit)
        acc = hits / len(pairs)
    else:
        acc = accuracy(pairs)
        hits = round(acc * len(pairs))
    acc_lo, acc_hi = wilson(hits, len(pairs))

    reproduced = None
    if study.reported_ece is not None:
        reproduced = abs(observed - study.reported_ece) < 0.005

    return {
        "repo": study.repo,
        "task": study.task,
        "variant": study.variant,
        "quantity": study.quantity,
        "provenance": study.provenance,
        "n": len(pairs),
        "bins": study.bins,
        "bin_range": list(study.bin_range),
        "occupied_bins": occupied,
        "accuracy": round(acc, 4),
        "accuracy_ci": [round(acc_lo, 4), round(acc_hi, 4)],
        "reported_ece": study.reported_ece,
        "ece": round(observed, 4),
        "reproduced": reproduced,
        "floor_mean": round(floor["mean"], 4),
        "floor_p95": round(floor["p95"], 4),
        "ratio": round(observed / floor["mean"], 2) if floor["mean"] else None,
        "informative": bool(observed > floor["p95"]),
        "edge": study.edge,
        "mce": round(mce(pairs, study.bins, study.bin_range, study.edge), 4),
        "brier": round(brier(pairs), 4),
        "coverage_at_0.9": {
            k: (round(v, 4) if isinstance(v, float) else v)
            for k, v in coverage_at(pairs, 0.9).items()
            if k != "ci"
        },
        "notes": study.notes,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--base",
        default=os.path.expanduser("~"),
        help="directory holding the cloned source repos (default: ~)",
    )
    ap.add_argument("--json", help="also write the full results here")
    ap.add_argument("--trials", type=int, default=600, help="noise-floor simulations")
    args = ap.parse_args(argv)

    studies = load_all(args.base)
    if not studies:
        print(
            f"No source repos found under {args.base}. Clone them first; see "
            "analysis/external/loaders.py for the commands.",
            file=sys.stderr,
        )
        return 1

    results = [evaluate(s, trials=args.trials) for s in studies]

    unreproduced = [
        r for r in results if r["reproduced"] is False
    ]
    if unreproduced:
        print("REPRODUCTION FAILED — not reinterpreting these:", file=sys.stderr)
        for r in unreproduced:
            print(
                f"  {r['repo']}/{r['variant']}: got {r['ece']}, "
                f"published {r['reported_ece']}",
                file=sys.stderr,
            )

    header = (
        f"{'study':<38} {'n':>6} {'bins':>12} {'acc':>7} "
        f"{'ECE':>7} {'floor':>7} {'ratio':>6}  verdict"
    )
    print(header)
    print("-" * len(header))
    for r in sorted(results, key=lambda r: -r["n"]):
        label = f"{r['repo']}/{r['variant']}"[:37]
        span = f"{r['bins']}@{r['bin_range'][0]:g}-{r['bin_range'][1]:g}"
        verdict = "real" if r["informative"] else "AT THE NOISE FLOOR"
        print(
            f"{label:<38} {r['n']:>6} {span:>12} {r['accuracy']:>7.3f} "
            f"{r['ece']:>7.4f} {r['floor_mean']:>7.4f} {r['ratio']:>6}  {verdict}"
        )

    print("\nReproduction of published figures:")
    any_reported = False
    for r in results:
        if r["reported_ece"] is None:
            continue
        any_reported = True
        mark = "ok" if r["reproduced"] else "MISMATCH"
        print(
            f"  {r['repo']}/{r['variant']:<22} published {r['reported_ece']:.4f}  "
            f"recomputed {r['ece']:.4f}  [{mark}]"
        )
    if not any_reported:
        print("  (none of the loaded studies published an ECE)")

    print(
        "\nratio = observed ECE / the ECE a perfectly calibrated model scores at\n"
        "this n and binning. It measures DETECTABILITY, not severity: a large n\n"
        "drives the floor down, so a mild miscalibration can show a high ratio.\n"
        "Read the ratio to decide whether a study can speak at all, and the raw\n"
        "ECE, Brier and reliability table for how bad the miscalibration is."
    )

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
            fh.write("\n")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
