# Re-analysis of the published Jev calibration figures

Issue #2. Every public ECE reported for Jev, recomputed from the study's own
committed data, with the study's own binning, against the noise floor for that
sample size and binning.

Run it:

```bash
git clone --depth 1 https://github.com/themsquared/jev-benchmark
git clone --depth 1 https://github.com/anisselbd/jev-phishing-bench
git clone --depth 1 https://github.com/bitnovus/jev-spam-eval
python3 analysis/external/run.py --base . --json analysis/external/summary.json
```

`summary.json` in this directory is the committed output, from source repos as of
2026-09-18.

## Results

| Study | n | binning | accuracy | ECE | floor | ratio | verdict |
|---|---|---|---|---|---|---|---|
| jev-spam-eval `spam_structured_criteria` | 19,528 | 10 @ [0,1] | 98.3% | 0.0508 | 0.0039 | 13.0 | real |
| jev-spam-eval `spam_generic_criteria` | 19,528 | 10 @ [0,1] | 96.6% | 0.0556 | 0.0039 | 14.1 | real |
| jev-spam-eval `spam_structured_focus` | 19,528 | 10 @ [0,1] | 98.0% | 0.0594 | 0.0041 | 14.3 | real |
| jev-spam-eval `spam_plain` | 19,528 | 10 @ [0,1] | 96.0% | 0.0792 | 0.0045 | 17.8 | real |
| jev-phishing-bench P(phishing) | 2,000 | 10 @ [0,1] | 62.6% | 0.1701 | 0.0206 | 8.3 | real |
| jev-phishing-bench verdict confidence | 2,000 | 10 @ [0.5,1] | 62.6% | 0.1536 | 0.0209 | 7.3 | real |
| jev-benchmark `jev-latest` | 60 | 10 @ [0,1] | 91.7% | 0.0712 | 0.0456 | 1.6 | at the noise floor |
| jev-benchmark `jev-preview` | 60 | 10 @ [0,1] | 91.7% | 0.0505 | 0.0452 | 1.1 | at the noise floor |

All three published ECE figures reproduce exactly (0.0712, 0.0505, 0.1536), as do
the published accuracies. jev-spam-eval publishes no ECE, so its rows are computed here.

Ratio measures detectability rather than severity: a large n pushes the floor down, so
a mild miscalibration can carry a high ratio. The ratio says whether a study can speak
at all; ECE, Brier and the reliability curve say how bad the miscalibration is.

## What changed, and what it corrects

jev-benchmark cannot measure calibration in either direction. At n=60 with 10 bins a
perfectly calibrated model scores ECE ≈ 0.045, and both reported figures sit on top of
that. This is a limit of the sample size rather than a fault in the study: its own
`analyze.py` prints a bin-occupancy warning, and 50 of its 60 predictions land in a
single bin. The figure should not be cited as evidence of good calibration. Its
binning-independent finding, that none of the five misses came at confidence 1.000, is
unaffected and remains its strongest result.

jev-spam-eval is widely read as showing Jev is well calibrated. At n=19,528 it shows
the opposite in a specific place. The study reports its extremes, which are excellent:
0.1% spam below 0.1, 99.9% above 0.9. The middle is not.

```
  bin        n     mean_p  hit rate    gap
  0.00-0.10  8565   0.034     0.001   +0.033
  0.10-0.20  1160   0.131     0.022   +0.109
  0.20-0.30   456   0.243     0.064   +0.179
  0.30-0.40   255   0.350     0.067   +0.284
  0.40-0.50   258   0.445     0.171   +0.274
  0.50-0.60   209   0.543     0.388   +0.156
  0.60-0.70   141   0.655     0.745   -0.090
  0.70-0.80   227   0.755     0.907   -0.152
  0.80-0.90   640   0.854     0.972   -0.118
  0.90-1.00  7617   0.973     0.999   -0.026
```

The curve crosses over around 0.6: below it Jev overstates P(spam) by up to 0.28,
above it understates by up to 0.15. These are not probabilities you can threshold
on. They are a monotone score whose calibrated decision boundary happens to sit
near 0.6, not 0.5.

The middle is thin, holding 7.9% of the corpus, so this matters less than it looks.
It is also why reporting only the extremes looked fine, and why ECE over the whole
distribution is the more complete summary.

jev-phishing-bench is overconfident in every bin.

```
  bin (confidence)   n    mean_p  hit rate    gap
  0.50-0.55         154   0.524     0.513   +0.011
  0.60-0.65         179   0.621     0.447   +0.174
  0.85-0.90         199   0.876     0.588   +0.288
  0.90-0.95         287   0.921     0.606   +0.315
  0.95-1.00         329   0.971     0.854   +0.117
```

No band is safe to route on. At confidence ≥ 0.9 you cover 30.8% of cases at a
73.9% hit rate; at ≥ 0.95, 16.4% coverage at 85.4%. An "auto-accept above 0.9"
rule would be wrong roughly one time in four.

## Consequences for the hypothesis in #1

The earlier framing, that Jev's calibration tracks its accuracy, survives only weakly,
and the mechanism argues against a single scalar relationship:

- Spam, 98.3% accurate: ECE 0.051, sigmoid-shaped, miscalibrated in a thin middle
  band, well calibrated where most of the mass is.
- Phishing, 62.6% accurate: ECE 0.154, uniformly overconfident across the range.

Absolute ECE does move with accuracy across these two points, but the shape of the
error differs: a shifted decision boundary against systematic overconfidence. Two
points with two failure modes do not establish a trend. Issue #1 settles it, and
records the reliability curve per tier rather than only a scalar, since the scalar
hides which of the two is occurring.

## Method notes

- Bin edge convention changes the answer. jev-benchmark uses right-closed bins,
  `conf > lo and conf <= hi`. Left-closed bins give 0.0488 instead of 0.0712 on
  identical data: a plausible figure that is not theirs. Jev returns round values
  constantly, so edges are densely populated.
- Bin range changes the answer. Confidence for a binary decision lives in [0.5, 1] and
  jev-phishing-bench bins accordingly, while jev-benchmark bins over [0, 1]. On the
  same four predictions those schemes give ECE 0.05 and 0.29, so the two studies'
  headline figures were never directly comparable.
- Accuracy is not thresholded for a confidence study. The outcome is already
  correctness; thresholding at 0.5 turns 55/60 into 56/60.
- jev-phishing-bench does not commit per-email rows, so its pairs are rebuilt from
  the published bin tables. ECE reads only bin means and hit rates, so the
  reproduction is exact; the floor is marginally optimistic because within-bin
  spread is lost.
- jev-rerank-bench is not included. It measures nDCG@10 with its own paired
  bootstrap and publishes no probability-versus-outcome data, so there is no
  calibration figure to check.
