"""Probes for three structural claims about the API, from the 2026-09-18 sweep.

    python3 lab/probe_structure.py --dry-run             # no key: sizes the run
    python3 lab/probe_structure.py --probe isolation --repeat 3
    python3 lab/probe_structure.py --probe batching --sizes 1,25,100,400
    python3 lab/probe_structure.py --probe formulation --repeat 3

Each probe carries a prediction written before the run and checked afterwards, so
a result cannot be adjudicated once the numbers are in. Raw responses land in
lab/runs/ before scoring.

isolation    Questions in one request see the shared state but not each other's
             instruction text. Claimed by archerhume via aiwithmike (sweep T23);
             if true it is a structural property nothing in this repo had tested,
             and it constrains how a batched payload may be written.

batching     Marginal cost of adding questions to a request. The sweep reports
             ~0.3 ms per question client-side at 1,000 questions (S10); this repo
             has only ever measured 8 to 100.

formulation  One Choice over K classes against K independent Nouls. The sweep
             found binary-per-item formulations leave 0.38-0.78 probability on
             distractors where a single Choice does not (S19), and recommends
             Choice for classification. Both the difficulty gradient and the
             negation probe in this repo use Nouls, so this decides whether
             those under-report what the model can do.

## Credentials

This file contains no credential handling. It calls
`jevlab.transport.resolve_sender()`, which defaults to the repo's client and can
be replaced with `JEV_TRANSPORT=package.module:callable`. The replacement takes
`(state, questions, model)` and returns the raw response dict; whatever it does
about authentication is invisible here, so the same file runs unmodified on
either side.

    JEV_TRANSPORT=my_ops.jev:send python3 lab/probe_structure.py --repeat 3
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jevlab.transport import (  # noqa: E402
    ask,
    describe_sender,
    resolve_sender,
)

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(BASE, "runs")

# A word that should appear nowhere in any model's ordinary vocabulary for this
# task, so its probability is driven by presence in the payload rather than prior.
CODE_WORD = "VELLICHOR"
ABSENT_WORD = "QUINTARREL"

NEUTRAL_STATE = (
    "Meeting notes, 14 March. Procurement confirmed the revised lead times for "
    "the Q2 order. Facilities will repaint the east stairwell over the weekend. "
    "The travel policy per-diem rises next month. No decisions outstanding."
)

# Written before the run. See the module docstring.
PREDICTIONS = {
    "isolation": (
        "If questions are isolated, a code word appearing only in another "
        "question's instructions scores below 0.30, while the same word placed "
        "in the shared state scores above 0.70. Both absent-word controls stay "
        "below 0.30."
    ),
    "batching": (
        "Marginal wall-clock cost is under 5 ms per additional question, so a "
        "400-question request costs less than 2 s more than a 1-question one."
    ),
    "formulation": (
        "A single Choice leaves less probability mass on wrong classes than K "
        "independent Nouls over the same classes."
    ),
}


def record(name: str, resp, started_at: str, meta: dict) -> None:
    os.makedirs(RUNS_DIR, exist_ok=True)
    path = os.path.join(RUNS_DIR, f"{started_at}-probe-{name}.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(
            json.dumps(
                {
                    "probe": name,
                    "meta": meta,
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


# --------------------------------------------------------------------- isolation


def isolation_payloads() -> list:
    """Two conditions, each one request. The only difference is where the code
    word sits: in a sibling question's instructions, or in the shared state."""
    def questions(carrier_word: str) -> dict:
        return {
            "carrier": {
                "type": "noul",
                "instructions": (
                    f"Ignoring everything else, is the word {carrier_word} a noun?"
                ),
                "criteria": {"true": "It is a noun", "false": "It is not a noun"},
            },
            "probe_code": {
                "type": "noul",
                "instructions": (
                    f"Does the text you were given contain the word {CODE_WORD}?"
                ),
                "criteria": {"true": "It appears", "false": "It does not appear"},
            },
            "probe_absent": {
                "type": "noul",
                "instructions": (
                    f"Does the text you were given contain the word {ABSENT_WORD}?"
                ),
                "criteria": {"true": "It appears", "false": "It does not appear"},
            },
        }

    return [
        # A: code word only in a sibling question's instructions.
        ("in_sibling_question", NEUTRAL_STATE, questions(CODE_WORD)),
        # B: code word in the shared state, sibling carries an unrelated word.
        (
            "in_shared_state",
            NEUTRAL_STATE + f" Filing reference {CODE_WORD}.",
            questions("cartography"),
        ),
    ]


def score_isolation(results: dict) -> dict:
    a = results["in_sibling_question"]
    b = results["in_shared_state"]
    met = (
        a["probe_code"] < 0.30
        and b["probe_code"] > 0.70
        and a["probe_absent"] < 0.30
        and b["probe_absent"] < 0.30
    )
    return {
        "code_word_in_sibling_question": a["probe_code"],
        "code_word_in_shared_state": b["probe_code"],
        "absent_control_a": a["probe_absent"],
        "absent_control_b": b["probe_absent"],
        "prediction_met": met,
        "reading": (
            "questions are isolated from each other's instructions"
            if met
            else "prediction not met; see the raw values"
        ),
    }


# ---------------------------------------------------------------------- batching


def batching_payload(size: int) -> tuple:
    questions = {
        f"q{i:04d}": {
            "type": "noul",
            "instructions": f"Is item {i} mentioned anywhere in the notes?",
            "criteria": {"true": "Mentioned", "false": "Not mentioned"},
        }
        for i in range(size)
    }
    return NEUTRAL_STATE, questions


def score_batching(timings: dict) -> dict:
    """Least-squares slope of wall clock against question count."""
    sizes = sorted(timings)
    xs = [float(s) for s in sizes]
    ys = [statistics.median(timings[s]) for s in sizes]
    n = len(xs)
    mean_x, mean_y = sum(xs) / n, sum(ys) / n
    denom = sum((x - mean_x) ** 2 for x in xs)
    slope = (
        sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
        if denom
        else float("nan")
    )
    ms_per_question = slope * 1000
    return {
        "median_seconds_by_size": {str(s): round(statistics.median(timings[s]), 3) for s in sizes},
        "marginal_ms_per_question": round(ms_per_question, 3),
        "intercept_s": round(mean_y - slope * mean_x, 3),
        "prediction_met": ms_per_question < 5.0,
    }


# ------------------------------------------------------------------- formulation

CLASSES = {
    "billing": "Payments, invoices, refunds, charges, subscriptions",
    "technical": "Bugs, errors, outages, integrations, crashes",
    "sales": "Plan comparisons, quotes, discounts, pre-purchase questions",
    "other": "Anything that is not a failure, a payment matter, or a pre-sale question",
}
FORMULATION_ITEM = (
    "My card was charged twice for the Pro plan this month. I need a refund for "
    "the duplicate charge."
)
FORMULATION_GOLD = "billing"


def formulation_payloads() -> list:
    choice = {
        "as_choice": {
            "type": "choice",
            "instructions": "Which team should handle this ticket?",
            "criteria": dict(CLASSES),
        }
    }
    nouls = {
        f"is_{name}": {
            "type": "noul",
            "instructions": f"Should this ticket be handled by the {name} team? ({desc})",
            "criteria": {"true": f"Yes, {name}", "false": f"No, not {name}"},
        }
        for name, desc in CLASSES.items()
    }
    return [("choice", FORMULATION_ITEM, choice), ("nouls", FORMULATION_ITEM, nouls)]


def score_formulation(choice_probs: dict, noul_probs: dict) -> dict:
    """Distractor mass: how much probability lands on wrong classes."""
    choice_distractors = sum(
        v for k, v in choice_probs.items() if k != FORMULATION_GOLD
    )
    noul_distractors = sum(
        v for k, v in noul_probs.items() if k != FORMULATION_GOLD
    )
    return {
        "choice_probabilities": {k: round(v, 3) for k, v in choice_probs.items()},
        "noul_probabilities": {k: round(v, 3) for k, v in noul_probs.items()},
        "choice_distractor_mass": round(choice_distractors, 3),
        "noul_distractor_mass": round(noul_distractors, 3),
        "max_distractor_choice": round(
            max((v for k, v in choice_probs.items() if k != FORMULATION_GOLD), default=0), 3
        ),
        "max_distractor_noul": round(
            max((v for k, v in noul_probs.items() if k != FORMULATION_GOLD), default=0), 3
        ),
        "prediction_met": choice_distractors < noul_distractors,
        "note": (
            "Noul probabilities need not sum to 1: each is an independent "
            "question. That is the point of the comparison, not a defect."
        ),
    }


# -------------------------------------------------------------------------- main


def run_isolation(sender, started_at, repeat) -> dict:
    per_condition = {}
    for label, state, questions in isolation_payloads():
        runs = []
        for rep in range(repeat):
            resp = ask(sender, state, questions)
            record("isolation", resp, started_at, {"condition": label, "rep": rep})
            runs.append({q: resp.noul(q) for q in questions})
            print(f"  isolation/{label} pass {rep + 1}: {resp.elapsed_s:.2f}s", file=sys.stderr)
        per_condition[label] = {
            q: round(statistics.mean(r[q] for r in runs), 3) for q in runs[0]
        }
    return {"per_condition": per_condition, **score_isolation(per_condition)}


def run_batching(sender, started_at, sizes, repeat) -> dict:
    timings: dict = {}
    for size in sizes:
        state, questions = batching_payload(size)
        timings[size] = []
        for rep in range(repeat):
            resp = ask(sender, state, questions)
            record("batching", resp, started_at, {"size": size, "rep": rep})
            timings[size].append(resp.elapsed_s)
            print(
                f"  batching/{size}q pass {rep + 1}: {resp.elapsed_s:.2f}s, "
                f"{resp.usage.get('input_tokens', '?')} input tokens",
                file=sys.stderr,
            )
    return score_batching(timings)


def run_formulation(sender, started_at, repeat) -> dict:
    collected: dict = {}
    for label, state, questions in formulation_payloads():
        runs = []
        for rep in range(repeat):
            resp = ask(sender, state, questions)
            record("formulation", resp, started_at, {"form": label, "rep": rep})
            if label == "choice":
                runs.append(dict(resp.probabilities("as_choice")))
            else:
                runs.append({k[3:]: resp.noul(k) for k in questions})
            print(f"  formulation/{label} pass {rep + 1}: {resp.elapsed_s:.2f}s", file=sys.stderr)
        keys = runs[0].keys()
        collected[label] = {k: statistics.mean(r.get(k, 0.0) for r in runs) for k in keys}
    return score_formulation(collected["choice"], collected["nouls"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument(
        "--probe",
        choices=["isolation", "batching", "formulation", "all"],
        default="all",
    )
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--sizes", default="1,25,100,400", help="batching sizes")
    ap.add_argument("--dry-run", action="store_true", help="size the run, make no calls")
    ap.add_argument("--out", default=os.path.join(BASE, "probe_structure_results.json"))
    args = ap.parse_args(argv)

    sizes = [int(s) for s in args.sizes.split(",") if s.strip()]
    wanted = (
        ["isolation", "batching", "formulation"] if args.probe == "all" else [args.probe]
    )

    if args.dry_run:
        calls = 0
        for name in wanted:
            if name == "isolation":
                n = 2 * args.repeat
                print(f"isolation    {n:>3} calls, 3 questions each")
            elif name == "batching":
                n = len(sizes) * args.repeat
                biggest = batching_payload(max(sizes))
                print(
                    f"batching     {n:>3} calls, sizes {sizes}, "
                    f"largest payload ~{len(json.dumps(biggest[1])) // 4} tokens"
                )
            else:
                n = 2 * args.repeat
                print(f"formulation  {n:>3} calls, 1 Choice vs {len(CLASSES)} Nouls")
            calls += n
        print(f"\nTotal calls: {calls}")
        print(f"\ntransport: {describe_sender()}")
        for name in wanted:
            print(f"\nprediction [{name}]: {PREDICTIONS[name]}")
        return 0

    started_at = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    sender = resolve_sender()
    results = {
        "started_at": started_at,
        "transport": describe_sender(),
        "repeat": args.repeat,
        "predictions": {},
    }

    for name in wanted:
        results["predictions"][name] = PREDICTIONS[name]
        try:
            if name == "isolation":
                results[name] = run_isolation(sender, started_at, args.repeat)
            elif name == "batching":
                results[name] = run_batching(sender, started_at, sizes, args.repeat)
            else:
                results[name] = run_formulation(sender, started_at, args.repeat)
        except Exception as exc:  # an injected transport raises what it likes
            results[name] = {"error": str(exc)}
            print(f"{name}: {exc}", file=sys.stderr)
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2)
            fh.write("\n")

    print("\n=== structural probes ===")
    for name in wanted:
        block = results.get(name, {})
        print(f"\n{name}")
        print(f"  prediction: {PREDICTIONS[name]}")
        if "error" in block:
            print(f"  ERROR: {block['error']}")
            continue
        for key, value in block.items():
            if key in ("per_condition", "note"):
                continue
            print(f"  {key}: {value}")
    print(f"\nRaw responses in {RUNS_DIR}/, summary in {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
