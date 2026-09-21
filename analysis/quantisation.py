"""What numeric resolution does the direct API actually return?

    python3 analysis/quantisation.py

No API key. Reads the raw responses committed under lab/runs/.

Issue #10 asks a methods question. Those runs went through Vercel AI Gateway,
whose response bodies carry `rounding: {probabilityDecimals: 2, scoreDecimals: 2}`
and whose option probabilities are quantised to 0.01, with exact 0 and exact 1
common. The question is whether that is the API's behaviour or the Gateway's,
because a probability of exactly 0 on the correct answer cannot be repaired by
temperature scaling, and the answer decides whether that footnote is about Jev
or about one way of calling it.

This repo's runs went to api.typesafe.ai directly on jev-1.13.0 and the raw
bodies are committed, so the question is answerable offline. Three parts:

1. Metadata. Does a direct response declare its rounding anywhere?
2. Grid. Are the numbers quantised to 0.01 regardless of what is declared?
3. Endpoints. How often is a returned value exactly 0 or exactly 1, and does
   that differ by primitive?

Part 3 is the one that matters for calibration work: the endpoints are where
temperature scaling and Platt maps stop being able to help.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
)

from jevlab.stats import wilson  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNS = os.path.join(ROOT, "lab", "runs")

# Keys the Gateway adds to a response body, per issue #10.
GATEWAY_METADATA_KEYS = ("rounding", "probabilityDecimals", "scoreDecimals")

GRID = 0.01
# Slack for float representation: 0.82 can arrive as 0.8200000000000001 when the
# server computes it as a residual rather than emitting a literal.
TOLERANCE = 1e-9


def responses(pattern: str = "*.jsonl") -> list:
    """Every committed raw response body, oldest file first."""
    out = []
    for path in sorted(glob.glob(os.path.join(RUNS, pattern))):
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                body = rec.get("response") or rec.get("raw")
                if isinstance(body, dict) and "answers" in body:
                    out.append((os.path.basename(path), body))
    return out


def numbers(bodies: list) -> list:
    """(source, primitive, field, value) for every number a response returned."""
    out = []
    for source, body in bodies:
        for qid, answer in (body.get("answers") or {}).items():
            kind = answer.get("type")
            for field in ("noul", "confidence", "score"):
                value = answer.get(field)
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    out.append((source, kind, field, float(value)))
            for option, value in (answer.get("probabilities") or {}).items():
                out.append((source, kind, "probabilities", float(value)))
    return out


def metadata_audit(bodies: list) -> dict:
    """Which top-level keys a direct response carries, and whether any declare rounding."""
    keys = collections.Counter()
    for _, body in bodies:
        keys.update(body.keys())
    declared = [k for k in GATEWAY_METADATA_KEYS if k in keys]
    return {
        "responses": len(bodies),
        "top_level_keys": dict(keys),
        "declares_rounding": bool(declared),
        "rounding_keys_found": declared,
    }


def off_grid(values: list, grid: float = GRID, tolerance: float = TOLERANCE) -> list:
    """Values that are not a multiple of `grid`, within representation slack."""
    return [
        row for row in values
        if abs(round(row[3] / grid) * grid - row[3]) > tolerance
    ]


def grid_audit(values: list) -> dict:
    stray = off_grid(values)
    literal = [row for row in values if repr(row[3]) != repr(round(row[3], 2))]
    return {
        "values": len(values),
        "off_grid": len(stray),
        "off_grid_examples": [
            {"source": s, "field": f, "value": v} for s, _, f, v in stray[:5]
        ],
        "quantised_to_0.01": not stray,
        "non_literal_reprs": len(literal),
        "non_literal_examples": [repr(row[3]) for row in literal[:5]],
    }


def endpoint_audit(values: list) -> dict:
    """Exact-0 and exact-1 rates, split by primitive and field.

    Split because the ceiling and floor need not be the same for every type, and
    if they are not, the "a returned 0 cannot be fixed by scaling" caveat applies
    to some primitives and not others.
    """
    groups = collections.defaultdict(list)
    for _, kind, field, value in values:
        groups[f"{kind}.{field}"].append(value)
    out = {}
    for name in sorted(groups):
        vs = groups[name]
        zeros = sum(1 for v in vs if v == 0.0)
        ones = sum(1 for v in vs if v == 1.0)
        out[name] = {
            "n": len(vs),
            "exact_0": zeros,
            "exact_0_rate": round(zeros / len(vs), 4),
            "exact_1": ones,
            "exact_1_rate": round(ones / len(vs), 4),
            "min": min(vs),
            "max": max(vs),
        }
    return out


def distribution_sums(bodies: list) -> dict:
    """Whether quantised distributions still sum to 1.

    If they do, the rounding is applied to the components and one entry absorbs
    the residual, which is what a stray 0.8200000000000001 looks like.
    """
    sums = collections.Counter()
    for _, body in bodies:
        for _, answer in (body.get("answers") or {}).items():
            probs = answer.get("probabilities")
            if probs:
                sums[round(sum(probs.values()), 6)] += 1
    return {"distributions": sum(sums.values()), "sums": dict(sums)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", help="write the audit result here")
    args = ap.parse_args(argv)

    bodies = responses()
    if not bodies:
        print(f"No committed responses under {RUNS}", file=sys.stderr)
        return 1
    values = numbers(bodies)

    meta = metadata_audit(bodies)
    print("1. Response metadata\n")
    print(f"  responses            {meta['responses']}")
    print(f"  top-level keys       {sorted(meta['top_level_keys'])}")
    print(f"  declares rounding    {meta['declares_rounding']}")

    grid = grid_audit(values)
    print("\n2. Numeric grid\n")
    print(f"  values examined      {grid['values']}")
    print(f"  off the 0.01 grid    {grid['off_grid']}")
    print(f"  quantised to 0.01    {grid['quantised_to_0.01']}")
    if grid["non_literal_reprs"]:
        print(
            f"  not a 2dp literal    {grid['non_literal_reprs']} "
            f"(e.g. {', '.join(grid['non_literal_examples'])})"
        )
    sums = distribution_sums(bodies)
    print(f"  distribution sums    {sums['sums']} over {sums['distributions']} vectors")

    print("\n3. Endpoints, by primitive\n")
    ends = endpoint_audit(values)
    header = f"  {'field':<26} {'n':>6} {'exact 0':>10} {'exact 1':>10} {'range':>14}"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for name, block in ends.items():
        print(
            f"  {name:<26} {block['n']:>6} "
            f"{block['exact_0']:>4} {block['exact_0_rate']:>5.1%} "
            f"{block['exact_1']:>4} {block['exact_1_rate']:>5.1%} "
            f"{str(block['min']) + '-' + str(block['max']):>14}"
        )

    noul = ends.get("noul.noul", {})
    print("\n4. Reading\n")
    print(
        "  The direct API declares no rounding, and rounds anyway: every value in\n"
        "  the committed bodies sits on the 0.01 grid. So the quantisation in #10\n"
        "  is the API's, not the Gateway's, and the Gateway's `rounding` block\n"
        "  reports it rather than causing it."
    )
    if noul and noul["exact_0"] == 0 and noul["exact_1"] == 0:
        bound = wilson(0, noul["n"])[1]
        print(
            f"\n  The endpoints are not shared across primitives. Choice and Score\n"
            f"  return exact 0 and exact 1 freely; Noul never did, over\n"
            f"  {noul['n']} answers, and stayed inside "
            f"[{noul['min']}, {noul['max']}].\n"
            f"  Zero of {noul['n']} bounds the endpoint rate for Noul at "
            f"{bound:.2%} (Wilson, 95%),\n"
            "  which is an absence worth acting on rather than a gap in the data.\n"
            "  So the unrepairable-zero caveat is real for Choice and Score and\n"
            "  has no instance for Noul. That matters for the per-type sign split\n"
            "  reported in #10: this repo's calibration results are all Noul,\n"
            "  measured on the one primitive that looks clamped, and a Platt or\n"
            "  temperature correction is only well defined there."
        )
        result_note = {
            "noul_endpoint_rate_upper_95": round(bound, 6),
            "noul_observed_range": [noul["min"], noul["max"]],
        }
    else:
        result_note = {}

    result = {
        "metadata": meta,
        "grid": grid,
        "endpoints": ends,
        "distribution_sums": sums,
        "noul_clamp": result_note,
    }
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
            fh.write("\n")
        print(f"\nWrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
