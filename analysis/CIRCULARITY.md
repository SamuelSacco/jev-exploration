# Judge-circularity audit of B1 and B2

Prompted by zhuyansen/jev-search-rerank-eval, which measured judge circularity in
a reranking eval: the reported advantage moved from +0.053 NDCG@10 under
Jev-authored relevance labels to −0.028 under LLM-authored labels. A swing of
0.081 and a sign change. Any benchmark where the model under test also produced
the labels carries that bias, unmeasured.

```bash
python3 analysis/circularity.py        # this audit, no credential needed
python3 lab/exp_circularity.py --dry-run
```

## Verdict

**B1 and B2 cannot carry this bias: PROVEN.** The model under test never touched
the labels. `lab/tiers/generate.py` assigns the label at line 12 from a counter
and builds the message text from it at line 18. The generator imports no HTTP
client and reads no model output. There is no path from Jev to the ground truth,
so the mechanism T69 measured is absent by construction rather than by argument.

**B2 is fragile to label error from any other source: NOTED.** Every item above
the 0.9 threshold is currently a hit, so each wrong label costs exactly one.
Three mislabelled items in t4, 1.5% of the tier, drop the hit rate below 0.95.
B2 is a statement about a 43-to-65 item bucket, not a law.

**B1 is not clearly sturdier than B2: CORRECTED.** An earlier version of this
file reported 8 adversarial flips, 4% of the tier. That was one pass of a
three-pass experiment reported as the result, and the search stepped by 2, which
rounded even that pass up from its true value of 7. Across the three passes the
break point is 2 to 8 flips, 1.0% to 4.0%, so the worst case is 1.0% against
B2's 1.5%. B1 remains robust to *realistic* label noise — random corruption at
10% overturns it in only 3 of 20 seeds — but the claim that it tolerated two and
a half times B2's corruption was an artefact of the reporting.

**The circularity premium on this benchmark is +0.005: the preregistration
predicting +0.05 is REFUTED.** Measured over 120 calls, and §4 explains why the
prediction was wrong and what that implies for benchmarks on less decidable
tasks.

**Residual exposure is author bias, not judge circularity: UNVERIFIABLE offline.**
The labels are clean but the *items* were written by a language model. That is a
different bias with a similar effect and it cannot be measured without real data.
Specified below.

## Why the requested experiment was re-posed

The request was to re-derive B1 and B2 under Jev-only, LLM-only and merged
labels, mirroring T69.

That design does not transfer. T69 has a latent quantity, "is this passage
relevant", that different judges estimate differently; swapping the judge
re-estimates the same thing, and the gap between estimates is the bias. The
difficulty gradient has no latent quantity to re-estimate. The generator picks
"phishing" or "legitimate" first and constructs a message to match, so a
relabeling pass would not produce a second estimate of the same truth. It would
produce a different dataset, and B1/B2 measured on it would not be comparable to
B1/B2 as published.

Running it anyway would produce three numbers that look like a circularity
measurement and are not one.

Two things were done instead: the provenance was established mechanically, and
the findings were stress-tested against label error from any cause.

## 1. Provenance

```
  generator            lab/tiers/generate.py
  label assigned       line 12
  text built from it   line 18
  label precedes text  True
  API imports          none
  reads model output   none
```

`test_labels_are_not_model_derived` pins this, and a companion test asserts the
checker is not vacuous by confirming it searches for the tokens that would appear
if someone later wired model output into the generator.

## 2. Sensitivity

Labels being clean does not make a finding robust. Both were corrupted
adversarially, flipping the outcomes that raise ECE most, which is the worst case:
an adversary who can see the model's answers and relabels to flatter or damage it.

**B2**, p≥0.9 gives a 1.000 hit rate:

| tier | items above 0.9 | wrong labels to fall below 0.95 | as a share of the tier |
|---|---|---|---|
| t1_trivial | 63 | 4 | 2.0% |
| t2_ordinary | 65 | 4 | 2.0% |
| t3_hard | 47 | 3 | 1.5% |
| t4_adversarial | 43 | 3 | 1.5% |

No search is needed; the budget is arithmetic, which is itself the finding.

**B1**, t4's gaps under t1's mass stay at or below t1's own ECE. Every pass of
the run, because the break point is not stable across them:

| pass | intact margin | flips to break | as a share of the tier |
|---|---|---|---|
| 0 | +0.0145 | 7 | 3.5% |
| 1 | +0.0022 | 2 | 1.0% |
| 2 | +0.0174 | 8 | 4.0% |

```
  random corruption 10%    broke 3/20 seeds
```

The intact margin is a difference between two ECEs, both of which move between
passes, and when it starts small — +0.0022 on pass 1 — a couple of flips close
it. So B1's budget is 1.0% of a tier in the worst case and 4.0% in the best,
against B2's 1.5%: comparably fragile, not sturdier.

What does survive is the distinction between adversarial and realistic noise. An
adversary who can see the model's answers needs 1% of a tier; random label error
at ten times that rate leaves the finding standing in 17 of 20 seeds.

This file previously reported "8 flips, 4.0%" here, from pass 0 alone, and a
search that stepped by 2 rounded even that pass up from its true value of 7.
Reporting one pass as the result is the error this repo corrects in other
people's work, so the correction is stated rather than quietly applied.

## 3. What this does not clear

The decisive pairs in `lab/tiers/components.json` were written by a language
model. The labels are not model-derived, but the text is. If model-written
phishing is unusually legible to models, accuracy on this gradient overstates
accuracy on real mail, and the overstatement would not show up anywhere in this
audit.

That is author bias rather than judge circularity. It is not measurable offline,
because it needs items produced by something other than a model.

The test: run the same question template over a real corpus and compare. The
PhishNChips set used by jev-phishing-bench is a reasonable target, with the
caveat that its bodies are themselves LLM-generated, so a fully clean test needs
genuinely human-written mail. A large accuracy gap between synthetic and real
items at matched difficulty is author bias; a small one bounds it.

## 4. The counterfactual, measured

Provenance settles whether *this* benchmark is circular. It does not say how
much circularity is worth in general, which is what decides how far to discount
benchmarks that did label their own task, including TypeSafe's dashboard.

`lab/exp_circularity.py` measured it directly, over the same 800 committed
items, in two regimes: **truth**, the generator's labels, which is what B1 and
B2 use, and **self**, labels elicited from Jev with deliberately different
wording from the scoring question, in separate requests. The circularity
premium is accuracy under self-labels minus accuracy under generator labels.

Written before the run: the premium is positive in every tier, largest on
t4_adversarial, and a premium above +0.05 overall is comparable to T69's 0.081.

Run 2026-09-20, 120 calls. **Reported, not reproducible from this
repository**: the raw responses were not returned here, so `lab/runs/` holds
nothing behind the table below and `python3 analysis/provenance.py` marks it
UNVERIFIABLE. Committing `lab/runs/*-circularity-*.jsonl` from that run fixes
it.

| tier | premium |
|---|---|
| t1_trivial | +0.015 |
| t2_ordinary | −0.005 |
| t3_hard | +0.015 |
| t4_adversarial | −0.005 |
| **mean** | **+0.005** |

**The preregistration is REFUTED, on every clause.** The premium is not
positive in every tier; it is negative in two. It is not largest on
t4_adversarial; it is smallest there, tied. And at +0.005 overall it is an order
of magnitude below the +0.05 threshold and sixteen times below T69's 0.081.

The reasoning behind the prediction was that a model agrees with itself more
than with the world, and most so where it is least accurate, because there is
more room to agree with its own mistakes. That is wrong here, and the reason it
is wrong is worth more than the prediction was. Self-agreement inflates a score
only when the labelling judgement and the scoring judgement are the *same*
judgement wearing different words. T69's judge re-estimated a genuinely latent
quantity, "is this passage relevant", where two readings can differ. The
gradient's items have a decisive element that settles the answer, so relabelling
is not a second opinion about something uncertain; it is the same reading of the
same fact. A model that gets an item wrong under the scoring wording tends to
get it wrong under the labelling wording too, and the errors cancel out of the
difference instead of compounding.

So circularity is not a constant to discount by. It scales with how much room
for disagreement the task leaves, which means a benchmark on an ambiguous task
carries far more of it than the +0.005 measured here, and quoting this number as
a general correction would be the same mistake in the other direction.

**For B1 and B2: the discount is ~zero**, on top of provenance already showing
the mechanism is absent by construction. That is two independent lines reaching
the same place, which is the only reason to state it with any confidence.

40 calls at default settings, about $0.008. `--dry-run` sizes it and prints the
prediction without a credential.

## Operating note

`lab/exp_circularity.py` contains no credential handling. It calls
`jevlab.transport.resolve_sender()`, which defaults to the repo's client but can
be replaced with `JEV_TRANSPORT=package.module:callable`. The replacement takes
`(state, questions, model)` and returns the raw response dict; whatever it does
about authentication is invisible to this repo.

```bash
JEV_TRANSPORT=my_ops.jev:send python3 lab/exp_circularity.py --repeat 3
```

Two tests enforce it: one strips docstrings and comments and asserts no
credential name appears in executable code, the other asserts the run log names
the transport in use without naming a secret.
