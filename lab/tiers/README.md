# Difficulty gradient dataset

Issue #1. 800 binary items, one domain, one fixed question wording, four tiers where the only
intended difference is difficulty.

Labels are committed and frozen: `dataset.jsonl` and this file landed before any API
call was made against them. Labels should not change after a result is seen.

```bash
python3 lab/tiers/generate.py      # rebuild dataset.jsonl byte for byte
python3 lab/tiers/baselines.py     # non-AI controls per tier, no key needed
python3 lab/run_tiers.py --dry-run # size the run: 20 calls/pass, ~$0.007
python3 lab/run_tiers.py --repeat 3
```

## The question

Does Jev's calibration survive difficulty, or does it hold only where Jev is already
accurate? Calibration is worth paying for only in the first case. A model calibrated
only where it is already right offers nothing beyond measuring accuracy directly, and
its confidence would be least trustworthy where it is most needed.

The answer is the shape of ECE across tiers rather than any single value. Flat means
calibration is a property of the model; rising means it tracks difficulty.

## Design

Two properties make the labels trustworthy.

Ground truth is chosen before the message exists: the generator picks phishing or
legitimate, then builds a message to match. Nobody reads a finished message and
decides what it is, so the adjudication problem from issue #6 cannot arise.

Every message carries a decisive element matching its label, in every tier. Phishing
messages always contain the malicious act: a payment redirected to a new account,
credentials requested at an off-domain host, an MFA code solicited by reply.
Legitimate ones always contain something that settles it the other way: no sensitive
ask, first-party destinations only, a verifiable internal route. The decisive element
is never removed or weakened, only surrounded.

Decisive elements come in matched pairs sharing a topic and vocabulary, so the class
cannot be read off the words:

| | phishing | legitimate |
|---|---|---|
| payroll_bank | "Confirm your bank account and routing number at `http://…`" | "You'll be asked to confirm your bank account in the usual portal — we never email a link for it" |
| mfa_code | "Reply with the six-digit code from your authenticator" | "You'll get a six-digit code when you sign in. Don't share it with anyone, including us" |
| remittance | "Our banking details changed; send payment to account 8842-11907" | "Our banking details have not changed. If you get a message saying they have, call Finance" |

Difficulty is the number of surrounding cues pointing against the label. Cues are
surface texture (urgency, alarming subjects, generic greetings, chatty context) and
never determine the answer.

| Tier | Cues with label | Cues against | What it reads like |
|---|---|---|---|
| `t1_trivial` | 2 | 0 | textbook phishing, obviously routine mail |
| `t2_ordinary` | 1 | 0 | realistic |
| `t3_hard` | 0 | 0 | decisive element standing alone, no atmosphere either way |
| `t4_adversarial` | 0 | 2 | calm specific phishing; alarming-sounding legitimate mail |

## The manipulation check

Difficulty is falsifiable rather than asserted: a regex on surface alarm vocabulary
should be near-perfect on t1 and below chance on t4.

| Tier | cue regex | decisive-act regex |
|---|---|---|
| t1_trivial | 95.5% [91.7, 97.6] | 83.0% [77.2, 87.6] |
| t2_ordinary | 88.0% [82.8, 91.8] | 75.5% [69.1, 80.9] |
| t3_hard | 49.0% [42.2, 55.9] | 73.5% [67.0, 79.1] |
| t4_adversarial | 1.5% [0.5, 4.3] | 69.5% [62.8, 75.5] |

The cue rule collapses from 95.5% to 1.5%, well below the 50% chance rate that
holds in every tier (labels are balanced by construction). The difficulty
manipulation is real and steep. `baselines.py` exits non-zero if this ever stops
being true.

The decisive-act regex is the figure any result has to be read against. It scores
69.5–83.0%, so a large part of this task is solvable without understanding anything;
beating chance means nothing, and the bar is roughly 70–83% per tier.
jev-phishing-bench found a plain regex beating Jev's best single signal on real data,
which is why both controls are reported rather than only the favourable one.

## Rejected designs

Two earlier constructions were discarded. Both are recorded because the current
design is a direct response to them.

Varying the decisive element by difficulty made t4 unlabelable. A t4 "phishing"
item came out as a note about a fire drill containing nothing malicious. Such items
are not hard, they are mislabelled, and a model would be penalised for answering
correctly. Hence the decisive element being mandatory in every tier.

Unmatched decisive pools made the task lexically solvable at every difficulty: a
regex scored 90/86/86/84.5% across the tiers, essentially flat. A flat control would
have produced flat model accuracy, which would resemble "calibration holds across
difficulty" without testing it. Hence the matched pairs above, which bring the control
to 83→69.5% and make it degrade.

Both were caught by measuring the controls before spending any calls.

## Known limitations

These bound what a result can claim and should travel with any number from it.

- Synthetic, generated from 20 decisive pairs and a component inventory. Real phishing
  is more varied and real legitimate mail is messier.
- Template signature: 20 pairs is a small pool. The residual 69.5% on t4 is lexical
  leakage, and a model that has seen this file could do better still.
- "Adversarial" here means adversarial to surface cues. Whether t4 is adversarial to
  the model is the question under test, not an assumption.
- One domain: email legitimacy, chosen for comparability with jev-spam-eval and
  jev-phishing-bench. Nothing here generalises to other task families.
- The dataset is written for this repo and appears in no public corpus, so training
  contamination is not a concern, unlike jev-spam-eval, whose corpora are public and
  old enough to sit in training data.

## Audit before running

t3 and t4 are the tiers worth reviewing by hand: those are where a mislabelled item is
plausible and would silently corrupt the result.

```bash
python3 -c "
import json, random
rows=[json.loads(l) for l in open('lab/tiers/dataset.jsonl')]
random.seed(1)
for r in random.sample([x for x in rows if x['tier']=='t4_adversarial'], 10):
    print(r['id'], r['label'], r['decisive'], r['cues_against_label']); print(r['text']); print('---')
"
```

For each sampled item the test is whether a careful reader, with no access to the
label, would reach the committed answer from the text alone. Items that fail should be
regenerated or dropped before a run, not after.

Cases to check specifically:

- t4 phishing items that read calmly enough for the malicious act to get lost. Is it
  still present?
- t4 legitimate items alarming enough to be reported as phishing in practice. Is the
  benign reading the only available one?
- t3 items where the decisive element stands alone. Is it unambiguous without
  surrounding context?

## Output

`run_tiers.py` writes raw responses to `lab/runs/` before scoring and produces, per
tier: accuracy with a Wilson interval, ECE next to its noise floor, MCE, Brier,
coverage at 0.9 and 0.95, and the full reliability table.

The reliability table matters more than the scalar. The two public studies large
enough to measure calibration fail in different shapes (jev-spam-eval by a shifted
decision boundary, jev-phishing-bench by uniform overconfidence), and an ECE figure
alone cannot distinguish them. See
[`analysis/external/`](../../analysis/external/).
