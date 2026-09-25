# Jev evidence ledger

One row per claim made about Jev, with its current status and the best evidence for or
against it. This file is meant to be edited as evidence appears; it is not a snapshot.

**Last updated:** 2026-09-21 · **Model version for runs in this repo:** `jev-1.13.0`

Status vocabulary:

| Status | Meaning |
|---|---|
| Verified | Independently reproduced, or checkable from the API contract itself |
| Overstated | Directionally true, but the headline figure is best-case |
| Refuted | False as stated, sometimes by TypeSafe's own footnotes |
| Contested | Measured more than once, with results that disagree |
| Unmeasured | No public evidence either way |

Provenance: rows marked *(measured here)* come from this repo's own live calls, listed
in [§5](#5-runs-in-this-repo). Everything else is attributed to the party that measured
it. Third-party figures are recorded as published, except where §6 states otherwise.

Rows marked *(raw data not in repo)* were run by the operator who holds the credential
and reported here without their raw responses, so they cannot be recomputed from this
repository. `python3 analysis/provenance.py` lists exactly which those are and what is
missing; `--strict` exits non-zero while any remain.

---

## The ledger

| # | Claim | Status | Evidence |
|---|---|---|---|
| 1 | One endpoint, `{state, model, questions}` in, `{model, answers, usage}` out | Verified | [§1](#1-the-api-contract) (measured here) |
| 2 | Independent questions batch into one call without a latency blowup | Verified | [§1](#1-the-api-contract) (measured here) |
| 3 | Output tokens are free; input is $0.042/MTok | Verified | [§1](#1-the-api-contract) (measured here) |
| 4 | 255-option Choice cap, ~32k token budget | Verified | TypeSafe docs |
| 5 | No published rate limits, SLA, or uptime commitment | Verified (absent) | TypeSafe docs |
| 6 | Returns honest uncertainty on unanswerable questions | Verified, small n | [§1](#1-the-api-contract) (measured here, n=4) |
| 7 | "193.6× faster / 444.6× cheaper" | Overstated | [§2](#2-speed-and-cost) |
| 8 | "Similar intelligence to frontier LLMs" | Overstated | [§3](#3-intelligence-and-accuracy) |
| 9 | 70–500 ms end-to-end | Fair as service time; not reachable on every client path | [§2](#2-speed-and-cost) |
| 10 | "Can't hallucinate" / 0% structured-output errors | Refuted | [§4](#4-refuted) |
| 11 | "New model class" as a scientific category | Unmeasured | [§4](#4-refuted) |
| 12 | An ordinary LLM can reproduce the interface | Verified | [§3](#3-intelligence-and-accuracy), openjev |
| 13 | Probabilities are calibrated | Refuted at scale | [§6](#6-the-open-question-calibration), both studies large enough to measure it find real miscalibration |
| 14 | Confidence is safe to route and escalate on | Depends on the sign of the error | [§6](#6-the-open-question-calibration), p≥0.9 gave 1.000 here, 0.739 on phishing |
| 15 | Calibration holds when the model is out of its depth | Yes, as a function, but harder inputs land where it is worst | [§6](#6-the-open-question-calibration), the 800-item gradient |
| 16 | Returned probabilities are full-precision floats | Refuted | [§1](#numeric-resolution), every value on a 0.01 grid across 71 direct responses (measured here) |
| 17 | A returned probability can be exactly 0 or 1, which no rescaling can repair | Verified for Choice and Score; no instance for Noul | [§1](#numeric-resolution) (measured here), [#10](../../issues/10) |
| 18 | Questions batched into one request cannot see each other's instructions | Verified (raw data not in repo) | [lab/PROBES.md](../lab/PROBES.md), 0.02 against 0.99; run by the operator, raw responses not committed, see [analysis/provenance.py](../analysis/provenance.py) |
| 19 | Batching is near-free: ~0.33 ms per extra question on ~1.4 s of overhead | Verified (raw data not in repo) | [lab/PROBES.md](../lab/PROBES.md); run by the operator, raw responses not committed |
| 20 | Choice and independent Nouls measure the same thing | Contested | [lab/PROBES.md](../lab/PROBES.md), Nouls left 0.29 on distractors where Choice left none, n=1 item; raw responses not committed |
| 21 | Jev's judgements are far more repeatable than an LLM judge's | Verified for repeatability, not for correctness | LangChain agent-eval, variance 1.49e-5 across 100 reps; but 5 frozen runs and one oracle, so agreement is 5/5 (95% CI 48–100%) and the LLM baselines' settings were unpinned |
| 22 | A benchmark whose labels the model supplied is inflated by ~0.08 | Refuted as a constant | [analysis/CIRCULARITY.md](../analysis/CIRCULARITY.md) §4, premium +0.005 here against T69's +0.081; it scales with how decidable the task is. Raw responses not committed |
| 23 | Fifty labels is enough to refit the intercept | Verified, and it is a floor not a plateau | [analysis/CALIBRATION-TRANSFER.md](../analysis/CALIBRATION-TRANSFER.md), 62% held-out reduction at 50; below 30 labels the worst draw is 4x the uncorrected ECE (measured here) |

---

## 1. The API contract

Verified across 7 live calls on `jev-1.13.0`, 2026-09-16.

One endpoint, `POST https://api.typesafe.ai/v1/systemone`, taking `{state, model,
questions}` and returning `{model, answers, usage}`. Three question types and no more.
Noul returns P(yes) as a float with no separate confidence field. Choice returns a winner,
the full distribution, and a confidence. Score returns a position along your ordered levels
that may land between them, plus a distribution and confidence.

Question IDs are yours and are echoed back rather than sent to the model, so the model
cannot select an option you did not offer. Confidence measures how concentrated the
distribution is. It is not a correctness estimate, which matters for rows 13 to 15.

Batching held up: 36 questions (12 tickets × 3 judgments) returned in one call, and 8
rerank questions in another. Adding questions did not blow up latency. Outputs were 89–997
tokens and are priced at zero, so the 12-ticket call cost roughly $0.00014 on 3,357 input
tokens. Treat that as one measurement, not a rate.

The documented limits are real and the undocumented ones are genuinely absent: the API
reference gives 429/529 plus backoff guidance and no numeric ceiling, no SLA, no uptime
commitment.

Four edge probes behaved the way the design intends. An unknowable question ("will the
user renew?") returned 0.49. A Choice forced between two options that were both wrong
returned a winner at 0.52 with confidence 0.04, so the distribution flagged the
garbage-in case even though the answer did not. Contradictory evidence returned 0.40. A
question unrelated to the supplied state was answered from world knowledge at 0.04. Four
probes prove nothing about calibration and are not counted as evidence for row 13. They establish that the failure modes are visible in the distribution, which is a
weaker and different claim.

### Numeric resolution

Every number the API returned in this repo's 281 committed responses sits on a 0.01
grid: 15,363 values, none off it. Nothing in a direct response declares that. The
API's top-level keys are `answers`, `model` and `usage`; the operator's transport
adds underscore-prefixed metadata (`_elapsed_s`, `_transport`) beside them.
Responses through Vercel AI Gateway carry `rounding: {probabilityDecimals: 2, scoreDecimals: 2}`
([#10](../../issues/10)), so the Gateway reports the rounding rather than causing it.
842 of 843 quantised distributions sum to exactly 1; one jev-1.13.0 choice vector
sums to 0.99, so the rounding residual is not always absorbed by a single entry.
A stray `0.8200000000000001` in the raw bodies is representation slack, on the grid.

The endpoints are not shared across primitives:

| Field | n | Exactly 0 | Exactly 1 | Observed range |
|---|---|---|---|---|
| `choice.probabilities` | 240 | 70.4% | 20.4% | 0.0–1.0 |
| `score.probabilities` | 180 | 47.2% | 16.7% | 0.0–1.0 |
| `score.score` | 60 | 41.7% | — | 0.0–2.0 |
| `choice.confidence` | 60 | 0% | 76.7% | 0.44–1.0 |
| `score.confidence` | 60 | 0% | 50.0% | 0.63–1.0 |
| `noul.noul` | 2,580 | 0% | 0% | 0.01–0.98 |

Zero endpoints in 2,580 Noul answers bounds the rate at 0.15% (Wilson, 95%), which is
an absence worth acting on rather than a gap in the data. Two consequences. A Choice
or Score can assign exactly 0 to the correct option, and no temperature or Platt map
can move it, because both act on the logit; row 6's "honest uncertainty" is a claim
about the distribution being *visible*, not about it being bounded away from 0.
And every calibration figure in this repo is Noul, measured on the one primitive that
appears to be clamped, so the correction in §6 is well defined on Noul and would need
a floor before it could be applied to the other two.

`python3 analysis/quantisation.py` re-derives all of it from `lab/runs/`, and
`tests/test_quantisation.py` fails if a future run breaks any of it.

## 2. Speed and cost

The multiplier is real and the headline is best-case. Official surfaces do not agree with
each other: 193.6×/444.6× on the homepage, 40–200× in the blog, 20–200× in the founder
thread, 100× in the launch video, while the homepage's own Doom demo (0.114 s vs 8.566 s)
works out to 75×. TypeSafe's own caveat is that the headlines sit "on the higher end of
real world gains."

Independent measurements, all against different comparators, which is why they spread:

| Source | Comparator | Speed | Cost |
|---|---|---|---|
| Near Here (n=50) | small LLMs, moderation | ~5× | 8.6× |
| Every | heavy-reasoning flagship | ~25× | ~580× |
| [jev-phishing-bench](https://github.com/anisselbd/jev-phishing-bench) (n=2,000) | Claude Haiku 4.5 | 2.9× (239 ms vs 687 ms p50) | 12× ($0.038 vs $0.462 per 1k emails) |
| [jev-rerank-bench](https://github.com/anessbelbati/jev-rerank-bench) (n=1,617) | Cohere Rerank 4 Pro | 2× (422 ms vs 844 ms) | 5.6× ($0.45 vs $2.51 per 1k queries) |

The two largest independent studies land at 2–3× speed and 5–12× cost against a serious
comparator. That is a good result and it is one to two orders of magnitude below the
headline.

On latency specifically, row 9 is about what the number describes rather than whether it is
true. The new harness measures in-process latency (no subprocess): 5 passes each of
triage and rerank from the test machine, p50 1.47 s and 1.48 s. The network floor, measured as
TCP + TLS to api.typesafe.ai, is p50 0.67 s from here, but that floor is dominated
by the egress proxy's CONNECT setup (~0.63 s), which is environment overhead rather
than distance. Implied service time from this VM is therefore ~0.8 s, an upper bound that
cannot judge TypeSafe's claim. (Caveat on the tooling: `measure_network_floor()` in
`jevlab/client.py` opens a direct socket, which fails behind a transparent proxy;
the floor above was measured through the proxy's CONNECT tunnel instead.)

jev-phishing-bench remains the cleanest single measurement: 239 ms p50 from France
against a measured 163 ms network floor, implying roughly 76 ms of service time.

Four independent direct-client measurements now land inside the band, collected by the
2026-09-18 external sweep (reviewed in [`analysis/sweep/`](../analysis/sweep/)): an
openchamber.dev survey median of 76 ms (n=333 user-reported figures), anisselbd's
239 ms p50, robipop22's 294 ms median, and chetaslua's 415 ms median over 1,191 calls.
The sweep's own CLI path also stays above 1.35 s, matching the finding here that a
subprocess-per-call harness measures its own overhead rather than the service.

The band is therefore reachable. The claim is fair as service time and misleading as an
end-to-end figure, since a client path can cost more than the model does. Selection
bias applies to the survey median, which the sweep flags: successful results are
published more readily.

## 3. Intelligence and accuracy

TypeSafe's own evals (evals.typesafe.ai, 711 cases over four workflows) put Jev at 67.8%
against GPT-5.6 Terra at 67.9%, GPT-5.6 Sol at 74.1% and Opus 5 at 73.1%, at $0.0004 per
case against $0.0304–$0.1761 and 0.4 s against 10–38 s. So Jev ties a mid-tier model and
trails the top reasoning models on their own benchmark. The reference answers are the
average of GPT-6 Astra and Fable 5.1 rather than ground truth, which TypeSafe
acknowledges. The site publishes summary statistics and examples, not full raw predictions.

Independent accuracy varies widely by task:

| Study | Task | n | Jev | Comparator |
|---|---|---|---|---|
| [jev-spam-eval](https://github.com/bitnovus/jev-spam-eval) | spam, in-distribution | 18,514 | 98.3% | TF-IDF logreg 98.4% |
| jev-spam-eval | spam, out-of-distribution | 2,876 | 98.6% | TF-IDF logreg 73.0% |
| [jev-benchmark](https://github.com/themsquared/jev-benchmark) | agent tool-call risk | 60 | 91.7% |, |
| [jev-rerank-bench](https://github.com/anessbelbati/jev-rerank-bench) | rerank, 14 datasets | 1,617 | 0.692 nDCG@10 | Cohere Pro 0.691 (tie) |
| [jev-phishing-bench](https://github.com/anisselbd/jev-phishing-bench) | phishing | 2,000 | 62.6% | Haiku 4.5 81.3%, regex 91.6% |
| [Verdict-open-jev](https://github.com/Heman10x-NGU/Verdict-open-jev) | typed decisions, 4 workflows | 2,000 | 68.0% | TF-IDF+LogReg 66.1% |
| gemanor/jev-code-review-benchmark | 4-rule Python review | 360 calls/model | 98% | Gemini Flash 100%, Fable 100% |

The spam result is the strongest published case for Jev: it matches a trained
classifier in-distribution and destroys it out-of-distribution, which is what zero-shot
semantic judgment should buy. The phishing result is the strongest case against: 62.6% accuracy and 43.2% recall, beaten by a regex on shorteners and domain
mismatch, with McNemar p < 0.0001 against Haiku.

Row 12 is settled. [openjev](https://github.com/TheoLeeCJ/openjev) reproduces the interface
by reading typed option probabilities directly from Qwen3.5-4B in a single forward pass,
reaching 0.845 modal agreement against 0.883 for published Jev on 102 aligned rows, at
5.21× the speed of generating and parsing a JSON array. The interface is therefore not the differentiator; whether the training is remains
open.

## 4. Refuted

**"Can't hallucinate."** False as stated, including by TypeSafe. The 0% chart carries the
footnote *"Our number is not empirical. Schema matching is guaranteed, thus we can
confidently add 0% into the plots."* Their docs say *"Typed output guarantees the
interface, not truth."* Jev cannot emit a malformed answer, but it can emit a confident wrong
valid one, and jev-phishing-bench measured it doing so 37.4% of the time. Constrained
decoding gives any model the same shape guarantee.

**"0% structured-output error rate."** Definitional, not measured, per the footnote above.

**"New model class."** No weights, no paper, no parameter count, no architecture details.
"System One Model" is a product category name. RLCD (Reinforcement Learning for Calibrated
Decisions) is a name plus a stated objective, epistemically honest probabilities, and
nothing further is public. Unfalsifiable as stated, so the useful question is not whether
the category is real but whether the calibration is, which is row 13.

## 5. Runs in this repo

Seven live calls on 2026-09-16, `jev-1.13.0`. These are demonstrations of the API shape,
not evidence of accuracy, and the ledger does not cite them for any accuracy claim: at
n=12 and n=8, every result has a 95% interval overlapping a trivial non-AI baseline on
the same data.

| Run | Setup | Result | Baseline on the same data |
|---|---|---|---|
| Triage | 12 tickets × 3 judgments, one call, 1.61 s | dept 10/12, urgency 12/12, frustration MAE 0.25 | majority class 5/12; urgency regex 9/12 |
| Rerank *(retired, #5)* | 8 passages, one Noul each | 8/8 | word-overlap ≥2: 7/8 |
| Statement verification | extract-then-verify, planted transposed digit | clean fields 0.99; planted error 0.01; truncation flagged | none |
| Edge probes | 4 unanswerable/contradictory questions | see [§1](#1-the-api-contract) | none |

The rerank demo is retired (issue #5). Its four distractors were a company
picnic, a revenue report, a sourdough recipe and an office lease, while every
relevant passage contained the literal string "PostgreSQL": a word-overlap rule
scores 7/8 on it, so the task had no discriminative power. For reranking numbers see
[jev-rerank-bench](https://github.com/anessbelbati/jev-rerank-bench), 14 datasets,
1,617 queries, 30 BM25 candidates each, bootstrap intervals, Jev at 0.692 nDCG@10
against Cohere Rerank 4 Pro at 0.691 for a fifth of the cost.

Its replacement is a negation probe ([`lab/negation.json`](../lab/negation.json),
n=80). Forty minimal pairs: a claim, a passage that asserts it, and a passage that
denies it differing by one word or short phrase. Because both halves share the same
vocabulary, 37 of the 40 pairs have identical content-word overlap with the claim -
any bag-of-words method is pinned at chance by construction, measured at 51.2%
[40.5%, 61.9%]. That makes it the first dataset in this repo where a Jev result
could actually separate from its baseline: at n=80, 85% would give [75.6%, 91.1%],
which does not overlap chance. Scoring also reports pairs *fully* resolved, since
answering yes to everything gets every supporting half right and resolves nothing.

Negation is also where the strongest independent evidence for Jev sits -
jev-rerank-bench found its clearest win there, 71% against Cohere's 67%, so this is
the slice worth owning rather than competing on general reranking at n=8.

Reproduce the baselines with `python3 lab/baselines.py` (no API key required). The
negation probe has not been run against the live API yet; that needs a key.

### Re-run on the new harness, 2026-09-17

Ten more calls (5 passes × 2 demos), model still `jev-1.13.0`, it has not moved
since 09-16. Raw responses are committed in `lab/runs/`; this is the first run the
ledger can cite at the response level.

| Demo | Result (pass 1 of 5) | Baseline, same data |
|---|---|---|
| Triage | dept 11/12 (v2 labels; 10/12 under v1), urgency 11/12, frustration MAE 0.25 | majority 4/12; urgency regex 9/12 |
| Rerank | 8/8 | word-overlap 7/8 |

The new information is the variance, which nobody has published for these tasks:

- Triage urgency: 1 of 12 questions flipped its label across the 5 passes
  (flip rate 8.3%), mean absolute spread 0.016, max 0.06. Urgency also moved
  *between* runs: 12/12 on 09-16, 11/12 on 09-17. A point estimate from one pass
  overstates what it knows.
- Rerank: 0 flips, mean spread 0.003, the 8/8 is stable, which is unsurprising
  given the distractors.
- All three calibration blocks printed at the noise floor (ECE 0.026–0.100 vs
  floors 0.044–0.143), exactly as the harness predicts for n=8–12. These demos
  cannot speak to calibration; §6 stands on the third-party studies.

Label version. Department scores above use label set v2
([`lab/LABELS.md`](../lab/LABELS.md), issue #6). Two tickets had no single
defensible home under v1 because the criteria overlapped: `technical` listed only
failure modes, leaving a feature request nowhere to go, and both `billing`
("pricing disputes") and `sales` ("quotes") claimed a pre-signature quote dispute.
Both criteria were tightened. One label moved as a result (t4 technical → other),
which raises the committed run from 10/12 to 11/12; the other was left standing as
a miss (t12 stays sales, Jev answered billing).

That correction moves a number in Jev's favour after the fact, which is the pattern
this ledger criticises elsewhere, so the reasoning in LABELS.md cites only ticket
text and criteria wording. Quote department scores with their label version. At
n=12 neither figure separates from the baseline: 11/12 is [65.1%, 97.9%].

Run it yourself: `python3 lab/run_demos.py --repeat 5` (~10 calls, under $0.01).

## 6. The open question: calibration

This is the claim the whole product rests on, and it is the row that changed most since
launch week. It is no longer unmeasured. It is contested, but less evenly than the raw
numbers suggest.

| Study | n | Accuracy | Calibration as reported |
|---|---|---|---|
| [jev-benchmark](https://github.com/themsquared/jev-benchmark) | 60 | 91.7% | ECE 0.0505 (preview) / 0.0712 (latest) |
| [jev-spam-eval](https://github.com/bitnovus/jev-spam-eval) | 18,514 | 98.3% | 0.1% spam below 0.1; 99.9% above 0.9; the 0.5–0.6 band overestimates at 38% |
| [jev-phishing-bench](https://github.com/anisselbd/jev-phishing-bench) | 2,000 | 62.6% | ECE 0.154, worse than Haiku 4.5 at 0.097 |

### Every published figure, recomputed

Issue #2 re-derived each of these from the study's own committed data, with the
study's own binning, against a simulated noise floor for that sample size. Full
working and the reliability curves: [`analysis/external/`](../analysis/external/).

| Study | n | binning | accuracy | ECE | floor | ratio |
|---|---|---|---|---|---|---|
| jev-spam-eval `structured_criteria` | 19,528 | 10 @ [0,1] | 98.3% | 0.0508 | 0.0039 | 13.0 |
| jev-phishing-bench P(phishing) | 2,000 | 10 @ [0,1] | 62.6% | 0.1701 | 0.0206 | 8.3 |
| jev-phishing-bench confidence | 2,000 | 10 @ [0.5,1] | 62.6% | 0.1536 | 0.0209 | 7.3 |
| jev-benchmark `jev-latest` | 60 | 10 @ [0,1] | 91.7% | 0.0712 | 0.0456 | 1.6 |
| jev-benchmark `jev-preview` | 60 | 10 @ [0,1] | 91.7% | 0.0505 | 0.0452 | 1.1 |

All three published ECEs reproduce exactly. Ratio is detectability, not severity:
a large n lowers the floor, so it says whether a study can speak, not how bad the
miscalibration is.

jev-benchmark cannot measure calibration in either direction. At n=60 with 10
bins a perfectly calibrated model scores ECE ≈ 0.045, and both reported figures sit
on top of that. Fifty of its sixty predictions land in one bin; its own `analyze.py`
warns about exactly this. The study's binding finding is the binning-independent
one, none of its five misses came at confidence 1.000, and that stands.

**jev-spam-eval, usually cited as the evidence Jev is well calibrated, shows real
miscalibration once the middle is included.** Its reported extremes are genuinely
excellent (0.1% spam below 0.1, 99.9% above 0.9). But the curve crosses over around
0.6: below that Jev overstates P(spam) by up to 0.28, above it understates by up to
0.15. Those mid-range numbers are not thresholdable probabilities, they are a
monotone score whose calibrated boundary sits near 0.6. It matters less than it
sounds, bins 0.2–0.8 hold 7.9% of the corpus, which is precisely why reporting
only the extremes looked clean.

jev-phishing-bench is overconfident in every bin, worst at 0.85–0.95 where
stated confidence ~0.90 buys a 60% hit rate. At confidence ≥ 0.9: 30.8% coverage,
73.9% hit rate. There is no threshold at which its confidence is safe to route on,
which is the sharpest evidence yet against row 14.

### A third independent calibration figure

[Verdict-open-jev](https://github.com/Heman10x-NGU/Verdict-open-jev) reports Jev at ECE
0.144 over 2,000 typed decisions on four enterprise workflows, against a TF-IDF logistic
regression at ECE 0.0207 with comparable accuracy (68.0% against 66.1%). That sits
beside jev-phishing-bench's 0.154 and supports the reading above: calibration is
task-dependent, and worse on realistic tasks than on synthetic verification. A trivial
trained baseline calibrating seven times better than Jev at the same accuracy is the
sharper half of that result.

Caveat, flagged by the sweep that surfaced it: the Jev row may be derived from
TypeSafe's published dashboard rather than measured live, so the provenance of the
0.144 is unclear. It is recorded here as a third datapoint rather than a replication.

### The difficulty gradient: the calibration function does not track difficulty

Issue #1, run `20260918T013027Z` on `jev-1.13.0`: 800 items over four difficulty
tiers, one domain, one fixed question wording, labels frozen before the run, three
passes. Full write-up and caveats: [`lab/tiers/FINDINGS.md`](../lab/tiers/FINDINGS.md);
re-derive it from the committed raw responses with `python3 lab/tiers/analyse.py`.

| Tier | accuracy | ECE | floor | ratio | coverage at p≥0.9 | hit rate |
|---|---|---|---|---|---|---|
| t1_trivial | 97.5% [94.3, 98.9] | 0.115 | 0.054 | 2.14 | 31.5% | 1.000 |
| t2_ordinary | 98.0% [95.0, 99.2] | 0.122 | 0.053 | 2.30 | 32.5% | 1.000 |
| t3_hard | 93.5% [89.2, 96.2] | 0.138 | 0.055 | 2.52 | 23.5% | 1.000 |
| t4_adversarial | 90.0% [85.1, 93.4] | 0.147 | 0.068 | 2.17 | 21.5% | 1.000 |

The accuracy gradient is real: the t1 and t4 intervals do not overlap. **The ECE
gradient is not.** The point estimates rise monotonically, but a bootstrap interval
on the *difference*, the correct test, rather than checking whether two independent
intervals overlap, includes zero at every step, and the ratio to floor is not
monotone either (it peaks at t3 and falls back at t4, whose floor is itself higher).

Decomposing the change settles what the scalar cannot. ECE moves either because each
bin's gap widened or because predictions relocated into bins that were already bad;
`jevlab.stats.decompose_ece` separates the two by swapping one sample's gaps onto the
other's mass. Applying t4's calibration curve to t1's distribution gives ECE 0.099
–0.114 across the three passes, at or *below* t1's own 0.1155. **t4 is not worse
calibrated than t1.** Applying t1's curve to t4's distribution gives 0.179–0.191,
which over-explains the observed rise. The whole movement is mass, in every pass.

So Jev carries one miscalibration curve that is roughly invariant to difficulty, and
it is not small: ECE sits at 2.1–2.5× its noise floor even where accuracy is 97.5%.
Harder inputs do not corrupt the curve, they push probabilities into the middle of
it, which is where it is worst.

The shape is compression toward the middle in every tier: Jev overstates low
probabilities and understates high ones, crossing over near 0.5. Individual bins
wobble (t2 flips sign at 0.4, t3 at 0.6); the broad shape, not the exact bin
pattern, is the load-bearing claim. On
t4 a stated 0.25 meant 2.6% and a stated 0.925 meant 100%. That is the same
distortion [`analysis/external/`](../analysis/external/) found in jev-spam-eval on
19,528 real emails, where the crossover sits near 0.6, two independent datasets, one
synthetic and one not, with the same systematic squeeze. It is the opposite of
jev-phishing-bench, which is overconfident in every bin.

Which decides the practical question. Because Jev is *under*confident at the top
here, a high threshold is conservative: p≥0.9 gave a 1.000 hit rate in all four
tiers, at 21.5–32.5% coverage. Where Jev is overconfident instead, the same rule
bought 73.9%. **The sign of the error, not the size of the ECE, determines whether
thresholding is safe**, and a scalar ECE does not carry the sign.

The middle band is unusable as a probability at any difficulty. But because the curve
is stable, the miscalibration is correctable: fit an isotonic or Platt map on a few
hundred labelled cases and apply it, rather than reading raw Jev output as
probabilities. Whether such a map transfers across domains is untested and is the
obvious next experiment.

### The negation probe, and a third sighting of the same curve

Run `20260918T014148Z`, 80 items: 80/80 correct, 40/40 pairs fully resolved,
against a word-overlap baseline pinned at chance by construction (41/80). ECE 0.065
against a floor of 0.052, ratio 1.25, at the noise floor, so this sample cannot
speak to calibration on its own.

What it does show is that the compression is not a symptom of being wrong. At 100%
accuracy Jev still returned 0.57 and 0.63 on items it got right every time, and the
gap pattern is the familiar one: positive below 0.5, negative above. Three datasets
now, the tiers, jev-spam-eval's 19,528 real emails, and this, carry the same
distortion.

### The correction transfers, in one parameter

Follow-up analysis ([`analysis/CALIBRATION-TRANSFER.md`](../analysis/CALIBRATION-TRANSFER.md),
`python3 analysis/calibration_transfer.py`): if the curve is stable, it should be
correctable, and it is, with a caveat that matters.

Fitting Platt independently per tier splits the two parameters cleanly. The slope
is stable at 2.11–2.61 across every tier and pass: Jev's log-odds are roughly half as
extreme as they should be, and that is a property of the model. The intercept
spans −0.48 to +1.75, absorbs the slice's base rate, and belongs to the slice.

So transferring a whole map is unreliable. Across the twelve tier-to-tier transfers
it cut mean ECE 54%, but t3 → t4 made calibration *worse* (0.147 → 0.184, consistent
on all three passes). Transferring only the slope and refitting the intercept on 50
labels cut mean ECE 61.7% on held-out items the refit never saw; the worst single
draw reached 0.124, still below the worst uncorrected case. Accuracy is untouched
throughout, since the maps are monotone.

| approach | mean ECE, 12 transfers | worst case |
|---|---|---|
| none | 0.1306 | 0.147 |
| full map from elsewhere | 0.0597 (−54%) | 0.184 (worse than nothing) |
| slope transferred, intercept refit on 50 labels | 0.0512 (−61.7%) | 0.124 |

It reaches the negation probe too, a different wording and construction, improving
from all four tiers, though that sample's headroom was small.

The practical summary: **Jev returns a well-behaved monotone score with a stable
distortion, not a probability.** Turning it into one costs a slope fitted once and
about fifty labels per deployment. Whether the slope survives a change of domain, or
a retrain, is untested.

### The earlier hypothesis, and how it fared

The framing recorded on 2026-09-17, that Jev's calibration tracks its accuracy
rather than holding independently of it, is not supported. It was built on two
confounded points from different studies; a controlled gradient shows the calibration
function holding roughly constant while accuracy falls by 7.5 points. What varies
with difficulty is where predictions land on that curve, which raises ECE without
any degradation in calibration. The cross-study pattern that suggested the hypothesis
is better explained by spam and phishing having different *directions* of error than
by difficulty.

### A reporting standard for this repo

Any calibration number added to this ledger should carry: n, the binning, the ECE, the
simulated noise floor for that n and probability distribution, the ratio between them, and
coverage at whatever threshold is quoted. `jevlab.stats.ece_with_floor` and
`coverage_at` produce all of it.

The community Enron test (93.7% accuracy at ≥95% confidence, n=9,840) is still uncited here
because it reports no coverage. Without the fraction of cases that cleared the threshold,
the number cannot be read: it is consistent with a great model and with one that abstains
on everything hard.

## Sources

Ours: live API calls 2026-09-16, TypeSafe docs and launch post read directly.

Third-party benchmarks: [jev-benchmark](https://github.com/themsquared/jev-benchmark),
[jev-phishing-bench](https://github.com/anisselbd/jev-phishing-bench),
[jev-spam-eval](https://github.com/bitnovus/jev-spam-eval),
[jev-rerank-bench](https://github.com/anessbelbati/jev-rerank-bench),
[openjev](https://github.com/TheoLeeCJ/openjev),
[typesafe-ai-benchmark](https://github.com/iammrduncan/typesafe-ai-benchmark). Directory:
[awesome-typesafe](https://github.com/Hawxy/awesome-typesafe).

Launch coverage consulted for §2 and §3: HN (1,797 pts), The Register, SiliconANGLE, The
Rundown, Cherry Creek audit, Actionbox, LumaDock, Every, Near Here, Good Start Labs,
DataCamp, Developers Digest, and founder posts.
