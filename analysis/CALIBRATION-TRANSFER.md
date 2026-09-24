# Does a fitted correction transfer?

Follow-up to [`lab/tiers/FINDINGS.md`](../lab/tiers/FINDINGS.md). No API key; every
number comes from the committed raw responses.

```bash
python3 analysis/calibration_transfer.py
```

## Summary

The slope transfers; the intercept does not. Transferring a whole two-parameter map
usually helps and occasionally hurts. Transferring the slope and spending about 50
labels on the intercept helped in every case measured, and helped more.

| approach | mean ECE over 12 transfers | worst single case |
|---|---|---|
| no correction | 0.1306 | 0.147 |
| full map fitted elsewhere | 0.0597 (−54%) | 0.184 (worse than no correction) |
| slope transferred, intercept refit on 50 labels | 0.0346 (−74%) | 0.045 |

Accuracy is unchanged throughout, since the maps are monotone and cannot reorder
anything. Brier improves alongside ECE (t1→t4: 0.1030 → 0.0805).

## Why the split

Fitting Platt independently on each tier shows the two parameters behaving
completely differently:

| tier | slope a | intercept b |
|---|---|---|
| t1_trivial | 2.27 | −0.36 |
| t2_ordinary | 2.43 | +0.60 |
| t3_hard | 2.55 | +1.75 |
| t4_adversarial | 2.15 | −0.30 |

The slope sits in a band of 2.11–2.61 across all four tiers and all three passes.
That is the squeeze: a property of the model, and the reusable part. A slope near 2.2
means Jev's log-odds are roughly half as extreme as they should be.

The intercept spans −0.48 to +1.75. It absorbs the slice's base rate and belongs to
the slice, not the model. t3 is the outlier: it has 58 predictions below 0.1 against
40 above 0.9, where the other tiers lean the other way, and the fit compensates with
a large positive shift.

That is why t3 → t4 is the one transfer that backfires, ECE 0.147 → 0.184, consistent
across all three passes (−25%, −24%, −27%). Carrying t3's base-rate offset onto t4
does more damage than the slope correction repairs.

## The recipe

```python
from jevlab.calibration import fit_platt, fit_platt_intercept, apply_map

slope = fit_platt(reference_pairs).a        # once, from any decent-sized slice
mapping = fit_platt_intercept(my_pairs[:50], slope)   # per deployment
calibrated = [mapping(p) for p in raw_probabilities]
```

One parameter, fitted on roughly fifty labelled examples, which is enough to pin a
base rate. `jevlab.calibration.transfer_slope` wraps both steps.

## Does it reach a different task?

The negation probe is a different question wording, a different construction, and
100% accurate, so it is a genuine out-of-domain test within email:

| slope fitted on | negation ECE before | after | reduction |
|---|---|---|---|
| t1_trivial | 0.065 | 0.021 | −67% |
| t2_ordinary | 0.065 | 0.011 | −83% |
| t3_hard | 0.065 | 0.007 | −89% |
| t4_adversarial | 0.065 | 0.022 | −66% |

Every one improves, including from t3, whose full map hurt t4. The starting ECE of
0.065 is already at that sample's noise floor (ratio 1.25 at n=80), so this is
suggestive rather than decisive: there was little to fix.

The negation run is 80/80 correct and still compressed, which shows the distortion is
not a symptom of being wrong. Jev returned 0.57 and 0.63 on items it classified
correctly every time.

## What this does not show

- One domain. Everything here is email legitimacy. Whether the slope holds on code
  review, moderation or triage is untested.
- One model version, `jev-1.13.0`. A retrain is exactly what would move a slope, so it
  should be re-fitted rather than hard-coded.
- The tiers are synthetic, from a 20-pair template pool. The negation transfer is the
  only out-of-construction evidence here, and its headroom was small.
- The tiers are one model version and one construction; a retrain is exactly what
  would move a slope, so it should be re-fitted rather than hard-coded.

## How many labels the intercept actually needs

`python3 analysis/calibration_set_size.py` sweeps the budget over all twelve
tier-to-tier transfers, 40 random refit sets per budget, scoring each on a fixed
held-out block of 100 items the refit never saw.

Two corrections to the figures above come out of it.

**The 74% was measured with the refit set inside the evaluation set.** The
method used `test[:50]` for the refit and then scored the map over all 200 items
of the tier, so a quarter of what was scored was what it had been fitted on.
Scored properly, on held-out items only, the same budget gives **61.7%**, not
the 69.1% the old method reports on this pass. The shortcut is worth about
0.010 of ECE, and it is the kind of thing this repo corrects in other people's
benchmarks.

**The mean flattens at about 75 labels; the tail is the reason to stop at 50.**

| budget | mean held-out ECE | worst single draw | as a multiple of doing nothing | transfers that can end up worse |
|---|---|---|---|---|
| 10 | 0.0646 | 0.4800 | 4.0x | 5 of 12 |
| 20 | 0.0579 | 0.2188 | 1.4x | 3 of 12 |
| 30 | 0.0516 | 0.1602 | 1.0x | 2 of 12 |
| 50 | 0.0512 | 0.1236 | 0.8x | 0 of 12 |
| 75 | 0.0475 | 0.1058 | 0.7x | 0 of 12 |
| 100 | 0.0481 | 0.1228 | 0.8x | 0 of 12 |

Averaged, the correction is nearly done at 30 labels. But an intercept fitted on
too few positives lands far from where it belongs and moves every probability
the wrong way, and at 10 labels the worst draw reaches **four times the
uncorrected ECE**. A deployment refits once and ships, so it is exposed to that
tail, not to the mean.

Fifty is the smallest budget at which no draw in this sweep left calibration
worse than applying no correction at all. So the recipe's original number
survives, for a reason that had not been measured: not because the correction is
finished there, but because that is where it stops being able to backfire.
Spending 75 buys a further 7% off the mean.

Below 30 labels, do not apply the correction. Uncorrected probabilities carry a
known distortion; a badly fitted intercept carries an unknown one.

Both figures are ECE on a fixed evaluation size on purpose. An earlier version of
this sweep scored on whatever the refit had not consumed, so the evaluation set
shrank as the budget grew, and the curve turned back up at 150 labels purely
because ECE is biased upward at small n — the same artefact this repo's noise
floor exists to catch, reproduced inside its own analysis.

## Where it leaves the ledger

Row 13 stays refuted: raw Jev probabilities are not calibrated at any difficulty. The
failure is systematic rather than erratic, though, and a one-parameter correction
recovers most of it. Jev returns a well-behaved monotone score carrying a stable
distortion, not a probability, and converting it into one is cheap given fifty
labels — and counterproductive given fewer than thirty.
