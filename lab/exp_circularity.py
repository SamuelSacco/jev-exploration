"""Measure what judge circularity WOULD have cost, had Jev labelled its own task.

    python3 lab/exp_circularity.py --dry-run          # no credential, sizes the run
    JEV_TRANSPORT=my_ops.jev:send python3 lab/exp_circularity.py --repeat 3

Contains no credential handling. It calls `jevlab.transport.resolve_sender()`,
which by default reads TYPESAFE_API_KEY from the environment but can be pointed
at an operator's own transport with JEV_TRANSPORT=package.module:callable. The
operator's transport does whatever it does about authentication; nothing here
sees it.

## Why this experiment rather than the one that was asked for

The request was to re-derive B1 and B2 under Jev-only, LLM-only and merged
labels, as zhuyansen/jev-search-rerank-eval (T69) did for reranking.

That design does not transfer directly. In T69 there is a latent quantity, "is
this passage relevant", that different judges estimate differently, so swapping
judges re-estimates the same thing and the gap between estimates is the bias.
In the difficulty gradient there is no latent quantity: `lab/tiers/generate.py`
picks "phishing" or "legitimate" from a counter and then builds a message to
match. Relabeling would not produce a second estimate of the same truth, it
would produce a different dataset, and B1/B2 measured on it would not be
comparable to B1/B2 as published.

`analysis/circularity.py` confirms the provenance mechanically: the label is
assigned before the text exists and the generator imports nothing that can reach
an API.

What is still worth measuring is the counterfactual. If this benchmark HAD been
built the way the circular ones were, with the model supplying the labels, how
much would that have inflated its own score? That is a number, it is cheap, and
it calibrates how much to discount any Jev benchmark that did label its own
task, including TypeSafe's dashboard.

## Design

Two regimes over the same 800 committed items.

  truth   labels from the generator, which is what B1/B2 use
  self    labels from Jev, elicited with a deliberately different wording from
          the scoring question so the two are not trivially identical

Then score Jev's scoring-question answers against each label set. The
circularity premium is (accuracy under self-labels) minus (accuracy under truth
labels), per tier and overall.

Preregistered expectation, written before the run:

  The premium is positive in every tier, because a model agrees with itself more
  than it agrees with the world. It is largest on t4_adversarial, where the
  model is least accurate against truth and so has the most room to agree with
  its own mistakes. A premium above +0.05 overall would put this benchmark in
  the same range as T69's measured swing of 0.081 and would mean any
  Jev-labelled benchmark should be discounted by at least that much.

The labelling and scoring questions are issued in SEPARATE requests. Questions
inside one request are isolated from each other's instruction text, but sharing
a request would still put both wordings in the same state, which is exactly the
confound this is trying to measure.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jevlab.stats import coverage_at, ece_with_floor, wilson  # noqa: E402
from jevlab.transport import describe_sender, resolve_sender, timed  # noqa: E402
from lab.tiers.baselines import TIER_ORDER, load  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(BASE, "runs")

# Identical to lab/run_tiers.py, so "scoring" here is the same measurement B1/B2 used.
SCORING_INSTRUCTIONS = (
    "Is message {id} a phishing or otherwise malicious email, as opposed to a "
    "legitimate one? Judge the message on its own content."
)
SCORING_CRITERIA = {
    "true": "Phishing or otherwise malicious",
    "false": "A legitimate message",
}

# Deliberately different wording. If the labelling question were identical to
# the scoring question the premium would be 1.0 by construction and meaningless.
LABELLING_INSTRUCTIONS = (
    "You are building a training corpus. Should message {id} be filed under "
    "'attack' or 'ordinary business correspondence'? Decide from the message."
)
LABELLING_CRITERIA = {
    "true": "File under attack",
    "false": "File under ordinary business correspondence",
}

PREREGISTERED = (
    "The circularity premium (accuracy under self-labels minus accuracy under "
    "generator labels) is positive in every tier and largest on t4_adversarial. "
    "A premium above +0.05 overall is comparable to T69's measured swing of "
    "0.081 and would imply any Jev-labelled benchmark needs at least that "
    "discount."
)


def batches(items: list, size: int) -> list:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build(chunk: list, instructions: str, criteria: dict) -> tuple:
    state = "Messages:\n\n" + "\n\n---\n\n".join(
        f"[{item['id']}]\n{item['text']}" for item in chunk
    )
    questions = {
        item["id"]: {
            "type": "noul",
            "instructions": instructions.format(id=item["id"]),
            "criteria": dict(criteria),
        }
        for item in chunk
    }
    return state, questions


def record(started_at: str, tier: str, regime: str, index: int, raw: dict, elapsed: float) -> None:
    os.makedirs(RUNS_DIR, exist_ok=True)
    path = os.path.join(RUNS_DIR, f"{started_at}-circularity-{tier}.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "tier": tier,
                    "regime": regime,
                    "batch": index,
                    "elapsed_s": round(elapsed, 4),
                    "model": raw.get("model"),
                    "usage": raw.get("usage"),
                    "response": {k: v for k, v in raw.items() if not k.startswith("_")},
                },
                sort_keys=True,
            )
            + "\n"
        )


def collect(sender, chunkset, instructions, criteria, started_at, tier, regime) -> dict:
    answers: dict = {}
    for index, chunk in enumerate(chunkset):
        state, questions = build(chunk, instructions, criteria)
        raw, elapsed = timed(sender, state, questions)
        record(started_at, tier, regime, index, raw, elapsed)
        for qid, ans in raw.get("answers", {}).items():
            if qid in questions:
                answers[qid] = float(ans["noul"])
        print(
            f"  {tier}/{regime} batch {index + 1}/{len(chunkset)}: "
            f"{elapsed:.2f}s, {len(questions)} questions",
            file=sys.stderr,
        )
    return answers


def score(scoring: dict, truth: dict, self_labels: dict, threshold: float = 0.5) -> dict:
    ids = [i for i in sorted(scoring) if i in truth and i in self_labels]
    truth_pairs = [(scoring[i], truth[i]) for i in ids]
    self_pairs = [(scoring[i], self_labels[i] >= threshold) for i in ids]

    def accuracy(pairs):
        hits = sum(1 for p, gold in pairs if (p >= threshold) == gold)
        lo, hi = wilson(hits, len(pairs))
        return {
            "hits": hits,
            "n": len(pairs),
            "accuracy": round(hits / len(pairs), 4),
            "ci95": [round(lo, 4), round(hi, 4)],
        }

    under_truth = accuracy(truth_pairs)
    under_self = accuracy(self_pairs)
    agreement = sum(1 for i in ids if (self_labels[i] >= threshold) == truth[i]) / len(ids)
    return {
        "n": len(ids),
        "under_generator_labels": under_truth,
        "under_self_labels": under_self,
        "circularity_premium": round(
            under_self["accuracy"] - under_truth["accuracy"], 4
        ),
        "self_label_agreement_with_truth": round(agreement, 4),
        "ece_under_generator_labels": round(ece_with_floor(truth_pairs, trials=300)["ece"], 4),
        "ece_under_self_labels": round(ece_with_floor(self_pairs, trials=300)["ece"], 4),
        "coverage_at_0.9_under_generator": {
            k: (round(v, 4) if isinstance(v, float) else v)
            for k, v in coverage_at(truth_pairs, 0.9).items()
            if k != "ci"
        },
        "coverage_at_0.9_under_self": {
            k: (round(v, 4) if isinstance(v, float) else v)
            for k, v in coverage_at(self_pairs, 0.9).items()
            if k != "ci"
        },
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tier", choices=TIER_ORDER, help="run one tier")
    ap.add_argument("--batch-size", type=int, default=40)
    ap.add_argument("--repeat", type=int, default=1, help="passes per regime")
    ap.add_argument("--limit", type=int, help="first N items per tier")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=os.path.join(BASE, "tiers", "circularity_results.json"))
    args = ap.parse_args(argv)

    rows = load()
    tiers = [args.tier] if args.tier else TIER_ORDER

    if args.dry_run:
        total = 0
        for tier in tiers:
            items = [r for r in rows if r["tier"] == tier][: args.limit]
            chunks = len(batches(items, args.batch_size))
            calls = chunks * 2 * args.repeat  # two regimes
            total += calls
            biggest = build(batches(items, args.batch_size)[0], SCORING_INSTRUCTIONS, SCORING_CRITERIA)
            print(
                f"{tier:<16} {len(items):>4} items  {chunks:>2} batches x 2 regimes x "
                f"{args.repeat} pass(es) = {calls:>3} calls  "
                f"(state ~{len(biggest[0]) // 4} tokens)"
            )
        print(f"\nTotal calls: {total}")
        print(f"Approx cost at $0.042/MTok: ${total * 4500 * 0.042 / 1_000_000:.4f}")
        print(f"\ntransport: {describe_sender()}")
        print(f"\npreregistered: {PREREGISTERED}")
        return 0

    sender = resolve_sender()
    started_at = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    results = {
        "started_at": started_at,
        "transport": describe_sender(),
        "repeat": args.repeat,
        "preregistered": PREREGISTERED,
        "tiers": {},
    }

    for tier in tiers:
        items = [r for r in rows if r["tier"] == tier][: args.limit]
        truth = {r["id"]: r["is_phishing"] for r in items}
        chunkset = batches(items, args.batch_size)

        scoring_passes, label_passes = [], []
        for rep in range(args.repeat):
            scoring_passes.append(
                collect(sender, chunkset, SCORING_INSTRUCTIONS, SCORING_CRITERIA,
                        started_at, tier, f"scoring-p{rep}")
            )
            label_passes.append(
                collect(sender, chunkset, LABELLING_INSTRUCTIONS, LABELLING_CRITERIA,
                        started_at, tier, f"labelling-p{rep}")
            )

        scoring = {
            k: statistics.mean(p[k] for p in scoring_passes if k in p)
            for k in scoring_passes[0]
        }
        self_labels = {
            k: statistics.mean(p[k] for p in label_passes if k in p)
            for k in label_passes[0]
        }
        results["tiers"][tier] = score(scoring, truth, self_labels)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
            fh.write("\n")

    print("\n=== circularity premium ===")
    header = (
        f"{'tier':<16} {'n':>5} {'acc vs truth':>13} {'acc vs self':>12} "
        f"{'premium':>8} {'agreement':>10}"
    )
    print(header)
    print("-" * len(header))
    premiums = []
    for tier in tiers:
        block = results["tiers"].get(tier)
        if not block:
            continue
        premiums.append(block["circularity_premium"])
        print(
            f"{tier:<16} {block['n']:>5} "
            f"{block['under_generator_labels']['accuracy']:>13.3f} "
            f"{block['under_self_labels']['accuracy']:>12.3f} "
            f"{block['circularity_premium']:>+8.3f} "
            f"{block['self_label_agreement_with_truth']:>10.3f}"
        )
    if premiums:
        overall = sum(premiums) / len(premiums)
        print(f"\nmean premium across tiers: {overall:+.4f}")
        print(f"T69's measured swing, for scale: 0.081")
        print(f"\npreregistered: {PREREGISTERED}")
    print(f"\nRaw responses in {RUNS_DIR}/, summary in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
