# Jev: an evidence ledger

What is actually known about [TypeSafe's Jev](https://typesafe.ai), the "System One"
judgment API that returns typed probabilities instead of generated text. Started as a
deep dive during launch week (September 2026), now maintained as a ledger of claims
and the evidence behind them, including other people's benchmarks.

→ **[The ledger](docs/claims-audit.md)**: every claim, its status, and its source.

## Findings

Jev is classifier-shaped, and its interface is reproducible with open models, so the
mechanism is not the interesting part. The claim worth testing is that its
probabilities are calibrated.

This repo recomputed every published Jev ECE from each study's own data against the
noise floor for its sample size ([method](analysis/external/)), then ran a controlled
800-item difficulty gradient ([method](lab/tiers/FINDINGS.md)) on `jev-1.13.0`.

1. **The probabilities are not calibrated.** ECE runs 2.1–2.5× its noise floor across
   all four difficulty tiers, including the tier where accuracy is 97.5%.

2. **Calibration does not degrade with difficulty.** ECE rises across the tiers, but
   decomposition attributes the whole rise to predictions relocating into the
   badly-calibrated middle, not to the calibration curve worsening.

3. **The distortion is compression toward the middle**: low probabilities overstated,
   high ones understated, crossing over near 0.5. The same shape appears in
   jev-spam-eval on 19,528 real emails, and is the opposite of jev-phishing-bench,
   which is overconfident throughout.

4. **The sign of the error decides whether thresholding is safe, not the size of the
   ECE.** Underconfident at the top here, so p≥0.9 gave a 1.000 hit rate in every
   tier at 21.5–32.5% coverage. On jev-phishing-bench, overconfident throughout, the
   same rule gave 73.9%.

5. **A widely cited n=60 benchmark cannot measure calibration in either direction.**
   A perfectly calibrated model scores ECE ≈0.045 at that sample size and binning,
   which is the range that benchmark reports.

6. **One parameter corrects most of it.** Fitted per tier, Platt's slope stays at
   2.11–2.61 while the intercept swings −0.48 to +1.75 with the slice's base rate.
   Transferring a whole map can make calibration worse; transferring the slope and
   refitting the intercept on ~50 labels cut ECE 74% and helped every case
   ([method](analysis/CALIBRATION-TRANSFER.md)).

In short: Jev returns a well-behaved monotone score carrying a stable distortion, not
a probability. Converting it into one costs a slope fitted once plus roughly fifty
labels per deployment. Whether that slope survives a change of domain or a retrain is
untested, and is tracked in [#9](../../issues/9).

## The API in 60 seconds

One endpoint:

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

Semantics, verified on `jev-1.13.0`:

- Question IDs are the caller's and are echoed back. They are not sent to the model,
  and the model cannot pick an option it was not offered.
- Noul near 0.5 means yes and no are similarly probable, not "medium intensity". Noul
  has no separate confidence field.
- Confidence measures how concentrated the distribution is. It is not a correctness
  estimate.
- State is the evidence, instructions are the judgment, criteria are the answer space.
- Code owns the workflow. Jev does not generate text, call functions, or decide what
  happens next. Thresholds, routing and escalation live in the caller's code.
- Errors: 401 bad key, 422 malformed question, 429/529 require backoff. Limits: 255
  Choice options, ~32k input tokens. No published rate limits, SLA or uptime
  commitment.
- Pricing: $0.042 per million input tokens, output tokens free.

## Layout

```
analysis/
  external/                published figures recomputed against their noise floors
  sweep/                   review of the external claim sweep, plus its audit tool
  circularity.py           judge-circularity audit of the gradient findings
  calibration_transfer.py  whether a fitted correction transfers
docs/
  claims-audit.md          the ledger
  thread.md                the original launch-week narrative (frozen)
jevlab/
  client.py                HTTP client: retries, network floor, escalation rules
  transport.py             seam for running under an operator's own credentials
  stats.py                 ECE, reliability, Brier, Wilson/bootstrap, ECE noise floor
  calibration.py           Platt and isotonic maps, slope transfer, intercept refit
lab/
  baselines.py             non-AI baselines with Wilson intervals
  exp_circularity.py       what self-labelling would have inflated the score by
  probe_structure.py       isolation, batching-scale and Choice-vs-Noul probes
  run_demos.py             triage and negation demos, scored against ground truth
  run_tiers.py             batched runner for the difficulty gradient
  runs/                    raw per-call JSONL, committed so results stay auditable
  tiers/                   the 800-item difficulty gradient and its analysis
  negation.json            40 minimal pairs (n=80); lexical methods pinned at chance
  tickets.json             12 labelled support tickets and their criteria
  LABELS.md                label decisions, versioned and dated
  rerank.json              retired; a word-overlap rule scores 7/8 on it
tests/                     offline test suite, no API key or network required
ci/                        CI definition, not yet enabled (see ci/README.md)
skills/                    Jev CLI and skill notes
jev_statement_verifier.py  extract-then-verify prototype
```

## Running it

Without an API key:

```bash
pip install -e ".[dev]" && pytest    # the suite runs entirely offline
python3 lab/baselines.py             # non-AI baselines on the bundled datasets
python3 lab/tiers/baselines.py       # difficulty-gradient controls
python3 lab/tiers/analyse.py         # re-derive the gradient result from raw responses
python3 analysis/calibration_transfer.py
python3 analysis/external/run.py --base ~    # needs the other repos cloned
python3 analysis/sweep/audit.py      # audit external calibration figures
python3 analysis/circularity.py      # judge-circularity audit of B1/B2
python3 lab/probe_structure.py --dry-run
python3 lab/run_tiers.py --dry-run   # size the gradient experiment
```

With a key:

```bash
export TYPESAFE_API_KEY=ts-...
python3 skills/jev/bin/jev.py lab/edge_payload.json   # one raw call
python3 lab/run_demos.py --repeat 3                   # triage + negation, variance reported
python3 lab/run_tiers.py --repeat 3                   # the difficulty gradient
python3 lab/probe_structure.py --repeat 3             # structural probes, 24 calls
python3 lab/exp_circularity.py --repeat 1             # circularity premium, 40 calls
python3 skills/jev/bin/jev.py --floor                 # network floor, no key needed
```

Runtime code is standard library only; `pytest` is the sole dev dependency. Raw
responses land in `lab/runs/*.jsonl` and are committed; derived summaries are not.

## Limits of the bundled demos

The triage demo is n=12, and every result it produces has a 95% interval overlapping a
trivial non-AI baseline on the same data (`python3 lab/baselines.py`). It demonstrates
the API shape. It is not evidence about accuracy, and the ledger does not cite it as
such.

The rerank demo is retired: a word-overlap rule scored 7/8 on it, so it could not
distinguish any model from keyword matching. Its replacement is the n=80 negation
probe, constructed so that no lexical method beats chance (measured: 51.2%).

The difficulty gradient is synthetic, generated from a 20-pair template pool. A regex
on the decisive-act vocabulary scores 69.5–83.0% across its tiers, so that, not
chance, is the bar any result there has to clear.

Both the gradient and the negation probe are built from Noul questions. An external
sweep reports that binary-per-item formulations leave much more probability on wrong
answers than a single Choice does; `lab/probe_structure.py` tests that directly, and if
it holds, those results measure a formulation as well as a model.

## Contributing

Measurements are welcome as pull requests adding a ledger row with its source. Any
calibration figure should carry n, the binning, the ECE, the simulated noise floor for
that sample size, the ratio between them, and coverage at any quoted threshold.
`jevlab.stats.ece_with_floor` and `coverage_at` produce all of it.

Open work: [#9](../../issues/9) (does the correction transfer across domains),
[#7](../../issues/7) (enable CI, choose a licence).

## Related work

[jev-benchmark](https://github.com/themsquared/jev-benchmark) ·
[jev-phishing-bench](https://github.com/anisselbd/jev-phishing-bench) ·
[jev-spam-eval](https://github.com/bitnovus/jev-spam-eval) ·
[jev-rerank-bench](https://github.com/anessbelbati/jev-rerank-bench) ·
[openjev](https://github.com/TheoLeeCJ/openjev) ·
[awesome-typesafe](https://github.com/Hawxy/awesome-typesafe)
