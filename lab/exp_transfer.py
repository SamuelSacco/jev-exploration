"""Issue #9: does the fitted calibration correction survive a change of domain?

    python3 lab/exp_transfer.py --dry-run             # sizes the run, no credential
    JEV_TRANSPORT=my_ops.jev:send python3 lab/exp_transfer.py --repeat 3

Contains no credential handling. It calls `jevlab.transport.resolve_sender()`,
which defaults to this repo's client and can be pointed at an operator's own
transport with `JEV_TRANSPORT=package.module:callable`. That transport takes
`(state, questions, model)` and returns the raw response dict; whatever it does
about authentication is invisible here, so this file runs unmodified on either
side.

## The claim under test

`analysis/CALIBRATION-TRANSFER.md` reports, on the 800-item e-mail gradient:

  - Platt's slope sits in 2.11-2.61 across all four tiers and all three passes.
    That is the squeeze, read as a property of the model and the reusable part.
  - The intercept spans -0.48 to +1.75, tracking the slice's base rate, and is
    read as belonging to the deployment rather than the model.
  - So: transfer the slope, spend ~50 labels refitting the intercept. That cut
    mean ECE 61.7% on held-out items, with no draw worse than doing nothing,
    where transferring the whole map cut it 54% and hurt one.

Its stated limitation is that everything behind it is e-mail legitimacy on
`jev-1.13.0`. If the slope is really a property of the model, it should hold
when the subject matter changes completely. If it is a property of *this task*,
the recipe has to be restated as e-mail-only, and the ledger row with it.

## Design

`lab/domains/dataset.jsonl`, 480 items in four slices, labels committed before
any call. Three domains with nothing in common but their construction:

  code_security        does this change introduce a security flaw?
  lab_safety           does this step violate the written safety protocol?
  contract_liability   does this clause expose the signer to uncapped liability?

Difficulty is held fixed: one cue per item, drawn independently of the label, in
every slice. Domain is the only thing that moves.

The fourth slice, `code_security_rare`, is the control for the decomposition
itself: same domain, same items, base rate 0.25 instead of 0.50. If slope and
intercept really separate into "model" and "deployment", then moving only the
base rate should move the intercept and leave the slope where it is. Without
this slice a stable slope across domains is consistent with the slope simply
being stable, and the decomposition would be untested.

`python3 lab/domains/baselines.py` is the gate and should be run first. It
reports a cross-validated bag-of-words bar of 81.7-88.3% and cue-only accuracy
at 43.3-55.0%, near chance. A Jev accuracy inside the bag-of-words interval on
a slice measures vocabulary, and no claim about that slice survives.

## Preregistered, written before any call

H1, the slope transfers. Each domain's fitted Platt slope lands inside the
e-mail band of 2.11-2.61. Falsified if any lands outside a 25%-widened
[1.60, 3.10], in which case the slope is task-specific and the recipe is
e-mail-only.

H2, the decomposition is real. Between `code_security` and `code_security_rare`
the intercept moves by more than 0.8 logits while the slope moves by less than
0.5. Falsified if the slope moves more than the intercept does.

H3, the recipe works out of domain. Applying the e-mail slope and refitting the
intercept on 50 labels from the slice cuts that slice's ECE by at least 50% and
increases it in no slice. Falsified by any increase.

Expected outcome, stated plainly so it can be wrong: H1 and H2 hold, H3 holds
for the three balanced slices and is the one most at risk on
`code_security_rare`, because a 50-label sample at a 0.25 base rate carries
about 12 positives and the intercept fit gets noisy.

A null result here is worth as much as a positive one: it would bound a
published recipe to the domain it was fitted on.
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
from lab.domains.baselines import (  # noqa: E402
    SLICE_ORDER,
    cue_leakage,
    lexical,
    load,
    slices_are_comparable,
)

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(BASE, "runs")

# The band reported in analysis/CALIBRATION-TRANSFER.md, and the widened band
# that would falsify H1.
EMAIL_SLOPE_BAND = (2.11, 2.61)
FALSIFYING_BAND = (1.60, 3.10)

PREREGISTERED = {
    "H1_slope_transfers": (
        "Each domain's fitted Platt slope lands inside the e-mail band "
        f"{EMAIL_SLOPE_BAND}. Falsified if any lands outside {FALSIFYING_BAND}."
    ),
    "H2_decomposition_is_real": (
        "Between code_security and code_security_rare the intercept moves more "
        "than 0.8 logits while the slope moves less than 0.5. Falsified if the "
        "slope moves more than the intercept."
    ),
    "H3_recipe_works_out_of_domain": (
        "E-mail slope plus a 50-label intercept refit cuts each slice's ECE by "
        "at least 50% and increases it in none. Falsified by any increase."
    ),
}


def batches(items: list, size: int) -> list:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build(chunk: list) -> tuple:
    """One request per chunk. Each item carries its own question and criteria.

    Questions in one request see the shared state but not each other's
    instruction text, measured in lab/probe_structure.py, so batching items from
    one slice does not leak between them.
    """
    state = "Items:\n\n" + "\n\n---\n\n".join(
        f"[{item['id']}]\n{item['text']}" for item in chunk
    )
    questions = {
        item["id"]: {
            "type": "noul",
            "instructions": item["question"].format(id=item["id"]),
            "criteria": dict(item["criteria"]),
        }
        for item in chunk
    }
    return state, questions


def record(started_at: str, slice_name: str, rep: int, index: int, reply) -> None:
    os.makedirs(RUNS_DIR, exist_ok=True)
    path = os.path.join(RUNS_DIR, f"{started_at}-transfer-{slice_name}.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "slice": slice_name,
                    "rep": rep,
                    "batch": index,
                    "requested_at": reply.requested_at,
                    "model": reply.model,
                    "elapsed_s": round(reply.elapsed_s, 4),
                    "attempts": reply.attempts,
                    "usage": reply.usage,
                    "response": reply.raw,
                },
                sort_keys=True,
            )
            + "\n"
        )


def collect(sender, chunkset, started_at, slice_name, rep) -> dict:
    answers: dict = {}
    for index, chunk in enumerate(chunkset):
        state, questions = build(chunk)
        reply = ask(sender, state, questions)
        record(started_at, slice_name, rep, index, reply)
        for qid in questions:
            if qid in reply.answers:
                answers[qid] = reply.noul(qid)
        print(
            f"  {slice_name} pass {rep + 1} batch {index + 1}/{len(chunkset)}: "
            f"{reply.elapsed_s:.2f}s, {len(questions)} questions",
            file=sys.stderr,
        )
    return answers


def check_gate(rows: list) -> dict:
    """Run the dataset controls before spending anything."""
    by_slice = {s: [r for r in rows if r["slice"] == s] for s in SLICE_ORDER}
    lex = {s: lexical(rs) for s, rs in by_slice.items()}
    cues = {s: cue_leakage(rs) for s, rs in by_slice.items()}
    return {
        "lexical_bar": {s: round(lex[s]["accuracy"], 4) for s in SLICE_ORDER},
        "cue_only": {s: round(cues[s]["accuracy"], 4) for s in SLICE_ORDER},
        "slices_comparable": slices_are_comparable(lex, cues),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--slice", choices=SLICE_ORDER, help="run one slice")
    ap.add_argument("--batch-size", type=int, default=40)
    ap.add_argument("--repeat", type=int, default=3, help="passes per slice")
    ap.add_argument("--limit", type=int, help="first N items per slice")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=os.path.join(BASE, "domains", "transfer_answers.json"))
    args = ap.parse_args(argv)

    rows = load()
    names = [args.slice] if args.slice else SLICE_ORDER
    gate = check_gate(rows)

    if args.dry_run:
        total = 0
        for name in names:
            items = [r for r in rows if r["slice"] == name][: args.limit]
            chunks = batches(items, args.batch_size)
            calls = len(chunks) * args.repeat
            total += calls
            state, _ = build(chunks[0])
            print(
                f"{name:<22} {len(items):>4} items  {len(chunks):>2} batches x "
                f"{args.repeat} pass(es) = {calls:>3} calls  "
                f"(state ~{len(state) // 4} tokens)"
            )
        print(f"\nTotal calls: {total}")
        print(f"Approx cost at $0.042/MTok: ${total * 3200 * 0.042 / 1_000_000:.4f}")
        print(f"\ntransport: {describe_sender()}")
        print("\ndataset gate:")
        for name in SLICE_ORDER:
            print(
                f"  {name:<22} bag-of-words {gate['lexical_bar'][name]:.1%}   "
                f"cue-only {gate['cue_only'][name]:.1%}"
            )
        print(f"  slices comparable: {gate['slices_comparable']}")
        print("\npreregistered:")
        for key, text in PREREGISTERED.items():
            print(f"  {key}: {text}")
        return 0

    if not gate["slices_comparable"]:
        print(
            "Dataset gate failed: the slices differ in more than domain. "
            "Run lab/domains/baselines.py and fix the dataset before spending "
            "calls; the transfer comparison is not interpretable otherwise.",
            file=sys.stderr,
        )
        return 2

    sender = resolve_sender()
    started_at = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    results = {
        "started_at": started_at,
        "transport": describe_sender(),
        "repeat": args.repeat,
        "preregistered": PREREGISTERED,
        "dataset_gate": gate,
        "slices": {},
    }

    for name in names:
        items = [r for r in rows if r["slice"] == name][: args.limit]
        chunkset = batches(items, args.batch_size)
        passes = [
            collect(sender, chunkset, started_at, name, rep)
            for rep in range(args.repeat)
        ]
        # Mean across passes, so a single stochastic answer cannot set a slope.
        merged = {
            qid: round(statistics.mean(p[qid] for p in passes if qid in p), 6)
            for qid in passes[0]
        }
        results["slices"][name] = {
            "n": len(merged),
            "passes": len(passes),
            "probabilities": merged,
        }
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"{name}: {len(merged)} answers over {len(passes)} passes", file=sys.stderr)

    print(f"\nRaw responses in {RUNS_DIR}/, answers in {args.out}")
    print("Now run: python3 analysis/transfer_domains.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
