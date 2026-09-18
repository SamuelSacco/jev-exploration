"""Fit a correction onto Jev's probabilities. Standard library only.

The gradient experiment (lab/tiers/FINDINGS.md) found that Jev carries one
miscalibration curve that barely moves with difficulty: probabilities are
compressed toward the middle, overstating low values and understating high ones.
A stable distortion is a correctable one, so the question this module exists to
answer is whether a map fitted on one slice transfers to another.

Two standard methods, both monotone, so neither can change the ranking and
neither can change accuracy at a threshold that moves with the map:

  Platt      two parameters fitted on the log-odds. Smooth, extrapolates, cannot
             express a kink. Appropriate when the distortion looks like a
             consistent squeeze, which is what we observe.
  Isotonic   non-parametric, pool-adjacent-violators. Fits any monotone shape,
             including kinks, and overfits happily on small samples.

Fit on one set, evaluate on another. `evaluate_transfer` refuses to let you do
otherwise by accident.
"""
from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass, field

EPS = 1e-6


def _clip(p: float) -> float:
    return min(1.0 - EPS, max(EPS, p))


def _logit(p: float) -> float:
    p = _clip(p)
    return math.log(p / (1.0 - p))


def _sigmoid(z: float) -> float:
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


@dataclass
class PlattMap:
    """p' = sigmoid(a * logit(p) + b). a > 1 sharpens, a < 1 flattens."""

    a: float = 1.0
    b: float = 0.0

    def __call__(self, p: float) -> float:
        return _sigmoid(self.a * _logit(p) + self.b)

    @property
    def description(self) -> str:
        shape = "sharpens" if self.a > 1 else "flattens"
        return f"Platt(a={self.a:.3f}, b={self.b:+.3f}), {shape} the distribution"


@dataclass
class IsotonicMap:
    """Piecewise-linear monotone fit through pool-adjacent-violators blocks."""

    xs: list = field(default_factory=list)
    ys: list = field(default_factory=list)

    def __call__(self, p: float) -> float:
        if not self.xs:
            return p
        if p <= self.xs[0]:
            return self.ys[0]
        if p >= self.xs[-1]:
            return self.ys[-1]
        i = bisect_right(self.xs, p)
        x0, x1 = self.xs[i - 1], self.xs[i]
        y0, y1 = self.ys[i - 1], self.ys[i]
        if x1 == x0:
            return y1
        return y0 + (y1 - y0) * (p - x0) / (x1 - x0)

    @property
    def description(self) -> str:
        return f"Isotonic({len(self.xs)} knots)"


def fit_platt(pairs: list, iterations: int = 100, tol: float = 1e-9) -> PlattMap:
    """Newton's method on the log loss over two parameters.

    Targets are smoothed as Platt's original paper prescribes, which keeps the
    fit finite on a perfectly separable slice, as a 100%-accurate slice produces.
    """
    if not pairs:
        return PlattMap()
    n_pos = sum(1 for _, hit in pairs if hit)
    n_neg = len(pairs) - n_pos
    hi = (n_pos + 1.0) / (n_pos + 2.0) if n_pos else 1.0 / 3.0
    lo = 1.0 / (n_neg + 2.0) if n_neg else 1.0 / 3.0

    zs = [_logit(p) for p, _ in pairs]
    ts = [hi if hit else lo for _, hit in pairs]

    a, b = 1.0, 0.0
    for _ in range(iterations):
        g_a = g_b = h_aa = h_ab = h_bb = 0.0
        for z, t in zip(zs, ts):
            q = _sigmoid(a * z + b)
            d = q - t
            w = max(q * (1.0 - q), 1e-12)
            g_a += d * z
            g_b += d
            h_aa += w * z * z
            h_ab += w * z
            h_bb += w
        det = h_aa * h_bb - h_ab * h_ab
        if abs(det) < 1e-12:
            break
        step_a = (h_bb * g_a - h_ab * g_b) / det
        step_b = (h_aa * g_b - h_ab * g_a) / det
        a -= step_a
        b -= step_b
        if abs(step_a) < tol and abs(step_b) < tol:
            break
    return PlattMap(a=a, b=b)


def fit_isotonic(pairs: list) -> IsotonicMap:
    """Pool adjacent violators, then expose the block boundaries as knots."""
    if not pairs:
        return IsotonicMap()
    ordered = sorted(pairs, key=lambda item: item[0])
    # Each block: [sum of outcomes, count, min x, max x]
    blocks = [[1.0 if hit else 0.0, 1, p, p] for p, hit in ordered]
    i = 0
    while i < len(blocks) - 1:
        if blocks[i][0] / blocks[i][1] > blocks[i + 1][0] / blocks[i + 1][1]:
            blocks[i][0] += blocks[i + 1][0]
            blocks[i][1] += blocks[i + 1][1]
            blocks[i][3] = blocks[i + 1][3]
            del blocks[i + 1]
            if i:
                i -= 1  # the merge may have broken monotonicity behind us
        else:
            i += 1

    xs, ys = [], []
    for total, count, lo_x, hi_x in blocks:
        value = total / count
        for x in (lo_x, hi_x):
            if xs and x <= xs[-1]:
                continue
            xs.append(x)
            ys.append(value)
    return IsotonicMap(xs=xs, ys=ys)


def fit_platt_intercept(pairs: list, a: float, iterations: int = 200, tol: float = 1e-10) -> PlattMap:
    """Refit only the intercept, holding a transferred slope fixed.

    The two Platt parameters behave very differently across slices of Jev. The
    slope -- the squeeze -- is a property of the model and is stable: fitted
    independently on four difficulty tiers it lands between 2.11 and 2.61. The
    intercept absorbs the slice's base rate and is not stable at all: the same
    four tiers give -0.48 to +1.75.

    So transferring the whole map can hurt. Transferring the slope and spending
    a handful of labels on the intercept does not: across the twelve
    tier-to-tier transfers, the full map cut mean ECE 54% but made one pair
    worse, while slope-only with the intercept refit on 50 labels cut it 74% and
    improved every pair.

    One parameter, and it needs only enough labels to pin a base rate.
    """
    if not pairs:
        return PlattMap(a=a, b=0.0)
    n_pos = sum(1 for _, hit in pairs if hit)
    n_neg = len(pairs) - n_pos
    hi = (n_pos + 1.0) / (n_pos + 2.0) if n_pos else 1.0 / 3.0
    lo = 1.0 / (n_neg + 2.0) if n_neg else 1.0 / 3.0
    zs = [_logit(p) for p, _ in pairs]
    ts = [hi if hit else lo for _, hit in pairs]

    b = 0.0
    for _ in range(iterations):
        gradient = hessian = 0.0
        for z, t in zip(zs, ts):
            q = _sigmoid(a * z + b)
            gradient += q - t
            hessian += max(q * (1.0 - q), 1e-12)
        step = gradient / hessian
        b -= step
        if abs(step) < tol:
            break
    return PlattMap(a=a, b=b)


def transfer_slope(fit_pairs: list, calibration_pairs: list) -> PlattMap:
    """The recommended recipe: slope from a large slice, intercept from the
    deployment's own labels. See fit_platt_intercept for why."""
    return fit_platt_intercept(calibration_pairs, fit_platt(fit_pairs).a)


FITTERS = {"platt": fit_platt, "isotonic": fit_isotonic}


def apply_map(pairs: list, mapping) -> list:
    return [(mapping(p), hit) for p, hit in pairs]


def evaluate_transfer(
    fit_pairs: list,
    test_pairs: list,
    method: str = "platt",
    bins: int = 10,
    allow_same: bool = False,
) -> dict:
    """Fit on one slice, score on another. Reports before and after on the test set.

    Passing the same list for both is a silent way to report a fit's training
    error as if it were a result, so it has to be asked for explicitly.
    """
    if fit_pairs is test_pairs and not allow_same:
        raise ValueError(
            "fit and test are the same object; pass allow_same=True if you really "
            "want training-set numbers, and label them as such"
        )
    from jevlab.stats import brier, ece  # local import: stats imports nothing here

    mapping = FITTERS[method](fit_pairs)
    after = apply_map(test_pairs, mapping)

    def accuracy(pairs):
        return sum(1 for p, hit in pairs if (p >= 0.5) == hit) / len(pairs)

    before_ece, after_ece = ece(test_pairs, bins), ece(after, bins)
    return {
        "method": method,
        "map": mapping.description,
        "n_fit": len(fit_pairs),
        "n_test": len(test_pairs),
        "ece_before": before_ece,
        "ece_after": after_ece,
        "ece_reduction": (
            (before_ece - after_ece) / before_ece if before_ece else float("nan")
        ),
        "brier_before": brier(test_pairs),
        "brier_after": brier(after),
        "accuracy_before": accuracy(test_pairs),
        "accuracy_after": accuracy(after),
    }
