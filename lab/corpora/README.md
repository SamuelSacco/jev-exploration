# External corpora

Importers for two public datasets that other people's Jev results are quoted
on. The datasets themselves are **not** committed: this repo's only approved
network endpoint is Jev's, so nothing here downloads anything. Point an importer
at a copy you already have.

```bash
python3 lab/corpora/bbq.py --src ~/BBQ/data --out lab/corpora/bbq.jsonl
python3 lab/corpora/sms.py --src ~/SMSSpamCollection --out lab/corpora/sms.jsonl
python3 lab/corpora/bbq.py --self-test    # runs against the bundled fixture
```

Each importer ships a small hand-written fixture in `fixtures/` that matches the
real file format exactly, so the parsing, the slicing and the analysis are
tested without the corpus present, and a schema change in the upstream data
fails loudly instead of silently producing a different dataset.

## Reported figures these exist to check

Targets to reproduce, not ground truth. They were reported elsewhere, on
unstated binning and without noise floors, which is the first thing to redo.

**BBQ** (Bias Benchmark for QA; ambiguous and disambiguated contexts)

| reported | value |
|---|---|
| questions | 58,492 |
| accuracy | 97.28% |
| abstention on ambiguous contexts | 99.96% |
| unsupported guesses that were stereotype-directed | 12 of 13 |
| bias score, ambiguous / disambiguated | 0.04 / 0.34 |

**SMS** (SMS Spam Collection)

| reported | value |
|---|---|
| messages | 5,574 |
| accuracy | 98.73% |
| ECE | 2.47pp |
| messages at 100% confidence, all correct | 1,357 |
| false positives / false negatives | 54 / 17 |

## What to be careful about

**The 12-of-13 is a small-n claim.** 92.3% of thirteen carries a Wilson
interval of 66.7% to 98.6%. It is consistent with a strong stereotype direction
and with a mild one. `analysis/corpora.py` reports the interval
beside the count, and a direction claim from thirteen observations is NOTED,
never PROVEN.

**"All 1,357 at 100% confidence were correct" needs its coverage.** A
high-confidence bucket that is always right is only meaningful with the share of
the corpus it covers, which is the standard this repo's ledger already applies
to the community Enron figure. 1,357 of 5,574 is 24.4%, and that number belongs
next to the claim.

**A 2.47pp ECE needs its noise floor.** At n=5,574 the floor is small, so this
one probably survives, but it has not been reported against one and this repo
does not quote a calibration figure without it.

**Training overlap is unknown and probably real.** Both corpora are public,
widely mirrored, and predate the model. Neither number can separate judgement
from recall, and any figure from them is an upper bound on what the same model
would do on unseen data of the same shape. `lab/domains/` exists partly for
this reason.
