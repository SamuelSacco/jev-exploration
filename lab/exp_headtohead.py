"""Jev against a local 4B model, on Jev's home turf and on its weak shapes.

    python3 lab/exp_headtohead.py --dry-run          # sizes it, no credential
    JEV_TRANSPORT=my_ops.jev:send \\
    JEV_LOCAL_TRANSPORT=my_ops.ollama:send \\
    python3 lab/exp_headtohead.py --repeat 3

Contains no credential handling and no network code. Both sides are injected:
`JEV_TRANSPORT` supplies a callable taking `(state, questions, model)` and
returning the raw response dict; `JEV_LOCAL_TRANSPORT` supplies a callable
taking a prompt string and returning the reply text. This repo has no default
for the second one and no code that can reach a local inference server, because
its only approved endpoint is Jev's.

Parsing the local model's text into a probability happens HERE rather than in
the operator's script, so the rule that turns words into numbers is versioned
and tested alongside the results it produces.

## Why these four arms

The interesting question is not "which is better" but "where does each one's
advantage live". So the battery deliberately spans the cases the public record
says should go opposite ways.

  home_turf    code_security, Noul. Tight binary classification against a
               written definition, which is the shape TypeSafe markets and the
               shape scienthoon's trained-4B comparison found Jev losing at
               once a few hundred labels exist. n=120.

  adversarial  t4_adversarial, Noul. Calm, specific phishing and alarming
               legitimate mail: the tier where surface cues point the wrong way.
               jev-phishing-bench (T15) reports Jev weakest on phishing verdicts
               and a plain regex beating its best single signal. n=120.

  negation     the 40 minimal pairs as 80 items, Noul. Constructed so that no
               lexical method beats chance (measured 51.2%), which makes it the
               one arm where a bag-of-words baseline cannot flatter anybody.
               n=80.

  typed        t4_adversarial again, as a two-option Choice instead of a Noul.
               Same items, same tier, different primitive. T75 found Choice
               putting all its probability on the right label where independent
               Nouls left 0.29 on distractors, which would mean every Noul-only
               result in this repo, the gradient included, under-reports Jev.
               This arm is the direct test of that, and it is why the
               comparison is run on the tier where there is the most room to
               move. n=120.

`typed` shares its items with `adversarial` on purpose: the only difference
between the two arms is the primitive, so the gap between them is the
formulation effect and nothing else.

## Baselines

Every arm carries three, because a head-to-head with no floor under it says
nothing about either model:

  random      0.5 with a Wilson interval at that n
  majority    always the commoner label
  lexical     two-fold cross-validated bag of words, fitted per arm

A model inside the lexical interval on an arm has not been shown to do anything
a word counter cannot.

## Preregistered, written before any call

H1. Jev beats the lexical bar on `home_turf` and on `negation`, and does not on
`adversarial`. Falsified if it clears the bar on `adversarial` or misses it on
`negation`.

H2. The local 4B beats Jev on `home_turf` accuracy, since that arm has written
definitions and a consistent rule, and loses on `negation`, which needs the
distinction a small model is least likely to hold. Falsified by either half.

H3. Jev's calibration is better than the local model's everywhere: lower
ECE-to-floor ratio on all four arms. Jev returns probabilities as its output
rather than as a parsed number, and T73 found its variance 433-913x lower than
LLM judges. Falsified if the local model has a lower ratio on any arm.

H4. `typed` beats `adversarial` on accuracy with non-overlapping bootstrap
intervals on the difference. This is T75's finding carried onto a harder slice.
Falsified if the difference interval covers zero, in which case T75's result
does not generalise past its single classification item and the Noul-only
results in this ledger need no formulation caveat.

Stated plainly so it can be wrong: H2 is the one expected to sting, and H4 is
the one that would force the most rewriting if it holds.

## Cost

33 Jev calls at default settings, about $0.005. The local side is free and slow:
440 items x 3 passes is 1,320 local calls, so `--local-repeat` and `--limit`
exist for sizing it down.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from jevlab.transport import (  # noqa: E402
    ask,
    describe_local_sender,
    describe_sender,
    resolve_local_sender,
    resolve_sender,
)

BASE = os.path.dirname(os.path.abspath(__file__))
RUNS_DIR = os.path.join(BASE, "runs")

ARMS = ["home_turf", "adversarial", "negation", "typed"]
# t4_adversarial holds 200 items. Capped so the battery stays in the tens of
# calls, and so the four arms sit within a factor of two of each other in n.
TIER_CAP = 120

PREREGISTERED = {
    "H1_jev_clears_the_bar_where_expected": (
        "Jev beats the lexical bar on home_turf and negation and not on "
        "adversarial. Falsified if it clears the bar on adversarial or misses "
        "it on negation."
    ),
    "H2_local_wins_home_turf_and_loses_negation": (
        "The local 4B beats Jev on home_turf accuracy and loses on negation. "
        "Falsified by either half."
    ),
    "H3_jev_calibrates_better_everywhere": (
        "Jev's ECE-to-floor ratio is lower than the local model's on all four "
        "arms. Falsified if the local model is lower on any arm."
    ),
    "H4_choice_beats_noul_on_the_same_items": (
        "typed beats adversarial on accuracy with a bootstrap interval on the "
        "difference that excludes zero. Falsified if the interval covers zero."
    ),
}

# The local model is asked for one number and nothing else. Parsed here so the
# rule is versioned with the results; see parse_probability.
LOCAL_PROMPT = """{question}

Answer with a single number between 0.00 and 1.00: the probability that the answer is yes.
"true" means: {true_label}
"false" means: {false_label}

Item:
{text}

Reply with the number alone and nothing else."""

# Tried in order. An explicit "probability: x" beats anything else in the
# reply; a line that is nothing but a number beats a number buried in prose;
# and within a category the LAST match wins, because a model that reasons
# before answering states its conclusion at the end. Each entry is
# (pattern, is_percentage, take_last).
_PROB_PATTERNS = [
    (re.compile(r"probability\D{0,20}?(\d{1,3}(?:\.\d+)?)\s*%", re.I), True, False),
    (re.compile(r"probability\D{0,20}?(\d?\.\d+|[01](?:\.0+)?)", re.I), False, False),
    (re.compile(r"^\s*(\d?\.\d+|[01](?:\.0+)?)\s*\.?\s*$", re.M), False, True),
    (re.compile(r"(\d{1,3}(?:\.\d+)?)\s*%"), True, True),
    (re.compile(r"(?<![\d.])(\d?\.\d+|[01])(?!\d)"), False, True),
]


def parse_probability(text: str):
    """Pull a probability out of a local model's reply, or None.

    Small models pad, hedge, and emit chain-of-thought before the answer, so
    this cannot be `float(text)`. None rather than a default on failure: a
    silent 0.5 would look like calibrated uncertainty and would be a parser bug
    wearing a result's clothes. Unparsed items are reported, never imputed.
    """
    if not text:
        return None
    body = re.sub(r"<think>.*?</think>", " ", text, flags=re.S | re.I)
    for pattern, is_percent, take_last in _PROB_PATTERNS:
        matches = pattern.findall(body)
        if not matches:
            continue
        raw = matches[-1] if take_last else matches[0]
        value = float(raw)
        if is_percent:
            value /= 100.0
        if 0.0 <= value <= 1.0:
            return value
    return None


def load_arms(limit=None) -> dict:
    """The four arms, from data already committed to this repo."""
    from lab.domains.baselines import load as load_domains
    from lab.tiers.baselines import load as load_tiers

    domains = [r for r in load_domains() if r["slice"] == "code_security"]
    tiers = [r for r in load_tiers() if r["tier"] == "t4_adversarial"][:TIER_CAP]
    with open(os.path.join(BASE, "negation.json"), encoding="utf-8") as fh:
        negation = json.load(fh)

    from lab.run_demos import negation_items

    neg = negation_items(negation)

    arms = {
        "home_turf": [
            {
                "id": r["id"],
                "text": r["text"],
                "gold": r["is_positive"],
                "question": r["question"].format(id=r["id"]),
                "criteria": r["criteria"],
                "primitive": "noul",
            }
            for r in domains
        ],
        "adversarial": [
            {
                "id": r["id"],
                "text": r["text"],
                "gold": r["is_phishing"],
                "question": (
                    f"Is message {r['id']} a phishing or otherwise malicious "
                    "email, as opposed to a legitimate one? Judge the message "
                    "on its own content."
                ),
                "criteria": {
                    "true": "Phishing or otherwise malicious",
                    "false": "A legitimate message",
                },
                "primitive": "noul",
            }
            for r in tiers
        ],
        "negation": [
            {
                "id": item[0],
                "text": f"Claim: {item[1]}\n\nPassage: {item[2]}",
                "gold": bool(item[3]),
                "question": (
                    f"Does the passage in item {item[0]} support the claim, "
                    "as opposed to contradicting it?"
                ),
                "criteria": {
                    "true": "The passage supports the claim",
                    "false": "The passage contradicts the claim",
                },
                "primitive": "noul",
            }
            for item in neg
        ],
    }
    # Same items as `adversarial`, asked as a Choice. The one difference is the
    # primitive, so the gap between the arms is the formulation effect.
    arms["typed"] = [dict(item, primitive="choice") for item in arms["adversarial"]]
    if limit:
        arms = {k: v[:limit] for k, v in arms.items()}
    return arms


def batches(items: list, size: int) -> list:
    return [items[i : i + size] for i in range(0, len(items), size)]


def build_jev(chunk: list) -> tuple:
    state = "Items:\n\n" + "\n\n---\n\n".join(
        f"[{item['id']}]\n{item['text']}" for item in chunk
    )
    questions = {}
    for item in chunk:
        if item["primitive"] == "choice":
            questions[item["id"]] = {
                "type": "choice",
                "instructions": item["question"],
                # Choice criteria is a dict of {label: description}; a list 422s.
                "criteria": {
                    "yes": item["criteria"]["true"],
                    "no": item["criteria"]["false"],
                },
            }
        else:
            questions[item["id"]] = {
                "type": "noul",
                "instructions": item["question"],
                "criteria": dict(item["criteria"]),
            }
    return state, questions


def read_jev(reply, item: dict):
    """One probability of 'yes' per item, whichever primitive was used."""
    qid = item["id"]
    if qid not in reply.answers:
        return None
    if item["primitive"] == "choice":
        return float(reply.probabilities(qid).get("yes", 0.0))
    return reply.noul(qid)


def record(started_at: str, arm: str, side: str, rep: int, index: int, payload: dict) -> None:
    os.makedirs(RUNS_DIR, exist_ok=True)
    path = os.path.join(RUNS_DIR, f"{started_at}-h2h-{arm}-{side}.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(payload, arm=arm, side=side, rep=rep, batch=index),
                            sort_keys=True) + "\n")


def run_jev(sender, items, started_at, arm, rep, batch_size) -> dict:
    out = {}
    for index, chunk in enumerate(batches(items, batch_size)):
        state, questions = build_jev(chunk)
        reply = ask(sender, state, questions)
        record(started_at, arm, "jev", rep, index, {
            "requested_at": reply.requested_at,
            "model": reply.model,
            "elapsed_s": round(reply.elapsed_s, 4),
            "usage": reply.usage,
            "response": reply.raw,
        })
        for item in chunk:
            value = read_jev(reply, item)
            if value is not None:
                out[item["id"]] = value
        print(f"  {arm}/jev pass {rep + 1} batch {index + 1}: "
              f"{reply.elapsed_s:.2f}s, {len(questions)} questions", file=sys.stderr)
    return out


def run_local(sender, items, started_at, arm, rep) -> tuple:
    out, unparsed, latencies = {}, [], []
    for index, item in enumerate(items):
        prompt = LOCAL_PROMPT.format(
            question=item["question"],
            true_label=item["criteria"]["true"],
            false_label=item["criteria"]["false"],
            text=item["text"],
        )
        started = time.monotonic()
        text = sender(prompt)
        elapsed = time.monotonic() - started
        latencies.append(elapsed)
        value = parse_probability(text)
        record(started_at, arm, "local", rep, index, {
            "id": item["id"], "elapsed_s": round(elapsed, 4),
            "reply": text, "parsed": value,
        })
        if value is None:
            unparsed.append(item["id"])
        else:
            out[item["id"]] = value
        if (index + 1) % 25 == 0:
            print(f"  {arm}/local pass {rep + 1}: {index + 1}/{len(items)}", file=sys.stderr)
    return out, unparsed, latencies


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--arm", choices=ARMS, help="run one arm")
    ap.add_argument("--side", choices=["jev", "local", "both"], default="both")
    ap.add_argument("--batch-size", type=int, default=40)
    ap.add_argument("--repeat", type=int, default=3, help="Jev passes")
    ap.add_argument("--local-repeat", type=int, default=3)
    ap.add_argument("--limit", type=int, help="first N items per arm")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--out", default=os.path.join(BASE, "headtohead_answers.json"))
    args = ap.parse_args(argv)

    arms = load_arms(args.limit)
    names = [args.arm] if args.arm else ARMS

    if args.dry_run:
        jev_calls = local_calls = 0
        for name in names:
            items = arms[name]
            chunks = len(batches(items, args.batch_size))
            jev_calls += chunks * args.repeat
            local_calls += len(items) * args.local_repeat
            print(f"{name:<14} {len(items):>4} items  {chunks:>2} batches x "
                  f"{args.repeat} = {chunks * args.repeat:>2} Jev calls, "
                  f"{len(items) * args.local_repeat:>5} local calls "
                  f"({items[0]['primitive']})")
        print(f"\nJev calls: {jev_calls}   "
              f"approx ${jev_calls * 3400 * 0.042 / 1_000_000:.4f}")
        print(f"Local calls: {local_calls} (free, but not fast)")
        print(f"\ntransport (jev):   {describe_sender()}")
        print(f"transport (local): {describe_local_sender()}")
        print("\npreregistered:")
        for key, text in PREREGISTERED.items():
            print(f"  {key}: {text}")
        return 0

    started_at = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    results = {
        "started_at": started_at,
        "transport_jev": describe_sender(),
        "transport_local": describe_local_sender(),
        "repeat": args.repeat,
        "local_repeat": args.local_repeat,
        "preregistered": PREREGISTERED,
        "arms": {},
    }

    jev_sender = resolve_sender() if args.side in ("jev", "both") else None
    local_sender = resolve_local_sender() if args.side in ("local", "both") else None

    for name in names:
        items = arms[name]
        block = {"n": len(items), "primitive": items[0]["primitive"],
                 "gold": {i["id"]: i["gold"] for i in items}}

        if jev_sender:
            passes = [run_jev(jev_sender, items, started_at, name, r, args.batch_size)
                      for r in range(args.repeat)]
            block["jev"] = {
                "passes": len(passes),
                "probabilities": {
                    qid: round(statistics.mean(p[qid] for p in passes if qid in p), 6)
                    for qid in passes[0]
                },
            }

        if local_sender:
            passes, unparsed, latencies = [], [], []
            for r in range(args.local_repeat):
                got, missed, took = run_local(local_sender, items, started_at, name, r)
                passes.append(got)
                unparsed.extend(missed)
                latencies.extend(took)
            block["local"] = {
                "passes": len(passes),
                "unparsed": sorted(set(unparsed)),
                "latency_p50_s": round(statistics.median(latencies), 4) if latencies else None,
                "probabilities": {
                    qid: round(statistics.mean(p[qid] for p in passes if qid in p), 6)
                    for qid in passes[0]
                },
            }

        results["arms"][name] = block
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(results, fh, indent=2, sort_keys=True)
            fh.write("\n")
        print(f"{name}: done", file=sys.stderr)

    print(f"\nRaw responses in {RUNS_DIR}/, answers in {args.out}")
    print("Now run: python3 analysis/headtohead.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
