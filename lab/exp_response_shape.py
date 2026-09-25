"""Two probes of the response itself: where the endpoints come from, and whether
option order moves the answer.

    python3 lab/exp_response_shape.py --dry-run
    JEV_TRANSPORT=my_ops.jev:send python3 lab/exp_response_shape.py --repeat 3

No credential handling. Resolves its sender through `jevlab.transport`.

## Probe 1: endpoints

`analysis/quantisation.py` established, from 71 committed responses, that the
direct API rounds every number to a 0.01 grid while declaring no rounding, that
Choice and Score reach exactly 0 and exactly 1 freely (70.4% and 20.4% of Choice
option probabilities), and that Noul did neither once in 11,148 answers, bounding
its endpoint rate at 0.0344% (Wilson, 95%).

That leaves the question those numbers raise. A probability of exactly 0 on the
*correct* option cannot be repaired by temperature, Platt or isotonic scaling,
because all three act on the logit and the logit of 0 is undefined. So: is the
endpoint a rounding artefact that only lands on options the model has already
dismissed, or can it land on a correct one?

The probe grades the evidence. Items run from decisive to genuinely ambiguous,
and each is asked as a Choice over four options and as four independent Nouls.
If endpoints are rounding, they should retreat as the evidence weakens. If they
are a clamp applied after the distribution is formed, they should persist.

## Probe 2: position

A third party reports 24.7% order reversal: present the same Choice options in a
different order and the winner changes about a quarter of the time. If true it
is disqualifying for the primitive; the ledger currently records it as
unverified.

The claim as stated is not testable, because it has no noise baseline. Jev is
stochastic: the same request twice does not always return the same winner, and
some fraction of "reversals" under a reordering would have happened anyway.
Three conditions, therefore:

  forward    options in their natural order
  reversed   the same options, order reversed
  repeat     forward again, a second time

`repeat` against `forward` is the run-to-run flip rate with nothing changed.
`reversed` against `forward` is that plus any position effect. The position
effect is the difference, with a bootstrap interval on it, and a reported figure
that does not exceed the repeat condition is not a position effect at all.

## Preregistered, written before any call

E1. Exact 0 and 1 appear on Choice and not on Noul, on the same items. Falsified
by any Noul at 0.00 or 1.00.

E2. Endpoints retreat as evidence weakens: the share of Choice option
probabilities at exactly 0 is lower on ambiguous items than on decisive ones.
Falsified if the ambiguous share is equal or higher.

E3. No exact 0 lands on a correct option. Falsified by one instance, which would
promote the caveat in the ledger from theoretical to observed.

P1. The reversal rate under reordering exceeds the repeat rate, with a bootstrap
interval on the difference excluding zero. Falsified if it covers zero, which
would mean the 24.7% figure measures stochasticity.

P2. If a position effect exists it is smaller than 24.7%. Falsified if the
interval's lower bound is above 0.247.

Stated plainly: P1 is expected to come back REFUTED, because a reported flip
rate with no same-order control is usually measuring noise. If it does not,
that is the more interesting outcome and the primitive has a real problem.

## Cost

30 calls at default settings, about $0.004.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jevlab.transport import ask, describe_sender, resolve_sender  # noqa: E402

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(BASE, "runs")
ITEMS_PATH = os.path.join(BASE, "response_shape_items.json")

REPORTED_REVERSAL_RATE = 0.247

PREREGISTERED = {
    "E1_endpoints_are_per_primitive": (
        "Exact 0 and 1 appear on Choice and not on Noul, on the same items. "
        "Falsified by any Noul at 0.00 or 1.00."
    ),
    "E2_endpoints_retreat_with_evidence": (
        "The share of Choice option probabilities at exactly 0 is lower on "
        "ambiguous items than on decisive ones. Falsified if equal or higher."
    ),
    "E3_no_endpoint_on_a_correct_option": (
        "No exact 0 lands on a correct option. Falsified by one instance."
    ),
    "P1_reordering_flips_more_than_repetition": (
        "The reversal rate under reordering exceeds the same-order repeat rate, "
        "bootstrap interval on the difference excluding zero. Falsified if it "
        "covers zero, which would mean the reported 24.7% is stochasticity."
    ),
    "P2_any_position_effect_is_below_the_reported_rate": (
        f"If a position effect exists it is below {REPORTED_REVERSAL_RATE:.1%}. "
        "Falsified if the interval's lower bound is above it."
    ),
}


def stratified(items: list, limit: int | None) -> list:
    """Take `limit` items, spread evenly across the evidence bands.

    A plain prefix truncates by band, because the generator emits decisive
    first: `--limit 30` over 60 items left the ambiguous band empty, and E2
    compares bands, so the probe silently stopped measuring what it exists to
    measure.
    """
    if not limit or limit >= len(items):
        return items
    bands: dict = {}
    for item in items:
        bands.setdefault(item["strength"], []).append(item)
    per_band = max(1, limit // max(len(bands), 1))
    out = []
    for band in sorted(bands):
        out.extend(bands[band][:per_band])
    return out[:limit]


def load_items(path: str | None = None) -> list:
    with open(path or ITEMS_PATH, encoding="utf-8") as fh:
        return json.load(fh)["items"]


def choice_question(item: dict, reverse: bool = False) -> dict:
    """Choice criteria is a dict of {label: description}; a list is rejected 422."""
    labels = list(item["options"])
    if reverse:
        labels = labels[::-1]
    return {
        "type": "choice",
        "instructions": item["question"],
        "criteria": {label: item["options"][label] for label in labels},
    }


def noul_questions(item: dict) -> dict:
    """The same decision as one independent Noul per option."""
    return {
        f"{item['id']}__{label}": {
            "type": "noul",
            "instructions": f"{item['question']} Specifically: is the answer '{label}'?",
            "criteria": {"true": description, "false": f"Not {label}"},
        }
        for label, description in item["options"].items()
    }


def build(chunk: list, mode: str) -> tuple:
    state = "Cases:\n\n" + "\n\n---\n\n".join(
        f"[{item['id']}]\n{item['text']}" for item in chunk
    )
    questions: dict = {}
    for item in chunk:
        if mode == "noul":
            questions.update(noul_questions(item))
        else:
            questions[item["id"]] = choice_question(item, reverse=(mode == "reversed"))
    return state, questions


def record(started_at: str, probe: str, mode: str, rep: int, index: int, reply) -> None:
    os.makedirs(RUNS_DIR, exist_ok=True)
    path = os.path.join(RUNS_DIR, f"{started_at}-shape-{probe}-{mode}.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "probe": probe,
                    "mode": mode,
                    "rep": rep,
                    "batch": index,
                    "requested_at": reply.requested_at,
                    "model": reply.model,
                    "elapsed_s": round(reply.elapsed_s, 4),
                    "usage": reply.usage,
                    "response": reply.raw,
                },
                sort_keys=True,
            )
            + "\n"
        )


def collect(sender, items, mode, started_at, probe, rep, batch_size) -> dict:
    out: dict = {}
    chunks = [items[i : i + batch_size] for i in range(0, len(items), batch_size)]
    for index, chunk in enumerate(chunks):
        state, questions = build(chunk, mode)
        reply = ask(sender, state, questions)
        record(started_at, probe, mode, rep, index, reply)
        for qid in questions:
            if qid not in reply.answers:
                continue
            answer = reply.answers[qid]
            if answer.get("type") == "choice":
                out[qid] = {
                    "choice": reply.choice(qid),
                    "probabilities": dict(reply.probabilities(qid)),
                    "confidence": reply.confidence(qid),
                }
            else:
                out[qid] = {"noul": reply.noul(qid)}
        print(
            f"  {probe}/{mode} pass {rep + 1} batch {index + 1}/{len(chunks)}: "
            f"{reply.elapsed_s:.2f}s, {len(questions)} questions",
            file=sys.stderr,
        )
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--probe", choices=["endpoints", "position", "all"], default="all")
    ap.add_argument("--batch-size", type=int, default=30)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=os.path.join(BASE, "response_shape_answers.json"))
    args = ap.parse_args(argv)

    items = stratified(load_items(), args.limit)
    chunks = -(-len(items) // args.batch_size)
    wanted = ["endpoints", "position"] if args.probe == "all" else [args.probe]
    # endpoints: choice + noul. position: forward, reversed, repeat.
    modes = {"endpoints": ["choice", "noul"], "position": ["forward", "reversed", "repeat"]}

    if args.dry_run:
        total = 0
        for probe in wanted:
            calls = chunks * len(modes[probe]) * args.repeat
            total += calls
            print(
                f"{probe:<11} {len(items):>3} items  {chunks} batches x "
                f"{len(modes[probe])} modes x {args.repeat} passes = {calls:>3} calls"
            )
        by_strength = {}
        for item in items:
            by_strength[item["strength"]] = by_strength.get(item["strength"], 0) + 1
        print(f"\nitems by evidence strength: {by_strength}")
        print(f"Total calls: {total}")
        print(f"Approx cost at $0.042/MTok: ${total * 2600 * 0.042 / 1_000_000:.4f}")
        print(f"\ntransport: {describe_sender()}")
        print("\npreregistered:")
        for key, text in PREREGISTERED.items():
            print(f"  {key}: {text}")
        return 0

    sender = resolve_sender()
    started_at = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    results = {
        "started_at": started_at,
        "transport": describe_sender(),
        "repeat": args.repeat,
        "preregistered": PREREGISTERED,
        "reported_reversal_rate": REPORTED_REVERSAL_RATE,
        "items": {i["id"]: {"gold": i["gold"], "strength": i["strength"]} for i in items},
        "probes": {},
    }

    for probe in wanted:
        block = {}
        for mode in modes[probe]:
            block[mode] = [
                collect(sender, items, mode, started_at, probe, rep, args.batch_size)
                for rep in range(args.repeat)
            ]
        results["probes"][probe] = block
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"{probe}: done", file=sys.stderr)

    print(f"\nRaw responses in {RUNS_DIR}/, answers in {args.out}")
    print("Now run: python3 analysis/response_shape.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
