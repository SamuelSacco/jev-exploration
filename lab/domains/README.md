# Cross-domain slices for issue #9

480 items in four slices, labels committed before any call.

```bash
python3 lab/domains/generate.py    # rebuild; the committed file is its output
python3 lab/domains/baselines.py   # the gate: run this first
python3 lab/exp_transfer.py --dry-run
```

## What this is for

`analysis/CALIBRATION-TRANSFER.md` reports that Platt's slope sits at 2.11–2.61
across all four tiers of the e-mail gradient while the intercept swings −0.48 to
+1.75 with the slice's base rate, and concludes that the slope is a property of
the model and the intercept a property of the deployment. That conclusion is
what makes the recipe reusable, and everything behind it is e-mail legitimacy.

These slices change the subject matter and nothing else.

| slice | question | base rate |
|---|---|---|
| `code_security` | does this change introduce a security flaw? | 0.50 |
| `lab_safety` | does this step violate the written safety protocol? | 0.50 |
| `contract_liability` | does this clause expose the signer to uncapped liability? | 0.50 |
| `code_security_rare` | same items and domain as the first | 0.25 |

The fourth slice is the control for the decomposition itself. A stable slope
across three domains is also consistent with the slope just being stable, which
would say nothing about slope-versus-intercept. Holding the domain fixed and
moving only the base rate tests the actual claim: the intercept should move and
the slope should not.

## Construction

Copied from `lab/tiers/generate.py`, with the content swapped.

The label is chosen from a counter and the item is built to match, so it never
depends on anyone reading the finished text. Every item carries a decisive
element drawn from a pair that shares its topic and vocabulary with the other
side: parameterised SQL against string-formatted SQL, acid into water against
water into acid, a cap that covers all claims against one that covers contract
claims only. Difficulty is held at one cue per item, in every slice.

## The gate

`python3 lab/domains/baselines.py` exits non-zero if the slices stop being
comparable, and `lab/exp_transfer.py` refuses to spend anything when it does.

| slice | majority | cue-only | bag of words |
|---|---|---|---|
| `code_security` | 50.0% | 43.3% | 81.7% |
| `lab_safety` | 50.0% | 55.0% | 88.3% |
| `contract_liability` | 50.0% | 50.8% | 81.7% |
| `code_security_rare` | 75.0% | 70.8% | 86.7% |

The bag-of-words column is a two-fold cross-validated Naive Bayes over word
unigrams, and it is the bar. A Jev accuracy inside its interval on a slice
measures vocabulary, not judgement.

## Rejected designs

Both were caught by measuring the dataset before spending anything, which is the
only reason they are cheap enough to write down.

**Label-specific cue pools.** The first version drew cues from a
`cues_toward_positive` pool and a `cues_toward_negative` pool, mirroring the
gradient. A rule keyed on the cue vocabulary then scored 100% on every slice.
The gradient can do this because cue *direction* is its difficulty knob and it
reports the cue rule falling from 95.5% to 1.5% across tiers as the proof that
the manipulation happened. Here difficulty is held fixed, so a cue that tracks
the label is not texture, it is a second decisive element. Cues are now drawn
from one pool without reference to the label, and the cue-only classifier sits
at 43.3–55.0%.

**A regex baseline written while looking at the generator.** The first
`baselines.py` scored 100% on every slice because its patterns were lifted from
the answer key. That measures the author, not the data. The bar is now a
classifier fitted on one fold and tested on the other, which cannot be tuned
that way.

**An index-parity cross-validation split.** The generator assigns labels at
regular index positions, so splitting folds on index parity put every positive
in one fold and every negative in the other. The classifier then trained on a
single class and scored 0.0%, which reads like a very hard dataset and was a
broken split. The folds are stratified by label now, and
`test_crossval_folds_are_stratified` pins it.

## Limitation

These items were written by a language model, as the gradient's were. That is
the author bias specified in `analysis/CIRCULARITY.md` §3 and it is not resolved
here. What this experiment controls is the *comparison between domains*, which
shares the bias and so cannot be explained by it.
