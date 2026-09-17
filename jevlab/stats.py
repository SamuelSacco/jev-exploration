"""Calibration and uncertainty statistics, standard library only.

Everything here works on the same input shape: a list of `(p, hit)` pairs, where
`p` is the probability the model assigned to an event and `hit` is whether that
event actually happened.

How to build the pairs from each primitive:

  Noul    (resp.noul(q), gold_label_is_true)
  Choice  (resp.confidence(q), resp.choice(q) == gold)
  Score   band the score, then treat it as Choice

The Choice form measures *confidence* calibration ("when it says 0.8, is it right
80% of the time?"), which is the operational question for routing, not full
multiclass calibration. Say which one you mean when you publish a number.

Binning is fixed at 10 equal-width bins by default because that is what the
published Jev benchmarks report, and ECE is not comparable across different
binning choices.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

DEFAULT_BINS = 10


def wilson(hits: int, n: int, z: float = 1.96) -> tuple:
    """Wilson score interval for a binomial proportion.

    Preferred over the normal approximation because the samples in this repo are
    small and often land at 100%, where the normal interval collapses to zero
    width and implies a certainty that is not there.
    """
    if n == 0:
        return (0.0, 1.0)
    p = hits / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, center - margin), min(1.0, center + margin))


@dataclass
class Bin:
    lo: float
    hi: float
    count: int
    mean_p: float
    hit_rate: float

    @property
    def gap(self) -> float:
        """Signed miscalibration. Positive means overconfident."""
        return self.mean_p - self.hit_rate


def reliability(pairs: list, bins: int = DEFAULT_BINS) -> list:
    """Group predictions into equal-width probability bins.

    Returns only non-empty bins. Empty bins contribute nothing to ECE and
    printing them as 0% hit rate invites misreading.
    """
    buckets: list = [[] for _ in range(bins)]
    for p, hit in pairs:
        idx = min(int(p * bins), bins - 1)
        buckets[idx].append((p, bool(hit)))

    out = []
    for i, bucket in enumerate(buckets):
        if not bucket:
            continue
        out.append(
            Bin(
                lo=i / bins,
                hi=(i + 1) / bins,
                count=len(bucket),
                mean_p=sum(p for p, _ in bucket) / len(bucket),
                hit_rate=sum(1 for _, h in bucket if h) / len(bucket),
            )
        )
    return out


def ece(pairs: list, bins: int = DEFAULT_BINS) -> float:
    """Expected Calibration Error: count-weighted mean |mean_p - hit_rate|."""
    if not pairs:
        return float("nan")
    n = len(pairs)
    return sum(b.count / n * abs(b.gap) for b in reliability(pairs, bins))


def mce(pairs: list, bins: int = DEFAULT_BINS) -> float:
    """Maximum Calibration Error: the worst single bin.

    Worth reporting next to ECE. A model can carry a respectable ECE while being
    badly wrong in one band, which is exactly the failure that matters if your
    routing threshold sits in that band.
    """
    gaps = [abs(b.gap) for b in reliability(pairs, bins)]
    return max(gaps) if gaps else float("nan")


def brier(pairs: list) -> float:
    """Mean squared error of the probabilities. Binning-independent, unlike ECE."""
    if not pairs:
        return float("nan")
    return sum((p - (1.0 if hit else 0.0)) ** 2 for p, hit in pairs) / len(pairs)


def accuracy(pairs: list, threshold: float = 0.5) -> float:
    if not pairs:
        return float("nan")
    return sum(1 for p, hit in pairs if (p >= threshold) == bool(hit)) / len(pairs)


def coverage_at(pairs: list, threshold: float) -> dict:
    """Accuracy among predictions above a confidence threshold, plus coverage.

    Accuracy at high confidence is meaningless without the fraction of cases that
    clear the bar. The community Enron result ("93.7% at >=95% confidence") is
    unreadable for exactly this reason.
    """
    kept = [(p, hit) for p, hit in pairs if p >= threshold]
    if not kept:
        return {"threshold": threshold, "coverage": 0.0, "n": 0, "hit_rate": float("nan")}
    hits = sum(1 for _, hit in kept if hit)
    lo, hi = wilson(hits, len(kept))
    return {
        "threshold": threshold,
        "coverage": len(kept) / len(pairs),
        "n": len(kept),
        "hit_rate": hits / len(kept),
        "ci": (lo, hi),
    }


def bootstrap_ci(
    pairs: list,
    statistic,
    resamples: int = 10_000,
    alpha: float = 0.05,
    seed: int = 0,
) -> tuple:
    """Percentile bootstrap interval for any statistic over the pairs.

    Seeded so a published interval can be reproduced exactly.
    """
    if not pairs:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    n = len(pairs)
    values = []
    for _ in range(resamples):
        sample = [pairs[rng.randrange(n)] for _ in range(n)]
        values.append(statistic(sample))
    values.sort()
    lo = values[int((alpha / 2) * resamples)]
    hi = values[min(resamples - 1, int((1 - alpha / 2) * resamples))]
    return (lo, hi)


def summarize(pairs: list, bins: int = DEFAULT_BINS, resamples: int = 2_000) -> dict:
    """The standard block of numbers to report for one task."""
    acc = accuracy(pairs)
    acc_lo, acc_hi = wilson(round(acc * len(pairs)), len(pairs)) if pairs else (0.0, 1.0)
    e = ece(pairs, bins)
    e_lo, e_hi = bootstrap_ci(pairs, lambda s: ece(s, bins), resamples=resamples)
    return {
        "n": len(pairs),
        "accuracy": acc,
        "accuracy_ci": (acc_lo, acc_hi),
        "ece": e,
        "ece_ci": (e_lo, e_hi),
        "mce": mce(pairs, bins),
        "brier": brier(pairs),
        "bins": bins,
        "reliability": [
            {
                "range": [round(b.lo, 2), round(b.hi, 2)],
                "n": b.count,
                "mean_p": round(b.mean_p, 4),
                "hit_rate": round(b.hit_rate, 4),
                "gap": round(b.gap, 4),
            }
            for b in reliability(pairs, bins)
        ],
    }


def format_reliability(pairs: list, bins: int = DEFAULT_BINS) -> str:
    """A reliability table for a terminal. Perfect calibration means gap ~ 0."""
    rows = reliability(pairs, bins)
    lines = [f"{'bin':>12}  {'n':>5}  {'mean p':>7}  {'hit rate':>8}  {'gap':>7}"]
    lines.append("-" * 46)
    for b in rows:
        lines.append(
            f"{b.lo:.1f}-{b.hi:.1f}".rjust(12)
            + f"  {b.count:5d}  {b.mean_p:7.3f}  {b.hit_rate:8.3f}  {b.gap:+7.3f}"
        )
    return "\n".join(lines)


def ece_noise_floor(
    probs: list,
    bins: int = DEFAULT_BINS,
    trials: int = 1_000,
    seed: int = 0,
) -> dict:
    """What ECE a *perfectly calibrated* model would score on a sample this size.

    ECE is biased upward at small n: with few points per bin, each bin's hit rate
    is a noisy estimate of its mean probability, and that noise shows up as
    apparent miscalibration. So an ECE figure means nothing until you know the
    floor it sits on, and the floor depends on both the sample size and how
    concentrated the predictions are.

    Pass the probabilities your run actually produced. Outcomes are then simulated
    from those same probabilities -- i.e. from a model that is calibrated by
    construction -- and the resulting ECE distribution is the null.

    Reference points, 10 bins, for Jev-like probabilities concentrated near 0 and 1:
    the floor is about 0.06 at n=60, 0.025 at n=500 and 0.012 at n=2000. Published
    Jev ECE figures should be read against those: 0.0505-0.0712 at n=60 sits at the
    floor and is uninformative, while 0.154 at n=2000 is an order of magnitude
    above it and is real.
    """
    if not probs:
        return {"n": 0, "mean": float("nan"), "p95": float("nan")}
    rng = random.Random(seed)
    n = len(probs)
    scores = []
    for _ in range(trials):
        sample = [probs[rng.randrange(n)] for _ in range(n)]
        scores.append(ece([(p, rng.random() < p) for p in sample], bins))
    scores.sort()
    return {
        "n": n,
        "trials": trials,
        "mean": sum(scores) / len(scores),
        "p50": scores[len(scores) // 2],
        "p95": scores[int(0.95 * len(scores))],
    }


def ece_with_floor(pairs: list, bins: int = DEFAULT_BINS, trials: int = 1_000) -> dict:
    """Observed ECE next to its noise floor, and the ratio between them.

    A ratio at or below 1 means the sample cannot distinguish this model from a
    perfectly calibrated one, whatever the raw ECE looks like.
    """
    observed = ece(pairs, bins)
    floor = ece_noise_floor([p for p, _ in pairs], bins=bins, trials=trials)
    ratio = observed / floor["mean"] if floor["mean"] else float("nan")
    return {
        "ece": observed,
        "floor_mean": floor["mean"],
        "floor_p95": floor["p95"],
        "ratio": ratio,
        "informative": bool(observed > floor["p95"]),
        "n": len(pairs),
    }
