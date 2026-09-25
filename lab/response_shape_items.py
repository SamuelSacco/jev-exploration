"""Generate the graded-evidence item set for lab/exp_response_shape.py.

    python3 lab/response_shape_items.py --out lab/response_shape_items.json

Deterministic and seeded, so the committed file can be rebuilt byte for byte.
The label is chosen before the text exists, as everywhere else in this repo.

Four options, so a Choice has somewhere to put probability other than the
winner, and three bands of evidence:

  decisive    one department's signal, stated plainly, nothing competing
  moderate    the same signal, hedged, plus one weak signal for another
              department
  ambiguous   two departments' signals at comparable strength, and the gold
              label is the one the ticket's actual REQUEST points at, not the
              one with more words

The bands matter because E2 asks whether exact-0 option probabilities retreat as
evidence weakens. If the ambiguous band is not genuinely ambiguous the probe
measures nothing, so `python3 lab/response_shape_items.py --check` reports the
bag-of-words separability of each band and is the gate: decisive should be
easy, ambiguous should be near chance for a lexical method.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

HERE = os.path.dirname(os.path.abspath(__file__))

OPTIONS = {
    "billing": "Payments, invoices, refunds, charges and disputes about amounts",
    "technical": "Bugs, errors, outages, integrations and broken features",
    "sales": "Plan comparisons, quotes, discounts, upgrades and pre-purchase questions",
    "account": "Logins, seats, permissions, ownership and profile changes",
}

QUESTION = "Which team should handle ticket {id}?"

# Signal sentences per department, in two strengths. The hedged form carries the
# same vocabulary as the plain one, so a band is not separable on words alone.
SIGNALS = {
    "billing": {
        "plain": "We were charged twice for the March invoice and need one of the charges refunded.",
        "hedged": "There may be a duplicate on the March invoice, we are not certain yet.",
    },
    "technical": {
        "plain": "The export endpoint returns a 500 on every request since this morning.",
        "hedged": "The export endpoint has felt slower than usual this week, no errors seen.",
    },
    "sales": {
        "plain": "We want a quote for moving from the team plan to enterprise before renewal.",
        "hedged": "We have been reading about the enterprise plan but have not decided anything.",
    },
    "account": {
        "plain": "Please transfer workspace ownership from the departing admin to me.",
        "hedged": "The departing admin still appears on the workspace list, which seems odd.",
    },
}

# For the ambiguous band. Both departments' topics appear in the resolver
# whichever one is gold, and only their ROLES swap, so a bag-of-words method
# sees the same tokens either way and cannot use word presence to answer. An
# earlier version used a one-sided request sentence naming only the gold
# department's action, which made the ambiguous band MORE separable than the
# moderate one: 75% against 35%, the opposite of the intended gradient.
TOPICS = {
    "billing": "the invoice question",
    "technical": "the export problem",
    "sales": "the plan question",
    "account": "the workspace question",
}
RESOLVER = "{other} can wait. {gold} is what is blocking us today."

OPENERS = [
    "Hello,",
    "Hi team,",
    "Good morning,",
    "Hi there,",
]
CLOSERS = [
    "Thanks in advance.",
    "Appreciate the help.",
    "Let us know.",
    "Thank you.",
]

BANDS = ["decisive", "moderate", "ambiguous"]


def build(gold: str, strength: str, index: int, rng: random.Random) -> dict:
    others = [d for d in OPTIONS if d != gold]
    lines = [rng.choice(OPENERS), ""]

    if strength == "decisive":
        lines.append(SIGNALS[gold]["plain"])
    elif strength == "moderate":
        lines.append(SIGNALS[gold]["hedged"])
        lines.append(SIGNALS[rng.choice(others)]["hedged"])
    else:
        # Two signals at equal strength. The resolver names both topics and
        # swaps only which is blocking, so the tokens are the same whichever
        # department is gold.
        distractor = rng.choice(others)
        pair = [SIGNALS[gold]["plain"], SIGNALS[distractor]["plain"]]
        rng.shuffle(pair)
        lines.extend(pair)
        lines.append(
            RESOLVER.format(
                other=TOPICS[distractor].capitalize(), gold=TOPICS[gold].capitalize()
            )
        )

    lines.extend(["", rng.choice(CLOSERS)])
    return {
        "id": f"rs{index:03d}",
        "strength": strength,
        "gold": gold,
        "question": QUESTION.format(id=f"rs{index:03d}"),
        "options": dict(OPTIONS),
        "text": "\n".join(lines),
    }


def generate(per_band: int = 20, seed: int = 20260924) -> list:
    rng = random.Random(seed)
    departments = list(OPTIONS)
    items, index = [], 0
    for strength in BANDS:
        for i in range(per_band):
            # Balanced across departments within each band, so a majority-class
            # baseline sits at 25% everywhere.
            gold = departments[i % len(departments)]
            items.append(build(gold, strength, index, rng))
            index += 1
    return items


def separability(items: list) -> dict:
    """Bag-of-words accuracy per band, as the gate on the ambiguous band."""
    from lab.domains.baselines import _fit, tokens  # noqa: F401

    out = {}
    for band in BANDS:
        rows = [i for i in items if i["strength"] == band]
        folds = [[], []]
        for gold in {r["gold"] for r in rows}:
            same = [r for r in rows if r["gold"] == gold]
            for i, row in enumerate(same):
                folds[i % 2].append(row)
        hits = 0
        for train, test in ((folds[0], folds[1]), (folds[1], folds[0])):
            model = _fit_multiclass(train)
            hits += sum(1 for r in test if model(r["text"]) == r["gold"])
        out[band] = round(hits / len(rows), 4)
    return out


def gradient_is_monotone(sep: dict) -> bool:
    """Evidence must actually weaken across the bands, or E2 measures nothing."""
    return sep["decisive"] > sep["moderate"] >= sep["ambiguous"]


def ambiguous_is_unsolvable(sep: dict, slack: float = 0.15) -> bool:
    """The ambiguous band must be near chance for a lexical method.

    Chance is 0.25 with four options. If a word counter can answer this band,
    then "ambiguous" describes the intent and not the data.
    """
    return sep["ambiguous"] <= 0.25 + slack


def _fit_multiclass(rows: list):
    """Multinomial Naive Bayes over the four departments."""
    import math

    from lab.domains.baselines import tokens

    counts, totals, docs, vocab = {}, {}, {}, set()
    for row in rows:
        label = row["gold"]
        counts.setdefault(label, {})
        totals.setdefault(label, 0)
        docs[label] = docs.get(label, 0) + 1
        for tok in tokens(row["text"]):
            counts[label][tok] = counts[label].get(tok, 0) + 1
            totals[label] += 1
            vocab.add(tok)
    n, size = len(rows), max(len(vocab), 1)

    def predict(text: str) -> str:
        best, best_score = None, None
        for label in sorted(docs):
            score = math.log(docs[label] / n)
            for tok in tokens(text):
                score += math.log((counts[label].get(tok, 0) + 1) / (totals[label] + size))
            if best_score is None or score > best_score:
                best, best_score = label, score
        return best

    return predict


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(HERE, "response_shape_items.json"))
    ap.add_argument("--per-band", type=int, default=20)
    ap.add_argument("--seed", type=int, default=20260924)
    ap.add_argument("--check", action="store_true", help="report separability only")
    args = ap.parse_args(argv)

    items = generate(args.per_band, args.seed)
    sep = separability(items)

    if args.check:
        print("bag-of-words accuracy per band (chance = 25%):\n")
        for band in BANDS:
            print(f"  {band:<11} {sep[band]:.1%}")
        print(f"\nmonotone: {gradient_is_monotone(sep)}")
        print(f"ambiguous near chance: {ambiguous_is_unsolvable(sep)}")
        ok = gradient_is_monotone(sep) and ambiguous_is_unsolvable(sep)
        print(f"gate: {ok}")
        return 0 if ok else 1

    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(
            {"version": "1.0", "separability": sep, "items": items},
            fh,
            indent=2,
            sort_keys=True,
        )
        fh.write("\n")
    print(f"Wrote {len(items)} items to {args.out}")
    for band in BANDS:
        print(f"  {band:<11} n={sum(1 for i in items if i['strength'] == band):<4} "
              f"bag-of-words {sep[band]:.1%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
