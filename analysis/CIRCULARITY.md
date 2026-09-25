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
the labels. `lab/tiers/generate.py` assigns the label at line 173 from a counter
and builds the message text from it at line 179. The generator imports no HTTP
client and reads no model output. There is no path from Jev to the ground truth,
so the mechanism T69 measured is absent by construction rather than by argument.

**B2 is fragile to label error from any other source: NOTED.** Every item above
the 0.9 threshold is currently a hit, so each wrong label costs exactly one.
Three mislabelled items in t4, 1.5% of the tier, drop the hit rate below 0.95.
B2 is a statement about a 43-to-65 item bucket, not a law.

**B1 is MORE fragile than B2: CORRECTED TWICE.** An adversary needs 1 flipped
label, 0.5% of a tier, against B2's 3 flips at 1.5%. This file has now said
three different things here, and the reason is worth more than the number:

| version | claim | why it was wrong |
|---|---|---|
| first | 8 flips, 4.0%, "two and a half times B2's budget" | one pass of three, and a search stepping by 2 that rounded 7 up to 8 |
| second | 2–8 flips, 1.0–4.0%, "comparably fragile" | all three passes, but one arbitrary tie-break in the greedy search |
| current | 1 flip, 0.5%, more fragile than B2 | minimum across passes *and* across tie-breaks |

At the first step of the greedy search, **twenty different flips raise ECE by
exactly the same amount**, and nineteen do at the second. "The" greedy answer
does not exist. Picking the lowest index is deterministic but not neutral: on
this data it is consistently the kindest option available to the adversary,
giving 10, 2 and 11 flips on the three passes against the 3, 1 and 3 an
adversary sampling the ties can reach.

That also settles a disagreement across three machines, which produced 7, 11 and
12 from the same committed code. Candidate ECEs that tie differ in the last bit
or two between interpreters, so an unrounded `>` picks a different flip on
Python 3.11 than on 3.12. Candidates are now rounded to ten places before being
compared and the tie-break is explicit, so the deterministic path reproduces
everywhere — and it is reported beside the sampled range rather than as the
answer.

**The 0.5% is an upper bound, not the minimum.** Greedy search over sampled
tie-breaks can miss a cheaper attack; it cannot invent one. The real adversarial
budget is at most 0.5% of a tier and may be smaller.

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
  label assigned       line 173
  text built from it   line 179
  label precedes text  True
  API imports          none
  reads model output   none
```

`test_labels_are_not_model_derived` pins this, and a companion test asserts the
checker is not vacuous by confirming it searches for the tokens that would appear
if someone later wired model output into the generator. The line numbers above are
machine-computed from the current source by `label_provenance()` and test-pinned, so they track the source if it moves instead of drifting like hand-copied numbers.

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

**B1**, t4's gaps under t1's mass stay at or below t1's own ECE. Every pass, and
every pass sampled over twenty resolutions of the greedy search's ties:

| pass | intact margin | adversary's best | tie-break range | lowest-index tie-break |
|---|---|---|---|---|
| 0 | +0.0145 | 3 flips (1.5%) | 3–9 | 10 |
| 1 | +0.0022 | 1 flip (0.5%) | 1–3 | 2 |
| 2 | +0.0174 | 3 flips (1.5%) | 3–10 | 11 |

```
  random corruption 10%    broke 3/20 seeds
```

The intact margin is a difference between two ECEs, both of which move between
passes, and on pass 1 it starts at +0.0022 — one flip closes it.

So B1's adversarial budget is **0.5% of a tier** against B2's 1.5%, and the
ordering in the first version of this file was backwards.

What does survive, and is the part worth keeping, is the distinction between
adversarial and realistic noise. An adversary who can see the model's answers
needs a single label. Random label error at twenty times that rate leaves the
finding standing in 17 of 20 seeds. B1 is fragile to an attacker and robust to
sloppiness, which are different threats and were being conflated.

`python3 analysis/circularity.py --tie-break-samples 20` reproduces all of it.

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

Run 2026-09-20, 120 calls. The raw responses were committed by PR #12 as
`lab/runs/20260921T150525Z-circularity-*.jsonl` (120 lines: 4 tiers × 2 regimes ×
3 passes × 5 batches), and the table below re-derives exactly from them
against the committed tier labels with mean-across-passes aggregation —
per-tier premiums +0.015/−0.005/+0.015/−0.005, mean +0.005. The "reported, not
reproducible" note that stood here predates the commit; `python3
analysis/provenance.py` marks this claim BACKED.

| tier | premium |
|---|---|
| t1_trivial | +0.015 |
| t2_ordinary | −0.005 |
| t3_hard | +0.015 |
| t4_adversarial | −0.005 |
| **mean** | **+0.005** |

**The preregistration is refuted on the overall clause**: at +0.005 it is an order
of magnitude below the +0.05 threshold and sixteen times below T69's 0.081. The
per-tier clauses fail only at noise level — t1 and t3 read +0.015, t2 and t4
−0.005, and t3's per-pass premiums (+0.015/+0.015/+0.020) never span zero but
never leave the noise band — so "positive in every tier" and "largest on
t4_adversarial" are unsettled, not refuted; the table supports ~zero everywhere.

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
