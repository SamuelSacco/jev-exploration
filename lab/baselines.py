"""Cheap non-AI baselines for the bundled demo datasets, plus Wilson intervals.

The point of this file is to make the demos interpretable. "8/8 on rerank" is
only meaningful next to what a keyword heuristic scores on the same eight
passages, and only if the interval around 8/8 is printed rather than implied.

No API key and no network needed:

    python3 lab/baselines.py
"""
import json
import math
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))

# Urgency cues a support team would grep for before reaching for a model.
URGENCY_RE = re.compile(
    r"asap|urgent|immediately|right away|blocking|blocked|broken|outage|"
    r"down|crash|error|500|deadline|month-end",
    re.I,
)


def wilson(hits: int, n: int, z: float = 1.96) -> tuple:
    """95% Wilson score interval for a binomial proportion."""
    if n == 0:
        return (0.0, 1.0)
    p = hits / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


def report(label: str, hits: int, n: int) -> None:
    lo, hi = wilson(hits, n)
    print(f"{label:<34} {hits}/{n}  ({hits / n:.1%})  95% CI [{lo:.1%}, {hi:.1%}]")


def content_words(text: str) -> set:
    return {w for w in re.findall(r"[a-z]+", text.lower()) if len(w) > 3}


def rerank_baseline() -> None:
    rr = json.load(open(os.path.join(BASE, "rerank.json")))
    query_words = content_words(rr["query"])
    hits = sum(
        (len(query_words & content_words(p["text"])) >= 2) == p["relevant"]
        for p in rr["passages"]
    )
    report("rerank: word-overlap >=2", hits, len(rr["passages"]))


def triage_baselines() -> None:
    tickets = json.load(open(os.path.join(BASE, "tickets.json")))
    urgent_hits = sum(bool(URGENCY_RE.search(t["text"])) == t["urgent"] for t in tickets)
    report("urgency: keyword regex", urgent_hits, len(tickets))

    # Majority-class floor for department routing.
    counts = {}
    for t in tickets:
        counts[t["dept"]] = counts.get(t["dept"], 0) + 1
    majority = max(counts.values())
    report("department: majority class", majority, len(tickets))


def main() -> None:
    print("Non-AI baselines on the bundled datasets\n")
    triage_baselines()
    rerank_baseline()
    print(
        "\nCompare against the committed Jev run in results.json.\n"
        "Where a baseline's interval overlaps Jev's, the demo does not "
        "distinguish them at this sample size."
    )


if __name__ == "__main__":
    main()
