"""Non-AI controls for the difficulty-gradient dataset.

Two rules, both reported per tier, because they answer different questions.

`CUE_RE` keys on surface alarm vocabulary: urgency, threats, generic greetings.
It measures whether the difficulty manipulation actually happened: it should be
near-perfect on t1 and *below chance* on t4, where the cues point the wrong way.

`DECISIVE_RE` keys on the vocabulary of the decisive act. It measures how much of
the task is solvable without understanding anything, and is the figure any model
result has to be read against. jev-phishing-bench found a plain regex beating Jev's
best single signal on their data, so both controls are reported rather than only
the favourable one.

    python3 lab/tiers/baselines.py
"""
from __future__ import annotations

import json
import os
import re
import sys

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from jevlab.stats import wilson  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))

CUE_RE = re.compile(
    r"urgent|immediate|final notice|suspend|expires today|do not ignore|"
    r"within 24 hours|action required|unusual sign-in|"
    r"dear (user|valued|account|member)",
    re.I,
)

DECISIVE_RE = re.compile(
    r"password|credential|remit|routing number|bank account|authentication code|"
    r"sign in with|re-enter your|single sign-on|account \d{4}-\d{5}|sort code|"
    r"card number",
    re.I,
)

TIER_ORDER = ["t1_trivial", "t2_ordinary", "t3_hard", "t4_adversarial"]


def load(path: str | None = None) -> list:
    path = path or os.path.join(HERE, "dataset.jsonl")
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def score(rows: list, pattern: re.Pattern) -> dict:
    """Per-tier accuracy of a regex that predicts phishing when it matches."""
    out = {}
    for tier in TIER_ORDER:
        subset = [r for r in rows if r["tier"] == tier]
        if not subset:
            continue
        hits = sum(1 for r in subset if bool(pattern.search(r["text"])) == r["is_phishing"])
        lo, hi = wilson(hits, len(subset))
        out[tier] = {
            "hits": hits,
            "n": len(subset),
            "rate": round(hits / len(subset), 4),
            "ci95": [round(lo, 4), round(hi, 4)],
        }
    return out


def gradient_is_real(cue_scores: dict) -> bool:
    """The manipulation check. If the cue rule does not collapse from t1 to t4,
    the tiers are not actually different and the experiment is void."""
    if not {"t1_trivial", "t4_adversarial"} <= set(cue_scores):
        return False
    return (
        cue_scores["t1_trivial"]["rate"] > 0.85
        and cue_scores["t4_adversarial"]["rate"] < 0.35
    )


def main() -> int:
    rows = load()
    results = {"cue": score(rows, CUE_RE), "decisive": score(rows, DECISIVE_RE)}

    for name, label in (
        ("cue", "surface alarm cues (difficulty manipulation check)"),
        ("decisive", "decisive-act vocabulary (the number to read Jev against)"),
    ):
        print(f"\n{label}")
        for tier in TIER_ORDER:
            s = results[name][tier]
            lo, hi = s["ci95"]
            print(
                f"  {tier:<16} {s['hits']:>3}/{s['n']}  {s['rate']:6.1%}  "
                f"CI [{lo:.1%}, {hi:.1%}]"
            )

    ok = gradient_is_real(results["cue"])
    print(
        f"\nDifficulty manipulation: {'CONFIRMED' if ok else 'NOT CONFIRMED'}: "
        "the cue rule "
        + ("collapses across tiers as intended." if ok else "does NOT collapse; tiers are not distinct.")
    )
    print(
        "Majority class is 50% in every tier by construction, so chance is 50% "
        "throughout and the tiers are directly comparable."
    )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
