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

6. **One parameter corrects most of it, and fifty labels is a floor rather than a
   recommendation.** Platt's slope stays at 2.11–2.61 across tiers while the intercept
   swings −0.48 to +1.75 with the base rate. Transferring the slope and refitting the
   intercept on 50 labels cuts ECE 62% measured on held-out items. Below 30 labels the
   correction can leave calibration four times worse than doing nothing
   ([method](analysis/CALIBRATION-TRANSFER.md)).

7. **The probabilities are quantised to 0.01, and Choice and Score can return exactly
   0 or 1.** Nothing in a direct response says so. An exact 0 on the correct option
   cannot be repaired by any rescaling. Noul did not do it once in 2,580 answers, and
   every calibration result here is Noul.

8. **Batching is near-free and questions cannot see each other.** ~0.33 ms per extra
   question on ~1.4 s of fixed overhead, and a code word in one question's instructions
   scored 0.02 on a sibling question against 0.99 in the shared state
   ([method](lab/PROBES.md)).

9. **Circularity is not a constant.** Relabelling the gradient with Jev's own labels
   inflated its score by +0.005, against the +0.081 swing a reranking study measured.
   The difference is how much room the task leaves for two readings to differ, so a
   single discount factor for self-labelled benchmarks is the wrong instrument
   ([method](analysis/CIRCULARITY.md)).

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
  headtohead.py            scores the Jev vs local-4B battery, writes the memo
  response_shape.py        scores the endpoint and position probes
  transfer_domains.py      scores the cross-domain transfer experiment
  quantisation.py          numeric resolution of the API's returned values
  calibration_transfer.py  whether a fitted correction transfers
  calibration_set_size.py  how many labels the intercept refit needs
  provenance.py            which published figures have raw data behind them
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
  exp_headtohead.py        Jev against a local 4B, four arms
  exp_transfer.py          does the fitted correction survive a change of domain
  exp_response_shape.py    where exact 0/1 come from, and whether order matters
  domains/                 480 items in four non-email slices, labels committed
  PROBES.md                isolation, batching and Choice-vs-Noul results
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
python3 analysis/calibration_set_size.py   # label budget for the intercept refit
python3 analysis/provenance.py             # which figures are reproducible here
python3 analysis/external/run.py --base ~    # needs the other repos cloned
python3 analysis/sweep/audit.py      # audit external calibration figures
python3 analysis/circularity.py      # judge-circularity audit of B1/B2
python3 analysis/quantisation.py     # what resolution the API actually returns
python3 lab/domains/baselines.py     # cross-domain slices: the gate
python3 lab/exp_transfer.py --dry-run
python3 lab/exp_headtohead.py --dry-run
python3 lab/response_shape_items.py --check   # graded-evidence gate
python3 lab/exp_response_shape.py --dry-run
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
python3 lab/exp_transfer.py --repeat 3                # cross-domain transfer, 36 calls
python3 lab/exp_headtohead.py --repeat 3              # Jev vs a local 4B, 33 calls
python3 lab/exp_response_shape.py --repeat 3          # endpoints + position, 30 calls
python3 skills/jev/bin/jev.py --floor                 # network floor, no key needed
```

Runtime code is standard library only; `pytest` is the sole dev dependency. Raw
responses land in `lab/runs/*.jsonl` and are committed; derived summaries are not.

Every experiment resolves its sender through `jevlab.transport` and contains no
credential handling of its own, so an operator who holds the key elsewhere runs the
same files unmodified:

```bash
JEV_TRANSPORT=my_ops.jev:send python3 lab/exp_transfer.py --repeat 3
```

The callable takes `(state, questions, model)` and returns the raw response dict. The
head-to-head battery takes a second, `JEV_LOCAL_TRANSPORT`, taking a prompt string and
returning reply text; this repo ships no default for it and no code that can reach a
non-Jev endpoint.

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

Both the gradient and the negation probe are built from Noul questions, as the
cross-domain slices are. On one classification item, independent Nouls left 0.29 of the
probability mass on wrong labels where a single Choice left none
([method](lab/PROBES.md)). One item is not enough to act on, but if it holds at scale
those results measure a formulation as well as a model; `lab/exp_headtohead.py` carries
a `typed` arm to find out.

## Contributing

Measurements are welcome as pull requests adding a ledger row with its source. Any
calibration figure should carry n, the binning, the ECE, the simulated noise floor for
that sample size, the ratio between them, and coverage at any quoted threshold.
`jevlab.stats.ece_with_floor` and `coverage_at` produce all of it.

Open work: [#9](../../issues/9) (does the correction transfer across domains),
[#10](../../issues/10) (per-primitive sign of miscalibration, raised externally),
[#7](../../issues/7) (enable CI, choose a licence).

## Related work

[jev-benchmark](https://github.com/themsquared/jev-benchmark) ·
[jev-phishing-bench](https://github.com/anisselbd/jev-phishing-bench) ·
[jev-spam-eval](https://github.com/bitnovus/jev-spam-eval) ·
[jev-rerank-bench](https://github.com/anessbelbati/jev-rerank-bench) ·
[openjev](https://github.com/TheoLeeCJ/openjev) ·
[awesome-typesafe](https://github.com/Hawxy/awesome-typesafe)
