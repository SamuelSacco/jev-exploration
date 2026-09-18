# Jev: an evidence ledger

Tracking what is actually known about [TypeSafe's Jev](https://typesafe.ai), the "System
One" judgment API that returns typed probabilities instead of generated text. Started as a
two-day deep dive during launch week (Sept 2026); now maintained as a ledger of claims and
the evidence for them, including other people's benchmarks.

**Where the argument stands.** Jev is classifier-shaped and its interface is
reproducible with open models, so the mechanism is not the interesting part. Its bet
is that the probabilities are *calibrated*. We recomputed every public ECE from each
study's own data against the noise floor for its sample size
([working](analysis/external/)), then ran a controlled 800-item difficulty gradient
of our own ([findings](lab/tiers/FINDINGS.md)). What that shows:

- **The probabilities are not calibrated, at any difficulty.** ECE runs 2.1–2.5× its
  noise floor across all four tiers, including where accuracy is 97.5%.
- **But calibration does not degrade with difficulty either.** Decomposing the ECE
  rise shows it is entirely predictions relocating into the badly-calibrated middle,
  not the calibration curve getting worse. Jev carries one fixed distortion.
- **The shape is compression toward the middle** — overstating low probabilities,
  understating high ones. The same distortion appears in jev-spam-eval on 19,528 real
  emails. It is the opposite of jev-phishing-bench, which is overconfident throughout.
- **So the sign of the error, not the size of the ECE, decides whether you can
  threshold.** Underconfident here: p≥0.9 gave a 1.000 hit rate in every tier at
  21.5–32.5% coverage. Overconfident there: the same rule bought 73.9%.
- **The widely cited n=60 benchmark cannot measure calibration at all** — a perfect
  model scores ECE ≈0.045 at that size, which is the range it reports.

Practical upshot: treat Jev's output as a monotone score, not a probability, and fit
your own calibration map on a few hundred labelled cases. It should transfer across
difficulty, since the curve is stable. Whether it transfers across domains is the
next open question.

→ **[The ledger](docs/claims-audit.md)** — every claim, its status, and the evidence.

---

## The API in 60 seconds

One endpoint. That is the whole surface area:

```http
POST https://api.typesafe.ai/v1/systemone
Authorization: Bearer <API key>
Content-Type: application/json
```

```json
{
  "state": "Text, an object, or an array containing the relevant context",
  "model": "jev-latest",
  "questions": {
    "my_question_id": {
      "type": "noul | choice | score",
      "instructions": "The judgment to make",
      "criteria": {}
    }
  }
}
```

Three primitives:

| Primitive | Returns | Shape |
|---|---|---|
| Noul | P(yes) as a float | `{"type": "noul", "noul": 0.92}` |
| Choice | winner + distribution + confidence | `{"type": "choice", "choice": "technical", "probabilities": {...}, "confidence": 0.82}` |
| Score | position along ordered levels, may land between them | `{"type": "score", "score": 1.6, "legend": {...}, "probabilities": {...}, "confidence": 0.78}` |

Semantics worth knowing, verified on `jev-1.13.0`:

- Question IDs are yours and are echoed back. They are not sent to the model, and the model
  cannot pick an option you did not offer.
- Noul near 0.5 means yes and no are similarly probable, not "medium intensity". Noul has
  no separate confidence field.
- Confidence is how concentrated the distribution is. It is not a correctness estimate and
  not permission to act.
- State is the evidence, instructions are the judgment, criteria are the answer space. You
  are designing a measurement instrument, not writing a prompt.
- Code owns the workflow. Jev never generates text, calls your functions, or decides what
  happens next. Thresholds, routing and escalation live in your code.
- Errors: 401 bad key, 422 malformed question, 429/529 back off with exponential retries.
  Limits: 255 Choice options, ~32k input tokens. No published rate limits, SLA or uptime
  commitment.
- Pricing: $0.042 per million input tokens, output tokens free.

## What is in here

```
analysis/external/         re-analysis of other studies' published figures (#2)
docs/
  claims-audit.md          the ledger: every claim, status, evidence
  review-and-roadmap.md    audit of this repo's own methodology, and the plan
  thread.md                the original 24-post narrative (frozen snapshot)
tests/                     52 tests, no API key and no network required
ci/                        CI definition (see ci/README.md to enable it)
jevlab/
  client.py                the one HTTP client: retries, network floor, escalation
  stats.py                 ECE, reliability, Brier, Wilson/bootstrap, ECE noise floor
lab/
  baselines.py             non-AI baselines + Wilson intervals, no API key needed
  run_demos.py             triage + rerank demos, scored against ground truth
  runs/                    raw per-call JSONL, committed so numbers stay auditable
  negation.json            40 minimal pairs (n=80); lexical methods pinned at chance
  tiers/                   800-item difficulty gradient (#1) + FINDINGS.md, the flagship result
  run_tiers.py             batched runner for the gradient, per-tier calibration
  tickets.json             12 labelled support tickets + their criteria (see LABELS.md)
  LABELS.md                label decisions, versioned and dated
  rerank.json              retired (issue #5): word overlap scores 7/8 on it
  edge_payload.json        edge-case probe payload
  results-2026-09-16-legacy.json   the original run, kept as a non-reproducible record
skills/
  jev/                     minimal Jev CLI + skill notes
  typesafe-ai-SKILL.md     TypeSafe builder skill
jev_statement_verifier.py  extract-then-verify prototype
```

## Run it yourself

No API key needed:

```bash
pip install -e ".[dev]" && pytest   # the whole suite runs offline
python3 lab/baselines.py            # non-AI baselines on the bundled datasets
python3 analysis/external/run.py --base ~   # recompute other studies' ECEs
python3 lab/tiers/baselines.py      # difficulty-gradient controls
python3 lab/tiers/analyse.py        # re-derive the flagship result from raw responses
python3 lab/run_tiers.py --dry-run  # size the flagship experiment
```

With a key:

```bash
export TYPESAFE_API_KEY=ts-...
python3 skills/jev/bin/jev.py lab/edge_payload.json   # single raw call
python3 lab/run_demos.py                              # triage + negation, one pass
python3 lab/run_demos.py --repeat 3                   # three passes, variance reported
python3 lab/run_demos.py --dry-run                    # payloads only, no calls
python3 lab/run_tiers.py --repeat 3                    # the gradient experiment (#1)
python3 skills/jev/bin/jev.py --floor                 # network floor, no key needed
```

Everything is standard library only. Raw responses land in `lab/runs/*.jsonl` and the
summary in `lab/results.json`; the JSONL is committed, the summary is derived.

## A caveat about our own demos

The triage demo is n=12, and every result it produces has a 95% interval that overlaps
a trivial non-AI baseline on the same data (`python3 lab/baselines.py`). It shows what
the API shape is good for; it is not evidence about accuracy, and the ledger does not
cite it as such.

The rerank demo is retired: a word-overlap rule scored 7/8 on it, so it measured
nothing. Its replacement, the n=80 negation probe, is built so that no lexical method
can beat chance — the baseline measures 51.2% — which makes it the first dataset here
where a result could separate from its baseline at all.

[review-and-roadmap.md](docs/review-and-roadmap.md) has the full methodology critique.

## Contributing

The ledger is the point: if you have measured something, open a PR adding a row with a
citation. Any calibration figure needs n, the binning, the ECE, the simulated noise floor
for that sample size, the ratio between them, and coverage at whatever threshold is quoted
— `jevlab.stats.ece_with_floor` and `coverage_at` produce all of it.

Work in flight:

| Issue | Needs a key |
|---|---|
| [#7 Enable CI, pick a licence](../../issues/7) | no |

## Other work worth reading

[jev-benchmark](https://github.com/themsquared/jev-benchmark) ·
[jev-phishing-bench](https://github.com/anisselbd/jev-phishing-bench) ·
[jev-spam-eval](https://github.com/bitnovus/jev-spam-eval) ·
[jev-rerank-bench](https://github.com/anessbelbati/jev-rerank-bench) ·
[openjev](https://github.com/TheoLeeCJ/openjev) ·
[awesome-typesafe](https://github.com/Hawxy/awesome-typesafe)
