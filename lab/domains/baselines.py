"""Non-AI controls for the cross-domain dataset.

    python3 lab/domains/baselines.py

The bar is a **cross-validated bag-of-words classifier**, not a regex. A regex
written while looking at the generator scores whatever its author wants it to;
the first version of this file scored 100% on every slice because its patterns
were lifted from the answer key, which measured the author rather than the data.
A multinomial Naive Bayes fitted on one fold and tested on the other cannot be
tuned that way: it sees only word counts and the labels, so whatever it reaches
is genuinely available to a method that understands nothing.

Two controls, both per slice:

`lexical()` is the bar Jev has to clear. If Jev's accuracy on a slice sits
inside its interval, the slice measures vocabulary and cannot support a claim
about that slice.

`cue_leakage()` checks the manipulation. Difficulty is held fixed across slices,
so cues are drawn independently of the label and a classifier trained on the cue
sentences ALONE must sit at chance. Above chance means the cue is acting as a
second decisive element and the slices are not comparable.

`slices_are_comparable()` is the gate that issue #9's question depends on:
"does the correction survive a change of domain" only means something if domain
is what changed.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from jevlab.stats import wilson  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

SLICE_ORDER = [
    "code_security",
    "lab_safety",
    "contract_liability",
    "code_security_rare",
]

TOKEN_RE = re.compile(r"[a-z0-9_]+")

DATASET_NAME = "domains"
# Same contract as lab/tiers/baselines.py: bump only on an intentional
# rebuild; the content hash in dataset_version() catches silent edits.
DATASET_VERSION = "1.0.0"


def fingerprint(path: str | None = None) -> str:
    """SHA-256 hex of the dataset file, read as committed, byte for byte."""
    path = path or os.path.join(HERE, "dataset.jsonl")
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dataset_version(path: str | None = None) -> str:
    """Version string pinned to content: "<semver> sha256:<full hex>"."""
    return f"{DATASET_VERSION} sha256:{fingerprint(path)}"


def load(path: str | None = None) -> list:
    path = path or os.path.join(HERE, "dataset.jsonl")
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def tokens(text: str) -> list:
    return TOKEN_RE.findall(text.lower())


def _fit(rows: list, field: str):
    """Multinomial Naive Bayes over word counts, Laplace smoothed."""
    counts = {True: {}, False: {}}
    totals = {True: 0, False: 0}
    docs = {True: 0, False: 0}
    vocab = set()
    for row in rows:
        label = row["is_positive"]
        docs[label] += 1
        for tok in tokens(row[field]):
            counts[label][tok] = counts[label].get(tok, 0) + 1
            totals[label] += 1
            vocab.add(tok)
    n = len(rows)
    size = max(len(vocab), 1)

    def predict(text: str) -> bool:
        best, best_score = False, None
        for label in (True, False):
            if not docs[label]:
                continue
            score = math.log(docs[label] / n)
            for tok in tokens(text):
                score += math.log(
                    (counts[label].get(tok, 0) + 1) / (totals[label] + size)
                )
            if best_score is None or score > best_score:
                best, best_score = label, score
        return best

    return predict


def crossval(rows: list, field: str = "text") -> dict:
    """Two-fold, stratified by label.

    Stratified rather than split on item index: the generator assigns labels at
    regular index positions, so an index-parity split put every positive in one
    fold and every negative in the other. That trains a single-class model and
    scores 0.0%, which reads like a hard dataset and is really a broken split.
    """
    folds = [[], []]
    for label in (True, False):
        same = [r for r in rows if r["is_positive"] is label]
        for i, row in enumerate(same):
            folds[i % 2].append(row)
    hits = 0
    for train, test in ((folds[0], folds[1]), (folds[1], folds[0])):
        predict = _fit(train, field)
        hits += sum(1 for r in test if predict(r[field]) == r["is_positive"])
    lo, hi = wilson(hits, len(rows))
    return {"n": len(rows), "hits": hits, "accuracy": hits / len(rows), "ci95": (lo, hi)}


def lexical(rows: list) -> dict:
    """The bar: everything a bag of words can extract from the whole item."""
    return crossval(rows, "text")


def cue_leakage(rows: list) -> dict:
    """The manipulation check: the same classifier on the cue sentences alone."""
    stripped = [dict(r, cue_text=" ".join(r["cues"])) for r in rows]
    return crossval(stripped, "cue_text")


def majority(rows: list) -> dict:
    """Always predict the more common label. The floor any result must clear."""
    positives = sum(1 for r in rows if r["is_positive"])
    hits = max(positives, len(rows) - positives)
    lo, hi = wilson(hits, len(rows))
    return {"n": len(rows), "hits": hits, "accuracy": hits / len(rows), "ci95": (lo, hi)}


def slices_are_comparable(
    lex: dict, cues: dict, spread_tolerance: float = 0.15, cue_ceiling: float = 0.60
) -> bool:
    """Domain must be the only thing that moved between the balanced slices.

    Two conditions. The lexical bar sits at a similar height in each, so no
    slice is secretly easier. And the cue sentences alone stay near chance, so
    the texture is not carrying the label.
    """
    balanced = [s for s in SLICE_ORDER if not s.endswith("_rare")]
    heights = [lex[s]["accuracy"] for s in balanced]
    leaks = [cues[s]["accuracy"] for s in balanced]
    return (max(heights) - min(heights) <= spread_tolerance) and (
        max(leaks) <= cue_ceiling
    )


def main() -> int:
    rows = load()
    by_slice = {s: [r for r in rows if r["slice"] == s] for s in SLICE_ORDER}

    lex = {s: lexical(rs) for s, rs in by_slice.items()}
    cues = {s: cue_leakage(rs) for s, rs in by_slice.items()}
    floor = {s: majority(rs) for s, rs in by_slice.items()}

    header = (
        f"{'slice':<22} {'n':>4} {'majority':>9} {'cue-only':>22} {'bag of words':>22}"
    )
    print(header)
    print("-" * len(header))
    for s in SLICE_ORDER:
        print(
            f"{s:<22} {lex[s]['n']:>4} {floor[s]['accuracy']:>8.1%} "
            f"{cues[s]['accuracy']:>11.1%} "
            f"[{cues[s]['ci95'][0]:.2f},{cues[s]['ci95'][1]:.2f}] "
            f"{lex[s]['accuracy']:>11.1%} "
            f"[{lex[s]['ci95'][0]:.2f},{lex[s]['ci95'][1]:.2f}]"
        )

    balanced = [s for s in SLICE_ORDER if not s.endswith("_rare")]
    spread = max(lex[s]["accuracy"] for s in balanced) - min(
        lex[s]["accuracy"] for s in balanced
    )
    worst_leak = max(cues[s]["accuracy"] for s in balanced)
    ok = slices_are_comparable(lex, cues)
    print(f"\nlexical-bar spread across the three balanced slices: {spread:.1%}")
    print(f"worst cue-only accuracy: {worst_leak:.1%}")
    print(f"slices comparable: {ok}")
    print(
        "\nThe bag-of-words column is the bar. A Jev accuracy inside its interval\n"
        "on a slice measures vocabulary, not judgement, and cannot support a\n"
        "claim about transfer on that slice."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
