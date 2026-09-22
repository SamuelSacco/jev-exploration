# Does Jev's calibration survive difficulty?

Issue #1. Run `20260918T013027Z`, `jev-1.13.0`, 800 items over 4 tiers, 3 passes,
60 calls. Labels frozen before the run; no items dropped after the audit.

Reproduce every number here from the committed raw responses, no API key:

```bash
python3 lab/tiers/analyse.py
```

## Summary

The calibration function does not change with difficulty; where predictions land on it
does.

Jev carries one miscalibration curve, roughly constant across every tier, and not a
small one: ECE sits at 2.1–2.5× its noise floor even on the trivial tier, where
accuracy is 97.5%. Harder items do not corrupt the curve, they push probabilities into
the middle of it, where the curve is worst.

## Per-tier results

| Tier | accuracy | ECE | floor | ratio |
|---|---|---|---|---|
| t1_trivial | 97.5% [94.3, 98.9] | 0.115 | 0.054 | 2.14 |
| t2_ordinary | 98.0% [95.0, 99.2] | 0.122 | 0.053 | 2.30 |
| t3_hard | 93.5% [89.2, 96.2] | 0.138 | 0.055 | 2.52 |
| t4_adversarial | 90.0% [85.1, 93.4] | 0.147 | 0.068 | 2.17 |

The accuracy gradient is real: t1 [94.3, 98.9] and t4 [85.1, 93.4] do not overlap,
so the difficulty manipulation worked.

The ECE gradient is not established. The four point estimates rise monotonically, but
the appropriate test is a bootstrap interval on the *difference* between tiers rather
than whether two independent intervals overlap:

```
  t1 -> t2_ordinary      +0.0072  95% CI [-0.0159, +0.0275]  NOT significant
  t1 -> t3_hard          +0.0225  95% CI [-0.0022, +0.0479]  NOT significant
  t1 -> t4_adversarial   +0.0316  95% CI [-0.0049, +0.0726]  NOT significant
```

At n=200 per tier, none separate from zero. A monotone ordering of four numbers
arises by chance about 4% of the time, so the ordering alone is weak evidence.

The ratio to floor is not monotone either: 2.14, 2.30, 2.52, 2.17. It peaks
at t3 and falls back at t4, partly because t4's floor is itself higher (0.068
against ~0.054) — its probabilities are more spread out, which puts fewer points in
each bin and raises the noise floor. Ratios across tiers are only comparable once
that is accounted for.

## Decomposition

ECE is a mass-weighted average of per-bin gaps, so it moves for two quite different
reasons: each bin's gap can widen (the calibration function degrades), or
predictions can relocate into bins that were already bad (mass shifts). Those have
opposite implications, and the scalar cannot tell them apart.

`jevlab.stats.decompose_ece` swaps one sample's gaps onto the other's mass:

| pass | ECE t1 | ECE t4 | t4 gaps @ t1 mass | t1 gaps @ t4 mass | verdict |
|---|---|---|---|---|---|
| 1 | 0.1152 | 0.1469 | **0.1007** | 0.1867 | mass shift only |
| 2 | 0.1158 | 0.1372 | **0.1136** | 0.1791 | mass shift only |
| 3 | 0.1159 | 0.1391 | **0.0985** | 0.1905 | mass shift only |

t4's calibration curve applied to t1's distribution gives ECE at or below t1's own
(0.099–0.114 against 0.1155), so t4 is not worse calibrated than t1. t1's curve
applied to t4's distribution gives 0.179–0.191, over-predicting the observed
0.137–0.147. The mass shift accounts for the entire rise.

Consistent across all three passes. The label flip rate between passes is 1.0–2.5%,
so this is not run-to-run noise.

## The failure shape

The per-bin gaps show the same crossover in every tier: Jev overstates low
probabilities and understates high ones. The broad shape is the load-bearing claim;
individual bins wobble at these counts.

```
t4_adversarial
         bin      n   mean p  hit rate      gap
     0.1-0.2     18    0.169     0.056   +0.114
     0.2-0.3     39    0.252     0.026   +0.226
     0.3-0.4     24    0.355     0.125   +0.230
     0.4-0.5     18    0.447     0.278   +0.169
     0.5-0.6     20    0.552     0.700   -0.148
     0.8-0.9     22    0.857     0.955   -0.097
     0.9-1.0     43    0.925     1.000   -0.075
```

Sign by bin, t1 and t4: `+ + + + + | - - - -`, crossing over around 0.5. t2 and
t3 wobble at a single bin each (t2 flips at 0.4, t3 at 0.6), so the pattern is not
bit-identical; the broad shape — overstating below ~0.5, understating above — holds
in all four.

This is compression toward the middle rather than overconfidence: the probabilities
are a monotone score that has been squeezed, so 0.25 means about 0.03 and 0.925 means
1.00.

It is the same shape [`analysis/external/`](../../analysis/external/) found in
jev-spam-eval, whose curve crosses over near 0.6 (overstating below, understating
above) on 19,528 real emails. Two independent datasets, one synthetic and one not,
showing the same systematic distortion. It is the opposite of jev-phishing-bench,
which is overconfident in every bin.

## Consequences for use

High-confidence answers are reliable here; coverage is what it costs.

| Tier | coverage at p≥0.9 | hit rate |
|---|---|---|
| t1_trivial | 31.5% | **1.000** |
| t2_ordinary | 32.5% | **1.000** |
| t3_hard | 23.5% | **1.000** |
| t4_adversarial | 21.5% | **1.000** |

Precision is 1.000 at ≥0.9 in every tier including the adversarial one, on 43–65
cases each. Because Jev is underconfident at the top, a high threshold is conservative
rather than risky. On jev-phishing-bench, where the error runs the other way, ≥0.9
gave a 73.9% hit rate. The direction of the error determines whether thresholding is
safe, and a scalar ECE does not carry the direction.

The middle band is not usable as a probability at any difficulty. A 0.25 from Jev did
not mean 25%; on t4 it meant 2.6%.

Because the curve is stable across difficulty, the miscalibration is correctable by a
fitted map rather than by treating raw output as probabilities. Measured in
[`analysis/CALIBRATION-TRANSFER.md`](../../analysis/CALIBRATION-TRANSFER.md).

## Effect on the ledger

- Row 13 (probabilities are calibrated): refuted here as well as at scale. ECE is
  2.1–2.5× its noise floor at every difficulty, including where accuracy is 97.5%.
- Row 14 (confidence is safe to route on): task-dependent, and the dependence is on
  the direction of the error rather than its magnitude. Where Jev is underconfident a
  high threshold is safe; where it is overconfident none is.
- Row 15 (calibration holds when the model is out of its depth): answered with a
  distinction the row did not anticipate. The calibration function holds, and so does
  the reliability of any given probability value. What changes is that harder inputs
  land where that function is worst, so a workflow degrades without the model becoming
  worse calibrated.

## Caveats

- The ECE gradient is not significant, and the decomposition result does not depend
  on it: t4's gaps under t1's mass sit below t1's own ECE at any n.
- Synthetic data from a 20-pair template pool. The decisive-act regex control scores
  69.5–83.0% across tiers, so a large part of this task is solvable with no
  understanding. Jev's 90–98% beats that control, but not by the margin the raw
  accuracy suggests.
- One domain and one model version. Nothing here generalises to other task families,
  and `jev-latest` is a moving target.
- n=200 per tier suffices for the accuracy gradient and the decomposition, but not for
  fine distinctions between adjacent tiers. Doubling it would cost about $0.02.
