# Difficulty gradient dataset

Issue #1. 800 binary items, one domain, one fixed question wording, four tiers
where the *only* intended difference is difficulty.

**Labels are committed and frozen.** `dataset.jsonl` and this file landed before any
API call was made against it. Do not change a label after seeing a result.

```bash
python3 lab/tiers/generate.py      # rebuild dataset.jsonl byte for byte
python3 lab/tiers/baselines.py     # non-AI controls per tier, no key needed
python3 lab/run_tiers.py --dry-run # size the run: 20 calls/pass, ~$0.007
python3 lab/run_tiers.py --repeat 3
```

## The question

Does Jev's calibration survive difficulty, or does it only hold where Jev is
already accurate? Calibration is worth paying for only if it survives — a model
well calibrated only where it is already right has given you nothing you could not
get by measuring accuracy, and its confidence would be least trustworthy exactly
where you most need it.

The answer is the **shape of ECE across tiers**, not any single value. Flat means
calibration is a real property. Rising means it tracks difficulty.

## Design

Two properties make the labels trustworthy.

**Ground truth is chosen before the message exists.** The generator picks phishing
or legitimate, then builds a message to match. No one reads a finished message and
decides what it is, so the adjudication problem from issue #6 cannot arise.

**Every message carries a decisive element matching its label, in every tier.**
Phishing messages always contain the malicious act: a payment redirected to a new
account, credentials requested at an off-domain host, an MFA code solicited by
reply. Legitimate ones always contain something that settles it the other way: no
sensitive ask, first-party destinations only, a verifiable internal route. The
decisive element is never removed or weakened, only surrounded.

Decisive elements come in **matched pairs** sharing a topic and vocabulary, so the
class cannot be read off the words:

| | phishing | legitimate |
|---|---|---|
| payroll_bank | "Confirm your bank account and routing number at `http://…`" | "You'll be asked to confirm your bank account in the usual portal — we never email a link for it" |
| mfa_code | "Reply with the six-digit code from your authenticator" | "You'll get a six-digit code when you sign in. Don't share it with anyone, including us" |
| remittance | "Our banking details changed; send payment to account 8842-11907" | "Our banking details have not changed. If you get a message saying they have, call Finance" |

Difficulty is the number of surrounding **cues** pointing against the label. Cues
are surface texture — urgency, alarming subjects, generic greetings, chatty
context — and never determine the answer.

| Tier | Cues with label | Cues against | What it reads like |
|---|---|---|---|
| `t1_trivial` | 2 | 0 | textbook phishing, obviously routine mail |
| `t2_ordinary` | 1 | 0 | realistic |
| `t3_hard` | 0 | 0 | decisive element standing alone, no atmosphere either way |
| `t4_adversarial` | 0 | 2 | calm specific phishing; alarming-sounding legitimate mail |

## The manipulation check

Difficulty is falsifiable rather than asserted. A regex on surface alarm
vocabulary should be near-perfect on t1 and *below chance* on t4:

| Tier | cue regex | decisive-act regex |
|---|---|---|
| t1_trivial | 95.5% [91.7, 97.6] | 83.0% [77.2, 87.6] |
| t2_ordinary | 88.0% [82.8, 91.8] | 75.5% [69.1, 80.9] |
| t3_hard | 49.0% [42.2, 55.9] | 73.5% [67.0, 79.1] |
| t4_adversarial | **1.5%** [0.5, 4.3] | 69.5% [62.8, 75.5] |

The cue rule collapses from 95.5% to 1.5%, well below the 50% chance rate that
holds in every tier (labels are balanced by construction). The difficulty
manipulation is real and steep. `baselines.py` exits non-zero if this ever stops
being true.

**The decisive-act regex is the number Jev has to be read against, and it is not
flattering.** It scores 69.5–83.0%, so a large part of this task is solvable with
no understanding at all. Jev beating chance here means nothing; beating ~70–83%
per tier is the bar. jev-phishing-bench found a plain regex beating Jev's best
single signal on real data, and reporting only the flattering control would repeat
exactly the mistake this repo exists to point out.

## Two design failures, recorded so they are not repeated

**The first version made t4 unlabelable.** It varied the decisive element by tier,
so a t4 "phishing" item was a message containing nothing malicious — a note about a
fire drill, labelled phishing. Those items were not hard, they were wrong, and any
model would have been penalised for being right. An experiment resting on
unknowable labels measures nothing. The fix is the decisive element being mandatory
in every tier.

**The second version was lexically solvable everywhere.** With unmatched decisive
pools, a regex scored 90/86/86/84.5% across the four tiers — essentially flat. A
flat regex baseline would have produced a flat Jev accuracy too, which would have
*looked* like "calibration holds across difficulty": a confident wrong answer to the
research question. The fix is the matched pairs above, which brought the control
down to 83→69.5% and, importantly, made it degrade.

Both were caught by measuring the baseline before spending a single call. That is
the argument for building the controls first.

## Known limitations

These bound what a result can claim and should travel with any number from it.

- **Synthetic.** Generated from 20 decisive pairs and a component inventory. Real
  phishing is more varied, and real legitimate mail is messier.
- **Template signature.** 20 pairs is a small pool. The residual 69.5% on t4 is
  lexical leakage, and a model that has seen this file could do better still.
- **"Adversarial" means adversarial to surface cues.** Whether t4 is adversarial to
  Jev is the open question, not an assumption.
- **One domain.** Email legitimacy, chosen for comparability with jev-spam-eval and
  jev-phishing-bench. Nothing here generalises to other task families.
- The dataset is written for this repo and appears in no public corpus, so training
  contamination is not a concern — unlike jev-spam-eval, whose corpora are public
  and old enough to sit in training data.

## Audit before running

The tiers that need human eyes are **t3 and t4**, because those are where a
mislabelled item is plausible and would silently corrupt the result.

```bash
python3 -c "
import json, random
rows=[json.loads(l) for l in open('lab/tiers/dataset.jsonl')]
random.seed(1)
for r in random.sample([x for x in rows if x['tier']=='t4_adversarial'], 10):
    print(r['id'], r['label'], r['decisive'], r['cues_against_label']); print(r['text']); print('---')
"
```

For each sampled item, one question: **would a careful reader, with no access to
the label, reach the committed answer from the text alone?** If not, that item is
broken — say which and it gets regenerated or dropped *before* any run, not after.

Worth checking specifically:

- t4 phishing items that read so calmly the malicious act gets lost — is it still
  actually there?
- t4 legitimate items so alarming they would be reported as phishing in practice —
  is the benign reading genuinely the only one?
- t3 items where the decisive element stands alone — is it unambiguous without any
  surrounding context?

## Output

`run_tiers.py` writes raw responses to `lab/runs/` before scoring and produces, per
tier: accuracy with a Wilson interval, ECE next to its noise floor, MCE, Brier,
coverage at 0.9 and 0.95, and the full reliability table.

The reliability table is the deliverable, not the scalar. The two public studies
large enough to measure calibration fail in different shapes — jev-spam-eval by a
shifted decision boundary, jev-phishing-bench by uniform overconfidence — and an
ECE number alone cannot tell those apart. See
[`analysis/external/`](../../analysis/external/).
