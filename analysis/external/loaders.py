"""Adapters onto other people's committed Jev results.

These are deliberately separate from `jevlab/`: they are shaped by five other
repositories' file formats and will rot when those change. Each loader returns
a Study carrying the (probability, outcome) pairs *and the binning that study
used*, because ECE is not comparable across binning schemes and reproducing
someone's number means reproducing their bins too.

Clone the sources next to this repo, or point the loaders elsewhere:

    git clone --depth 1 https://github.com/themsquared/jev-benchmark
    git clone --depth 1 https://github.com/anisselbd/jev-phishing-bench
    git clone --depth 1 https://github.com/bitnovus/jev-spam-eval
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


@dataclass
class Study:
    """One measurable slice of a published benchmark."""

    repo: str
    task: str
    variant: str
    pairs: list  # (probability, outcome) — see `quantity`
    bins: int
    bin_range: tuple
    quantity: str  # "confidence" (P(correct)) or "probability" (P(event))
    edge: str = "left"  # bin half-open convention; see jevlab.stats.reliability
    reported_ece: float | None = None  # what the study itself published, if any
    notes: str = ""
    provenance: str = "raw"  # "raw" rows, or "reconstructed" from published bins
    extra: dict = field(default_factory=dict)

    @property
    def name(self) -> str:
        return f"{self.repo}/{self.variant}"


def _read_jsonl(path: str) -> list:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def load_jev_benchmark(root: str) -> list:
    """Agent tool-call risk, n=60. Raw per-call rows with confidence and correct.

    analyze.py bins confidence into 10 equal bins over [0, 1], right-closed:
    `conf > lo and conf <= hi`, with the first bin also taking its lower edge.
    """
    studies = []
    reported = {"jev-latest": 0.0712, "jev-preview": 0.0505}
    for model, ece_value in reported.items():
        path = os.path.join(root, "results", f"jev-{model}.jsonl")
        if not os.path.exists(path):
            continue
        rows = _read_jsonl(path)
        pairs = [
            (float(r["confidence"]), bool(r["correct"]))
            for r in rows
            if isinstance(r.get("confidence"), (int, float))
        ]
        studies.append(
            Study(
                repo="jev-benchmark",
                task="agent tool-call risk",
                variant=model,
                pairs=pairs,
                bins=10,
                bin_range=(0.0, 1.0),
                edge="right",
                quantity="confidence",
                reported_ece=ece_value,
                provenance="raw",
                extra={
                    "difficulty": {
                        d: sum(1 for r in rows if r.get("difficulty") == d)
                        for d in ("clear", "ambiguous", "adversarial")
                    }
                },
            )
        )
    return studies


def load_phishing_bench(root: str) -> list:
    """Phishing, n=2,000. Per-email rows are not committed; the published
    reliability tables are, which is enough to reconstruct the ECE exactly.

    Two different tables live in metrics.json and they measure different things:
      ece_bins    confidence (P(correct)) over [0.5, 1.0] — what /jev/ece reports
      reliability P(phishing) over [0.0, 1.0]

    The reconstruction places each bin's n items at that bin's mean value, with
    round(accuracy x n) of them correct. ECE only reads bin means and hit rates,
    so the reproduced ECE is exact to rounding; the noise floor is very slightly
    optimistic because within-bin spread is lost.
    """
    path = os.path.join(root, "results", "metrics.json")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        metrics = json.load(fh)
    jev = metrics["jev"]

    def rebuild(table: list, value_key: str, rate_key: str) -> list:
        pairs = []
        for b in table:
            n = int(b["n"])
            hits = round(float(b[rate_key]) * n)
            value = float(b[value_key])
            pairs.extend([(value, True)] * hits)
            pairs.extend([(value, False)] * (n - hits))
        return pairs

    return [
        Study(
            repo="jev-phishing-bench",
            task="phishing email",
            variant="verdict confidence",
            pairs=rebuild(jev["ece_bins"], "confidence", "accuracy"),
            bins=len(jev["ece_bins"]),
            bin_range=(0.5, 1.0),
            quantity="confidence",
            reported_ece=jev.get("ece"),
            provenance="reconstructed",
            notes="Rebuilt from published ece_bins; within-bin spread is lost.",
            extra={"accuracy": jev.get("accuracy"), "auroc": jev.get("auroc")},
        ),
        Study(
            repo="jev-phishing-bench",
            task="phishing email",
            variant="P(phishing)",
            pairs=rebuild(jev["reliability"], "predicted", "observed"),
            bins=len(jev["reliability"]),
            bin_range=(0.0, 1.0),
            quantity="probability",
            reported_ece=None,
            provenance="reconstructed",
            notes="Their reliability table; they report no ECE for this quantity.",
        ),
    ]


def load_spam_eval(root: str, filename: str = "results_criteria_all.jsonl") -> list:
    """Spam, n=19,528 raw rows with Noul probabilities and gold labels.

    The study reports bin-level hit rates but never an ECE, so every number this
    produces is ours rather than a reproduction of theirs. Each `nouls` key is a
    different prompt variant over the same emails.
    """
    path = os.path.join(root, "results", filename)
    if not os.path.exists(path):
        return []
    rows = _read_jsonl(path)
    variants = sorted({k for r in rows for k in r.get("nouls", {})})
    studies = []
    for variant in variants:
        pairs = [
            (float(r["nouls"][variant]), r["label"] == "spam")
            for r in rows
            if variant in r.get("nouls", {})
        ]
        if not pairs:
            continue
        studies.append(
            Study(
                repo="jev-spam-eval",
                task="spam",
                variant=variant,
                pairs=pairs,
                bins=10,
                bin_range=(0.0, 1.0),
                quantity="probability",
                reported_ece=None,
                provenance="raw",
                notes="ECE computed by us; the study reports bin hit rates only.",
            )
        )
    return studies


SOURCES = {
    "jev-benchmark": ("themsquared/jev-benchmark", load_jev_benchmark),
    "jev-phishing-bench": ("anisselbd/jev-phishing-bench", load_phishing_bench),
    "jev-spam-eval": ("bitnovus/jev-spam-eval", load_spam_eval),
}

# jev-rerank-bench is deliberately absent: it measures ranking quality (nDCG@10,
# with its own paired bootstrap) and publishes no probability-versus-outcome
# data, so there is no calibration number to check.


def load_all(base: str) -> list:
    """Load every source found under `base`, skipping the ones not cloned."""
    studies = []
    for _, (path, loader) in SOURCES.items():
        root = os.path.join(base, path)
        if os.path.isdir(root):
            studies.extend(loader(root))
    return studies
