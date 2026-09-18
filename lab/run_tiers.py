"""Run the difficulty-gradient experiment (issue #1) against the live API.

    python3 lab/run_tiers.py --dry-run          # no key needed: sizes the batches
    python3 lab/run_tiers.py                    # one pass over all four tiers
    python3 lab/run_tiers.py --repeat 3         # three passes, variance reported
    python3 lab/run_tiers.py --tier t4_adversarial --batch-size 25

Batches many items into each call, because that is the shape Jev is built for and
because 800 separate calls would be both slow and pointless. Every raw response
lands in lab/runs/ before scoring.

What this produces, per tier: accuracy with a Wilson interval, ECE next to the
noise floor for that tier's n and binning, MCE, Brier, coverage at 0.9 and 0.95,
and the full reliability table. The reliability table is the point — the scalar
hides whether a tier fails by a shifted decision boundary or by uniform
overconfidence, and the public studies differ on exactly that.

Read lab/tiers/README.md before interpreting anything this prints. In particular
the decisive-act regex control scores ~70-83% across tiers, so Jev beating chance
is not by itself interesting; beating that control is.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jevlab.client import JevClient, JevError  # noqa: E402
from jevlab.stats import (  # noqa: E402
    brier,
    coverage_at,
    ece_with_floor,
    format_reliability,
    mce,
    wilson,
)
from lab.tiers.baselines import CUE_RE, DECISIVE_RE, TIER_ORDER, load, score  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(BASE, "runs")

# One fixed wording for all 800 items. Difficulty must be the only thing that
# varies; a per-tier prompt would confound the two.
INSTRUCTIONS = (
    "Is message {id} a phishing or otherwise malicious email, as opposed to a "
    "legitimate one? Judge the message on its own content."
)
CRITERIA = {
    "true": "Phishing or otherwise malicious",
    "false": "A legitimate message",
}


def batches(items: list, size: int) -> list:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build_payload(batch: list) -> tuple:
    state = "Messages:\n\n" + "\n\n---\n\n".join(
        f"[{item['id']}]\n{item['text']}" for item in batch
    )
    questions = {
        item["id"]: {
            "type": "noul",
            "instructions": INSTRUCTIONS.format(id=item["id"]),
            "criteria": dict(CRITERIA),
        }
        for item in batch
    }
    return state, questions


def record(resp, started_at: str, tier: str, index: int) -> None:
    os.makedirs(RUNS_DIR, exist_ok=True)
    path = os.path.join(RUNS_DIR, f"{started_at}-tiers-{tier}.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "tier": tier,
                    "batch": index,
                    "requested_at": resp.requested_at,
                    "model": resp.model,
                    "elapsed_s": round(resp.elapsed_s, 4),
                    "attempts": resp.attempts,
                    "usage": resp.usage,
                    "response": resp.raw,
                },
                sort_keys=True,
            )
            + "\n"
        )


def analyse(pairs: list, label: str, trials: int = 500) -> dict:
    hits = sum(1 for p, gold in pairs if (p >= 0.5) == gold)
    lo, hi = wilson(hits, len(pairs))
    floor = ece_with_floor(pairs, trials=trials)
    return {
        "label": label,
        "n": len(pairs),
        "accuracy": round(hits / len(pairs), 4),
        "accuracy_ci95": [round(lo, 4), round(hi, 4)],
        "ece": round(floor["ece"], 4),
        "noise_floor_mean": round(floor["floor_mean"], 4),
        "ratio_to_floor": round(floor["ratio"], 2) if floor["ratio"] else None,
        "informative": floor["informative"],
        "mce": round(mce(pairs), 4),
        "brier": round(brier(pairs), 4),
        "coverage": {
            str(t): {
                k: (round(v, 4) if isinstance(v, float) else v)
                for k, v in coverage_at(pairs, t).items()
                if k != "ci"
            }
            for t in (0.9, 0.95)
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tier", choices=TIER_ORDER, help="run one tier")
    ap.add_argument("--batch-size", type=int, default=40, help="items per API call")
    ap.add_argument("--repeat", type=int, default=1, help="passes per tier")
    ap.add_argument("--dry-run", action="store_true", help="size the run, make no calls")
    ap.add_argument("--limit", type=int, help="use only the first N items per tier")
    ap.add_argument("--out", default=os.path.join(BASE, "tiers", "results.json"))
    args = ap.parse_args(argv)

    rows = load()
    tiers = [args.tier] if args.tier else TIER_ORDER

    if args.dry_run:
        total_calls = 0
        for tier in tiers:
            items = [r for r in rows if r["tier"] == tier][: args.limit]
            chunks = batches(items, args.batch_size)
            chars = max(len(build_payload(c)[0]) for c in chunks) if chunks else 0
            total_calls += len(chunks) * args.repeat
            print(
                f"{tier:<16} {len(items):>4} items  {len(chunks):>3} batches x "
                f"{args.repeat} pass(es)  max state ~{chars // 4} tokens"
            )
        print(f"\nTotal calls: {total_calls}")
        print(
            f"Approx cost at $0.042/MTok: "
            f"${total_calls * 8000 * 0.042 / 1_000_000:.4f}"
        )
        print("The ~32k token request budget is the constraint; keep batches well under it.")
        return 0

    started_at = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    client = JevClient()
    results = {
        "started_at": started_at,
        "repeat": args.repeat,
        "batch_size": args.batch_size,
        "baselines": {
            "cue": score(rows, CUE_RE),
            "decisive": score(rows, DECISIVE_RE),
        },
        "tiers": {},
    }

    for tier in tiers:
        items = [r for r in rows if r["tier"] == tier][: args.limit]
        gold = {r["id"]: r["is_phishing"] for r in items}
        passes = []
        for rep in range(args.repeat):
            answers: dict = {}
            failed = False
            for index, chunk in enumerate(batches(items, args.batch_size)):
                state, questions = build_payload(chunk)
                try:
                    resp = client.ask(state, questions)
                except JevError as exc:
                    print(f"{tier} batch {index}: {exc}", file=sys.stderr)
                    failed = True
                    break
                record(resp, started_at, tier, index)
                answers.update({q: resp.noul(q) for q in questions if q in resp.answers})
                print(
                    f"  {tier} pass {rep + 1} batch {index + 1}: "
                    f"{resp.elapsed_s:.2f}s, {len(questions)} questions",
                    file=sys.stderr,
                )
            if failed:
                break
            passes.append(answers)

        if not passes:
            continue

        pairs = [(passes[0][i], gold[i]) for i in sorted(passes[0]) if i in gold]
        block = analyse(pairs, tier)
        if len(passes) > 1:
            flips = sum(
                1
                for qid in passes[0]
                if len({p[qid] >= 0.5 for p in passes if qid in p}) > 1
            )
            block["variance"] = {
                "passes": len(passes),
                "label_flip_rate": round(flips / len(passes[0]), 4),
            }
        results["tiers"][tier] = block
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
            fh.write("\n")
        print(f"\n{tier}: {format_reliability(pairs)}")

    _report(results)
    return 0


def _report(results: dict) -> None:
    print("\n=== difficulty gradient ===")
    header = (
        f"{'tier':<16} {'n':>5} {'accuracy':>18} {'ECE':>7} "
        f"{'floor':>7} {'ratio':>6} {'cue base':>9} {'regex base':>11}"
    )
    print(header)
    print("-" * len(header))
    for tier in TIER_ORDER:
        block = results["tiers"].get(tier)
        if not block:
            continue
        lo, hi = block["accuracy_ci95"]
        cue = results["baselines"]["cue"][tier]["rate"]
        dec = results["baselines"]["decisive"][tier]["rate"]
        print(
            f"{tier:<16} {block['n']:>5} "
            f"{block['accuracy']:>7.1%} [{lo:.0%},{hi:.0%}] "
            f"{block['ece']:>7.4f} {block['noise_floor_mean']:>7.4f} "
            f"{str(block['ratio_to_floor']):>6} {cue:>9.1%} {dec:>11.1%}"
        )
    print(
        "\nThe question is the SHAPE of ECE across tiers, not any single value.\n"
        "Flat means calibration is a real property. Rising means it tracks\n"
        "difficulty, and the reliability tables say whether a tier fails by a\n"
        "shifted boundary or by uniform overconfidence."
    )


if __name__ == "__main__":
    raise SystemExit(main())
