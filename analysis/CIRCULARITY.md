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

**B1 is sturdier: NOTED.** It takes 8 adversarially chosen flips, 4% of the tier,
to overturn the decomposition, and random corruption at 10% overturns it in only
3 of 20 seeds.

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

**B1**, t4's gaps under t1's mass stay at or below t1's own ECE:

```
  intact margin            +0.0145
  adversarial corruption   breaks at 8 flips (4.0% of the tier)
  random corruption 10%    broke 3/20 seeds
```

So B1 tolerates roughly two and a half times the corruption B2 does, and is
robust to realistic (random) label noise at a rate no careful labelling process
would reach.

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

## 4. The counterfactual worth measuring

Provenance settles whether *this* benchmark is circular. It does not say how much
circularity is worth in general, which is what decides how far to discount
benchmarks that did label their own task, including TypeSafe's dashboard.

`lab/exp_circularity.py` measures that directly. Over the same 800 committed
items, two regimes:

- **truth**: labels from the generator, which is what B1 and B2 use.
- **self**: labels elicited from Jev, with deliberately different wording from
  the scoring question, in separate requests.

The circularity premium is accuracy under self-labels minus accuracy under
generator labels. It is what this benchmark's score would have been inflated by,
had it been built the circular way.

Preregistered, before any run: the premium is positive in every tier, because a
model agrees with itself more than with the world, and largest on t4_adversarial,
where accuracy against truth is lowest and there is most room to agree with its
own mistakes. A premium above +0.05 overall is comparable to T69's 0.081 and
implies any Jev-labelled benchmark needs at least that discount.

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
