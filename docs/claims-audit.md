# Jev evidence ledger

One row per claim made about Jev, with its current status and the best evidence for or
against it. This file is meant to be edited as evidence appears; it is not a snapshot.

**Last updated:** 2026-09-18 · **Model version in our own runs:** `jev-1.13.0`

Status vocabulary:

| Status | Meaning |
|---|---|
| Verified | Independently reproduced, or checkable from the API contract itself |
| Overstated | Directionally true, but the headline figure is best-case |
| Refuted | False as stated, sometimes by TypeSafe's own footnotes |
| Contested | Measured more than once, with results that disagree |
| Unmeasured | No public evidence either way |

A note on provenance. Rows marked *(ours)* come from our own live calls, listed in
[§5](#5-our-own-runs). Everything else is cited to the party that measured it. We have not
re-run anyone else's benchmark, and the third-party numbers below are recorded as
reported.

---

## The ledger

| # | Claim | Status | Evidence |
|---|---|---|---|
| 1 | One endpoint, `{state, model, questions}` in, `{model, answers, usage}` out | Verified | [§1](#1-the-api-contract) (ours) |
| 2 | Independent questions batch into one call without a latency blowup | Verified | [§1](#1-the-api-contract) (ours) |
| 3 | Output tokens are free; input is $0.042/MTok | Verified | [§1](#1-the-api-contract) (ours) |
| 4 | 255-option Choice cap, ~32k token budget | Verified | TypeSafe docs |
| 5 | No published rate limits, SLA, or uptime commitment | Verified (absent) | TypeSafe docs |
| 6 | Returns honest uncertainty on unanswerable questions | Verified, small n | [§1](#1-the-api-contract) (ours, n=4) |
| 7 | "193.6× faster / 444.6× cheaper" | Overstated | [§2](#2-speed-and-cost) |
| 8 | "Similar intelligence to frontier LLMs" | Overstated | [§3](#3-intelligence-and-accuracy) |
| 9 | 70–500 ms end-to-end | Overstated as a user-facing figure | [§2](#2-speed-and-cost) |
| 10 | "Can't hallucinate" / 0% structured-output errors | Refuted | [§4](#4-refuted) |
| 11 | "New model class" as a scientific category | Unmeasured | [§4](#4-refuted) |
| 12 | An ordinary LLM can reproduce the interface | Verified | [§3](#3-intelligence-and-accuracy) — openjev |
| 13 | **Probabilities are calibrated** | **Refuted at scale** | [§6](#6-the-open-question-calibration) — both studies large enough to measure it find real miscalibration |
| 14 | Confidence is safe to route and escalate on | Task-dependent; refuted on phishing | [§6](#6-the-open-question-calibration) — conf ≥0.9 gives a 73.9% hit rate there |
| 15 | Calibration holds when the model is out of its depth | Unmeasured, and the open question | [§6](#6-the-open-question-calibration) |

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
distribution is. It is not a correctness estimate, which matters for rows 13–15.

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
probes prove nothing about calibration, and we are not counting them as evidence for row
13. They establish that the failure modes are visible in the distribution, which is a
weaker and different claim.

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
triage and rerank from our VM, p50 1.47 s and 1.48 s. The network floor, measured as
TCP + TLS to api.typesafe.ai, is p50 0.67 s from here — but that floor is dominated
by our egress proxy's CONNECT setup (~0.63 s), which is environment overhead, not
distance. Implied service time from this VM is therefore ~0.8 s, an upper bound that
cannot judge TypeSafe's claim. (Caveat on the tooling: `measure_network_floor()` in
`jevlab/client.py` opens a direct socket, which fails behind a transparent proxy;
the floor above was measured through the proxy's CONNECT tunnel instead.)

jev-phishing-bench remains the clean measurement: 239 ms p50 from France against a
measured 163 ms network floor, implying roughly 76 ms of service time, which is
consistent with TypeSafe's range. The 70–500 ms claim is fair as a service-time figure
and misleading as an end-to-end one, because your network floor may exceed the model
time by 2×.

## 3. Intelligence and accuracy

TypeSafe's own evals (evals.typesafe.ai, 711 cases over four workflows) put Jev at 67.8%
against GPT-5.6 Terra at 67.9%, GPT-5.6 Sol at 74.1% and Opus 5 at 73.1%, at $0.0004 per
case against $0.0304–$0.1761 and 0.4 s against 10–38 s. So Jev ties a mid-tier model and
trails the top reasoning models on their own benchmark. The reference answers are the
average of GPT-6 Astra and Fable 5.1 rather than ground truth, which TypeSafe
acknowledges. The site publishes summary statistics and examples, not full raw predictions.

Independent accuracy varies enormously by task, and this spread is the most useful thing in
the ledger:

| Study | Task | n | Jev | Comparator |
|---|---|---|---|---|
| [jev-spam-eval](https://github.com/bitnovus/jev-spam-eval) | spam, in-distribution | 18,514 | 98.3% | TF-IDF logreg 98.4% |
| jev-spam-eval | spam, out-of-distribution | 2,876 | 98.6% | TF-IDF logreg 73.0% |
| [jev-benchmark](https://github.com/themsquared/jev-benchmark) | agent tool-call risk | 60 | 91.7% | — |
| [jev-rerank-bench](https://github.com/anessbelbati/jev-rerank-bench) | rerank, 14 datasets | 1,617 | 0.692 nDCG@10 | Cohere Pro 0.691 (tie) |
| [jev-phishing-bench](https://github.com/anisselbd/jev-phishing-bench) | phishing | 2,000 | 62.6% | Haiku 4.5 81.3%, regex 91.6% |

The spam result is the strongest case anyone has made for Jev: it matches a trained
classifier in-distribution and destroys it out-of-distribution, which is exactly what
zero-shot semantic judgment should buy you. The phishing result is the strongest case
against: 62.6% accuracy and 43.2% recall, beaten by a regex on shorteners and domain
mismatch, with McNemar p < 0.0001 against Haiku.

Row 12 is settled. [openjev](https://github.com/TheoLeeCJ/openjev) reproduces the interface
by reading typed option probabilities directly from Qwen3.5-4B in a single forward pass,
reaching 0.845 modal agreement against 0.883 for published Jev on 102 aligned rows, at
5.21× the speed of generating and parsing a JSON array. The interface is not the moat. The
open question is whether the training is.

## 4. Refuted

**"Can't hallucinate."** False as stated, including by TypeSafe. The 0% chart carries the
footnote *"Our number is not empirical. Schema matching is guaranteed, thus we can
confidently add 0% into the plots."* Their docs say *"Typed output guarantees the
interface, not truth."* Jev cannot emit a malformed answer; it can emit a confident wrong
valid one, and jev-phishing-bench measured it doing so 37.4% of the time. Constrained
decoding gives any model the same shape guarantee.

**"0% structured-output error rate."** Definitional, not measured, per the footnote above.

**"New model class."** No weights, no paper, no parameter count, no architecture details.
"System One Model" is a product category name. RLCD (Reinforcement Learning for Calibrated
Decisions) is a name plus a stated objective, epistemically honest probabilities, and
nothing further is public. Unfalsifiable as stated, so the useful question is not whether
the category is real but whether the calibration is, which is row 13.

## 5. Our own runs

Seven live calls on 2026-09-16, `jev-1.13.0`. These are demonstrations of the API shape,
not evidence of accuracy, and the ledger does not cite them for any accuracy claim. The
reason is in [`review-and-roadmap.md`](review-and-roadmap.md): at n=12 and n=8 every result
we got has a 95% interval that overlaps a trivial non-AI baseline on the same data.

| Run | Setup | Result | Baseline on the same data |
|---|---|---|---|
| Triage | 12 tickets × 3 judgments, one call, 1.61 s | dept 10/12, urgency 12/12, frustration MAE 0.25 | majority class 5/12; urgency regex 9/12 |
| Rerank | 8 passages, one Noul each, one call, 1.69 s | 8/8, clean separation (0.94–0.98 vs 0.01) | word-overlap ≥2: 7/8 |
| Statement verification | extract-then-verify, planted transposed digit | clean fields 0.99; planted error 0.01; truncation flagged | none |
| Edge probes | 4 unanswerable/contradictory questions | see [§1](#1-the-api-contract) | none |

Reproduce the baselines with `python3 lab/baselines.py` (no API key required). Raw
responses for these runs were not committed, which is being fixed; see the roadmap.

### Re-run on the new harness, 2026-09-17

Ten more calls (5 passes × 2 demos), model still `jev-1.13.0` — it has not moved
since 09-16. Raw responses are committed in `lab/runs/`; this is the first run the
ledger can cite at the response level.

| Demo | Result (pass 1 of 5) | Baseline, same data |
|---|---|---|
| Triage | dept 11/12 (v2 labels; 10/12 under v1), urgency 11/12, frustration MAE 0.25 | majority 4/12; urgency regex 9/12 |
| Rerank | 8/8 | word-overlap 7/8 |

The new information is the variance, which nobody has published for these tasks:

- **Triage urgency**: 1 of 12 questions flipped its label across the 5 passes
  (flip rate 8.3%), mean absolute spread 0.016, max 0.06. Urgency also moved
  *between* runs: 12/12 on 09-16, 11/12 on 09-17. A point estimate from one pass
  overstates what it knows.
- **Rerank**: 0 flips, mean spread 0.003 — the 8/8 is stable, which is unsurprising
  given the distractors.
- All three calibration blocks printed **at the noise floor** (ECE 0.026–0.100 vs
  floors 0.044–0.143), exactly as the harness predicts for n=8–12. These demos
  cannot speak to calibration; §6 stands on the third-party studies.

**Label version.** Department scores above use label set v2
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
| jev-benchmark `jev-latest` | 60 | 10 @ [0,1] | 91.7% | 0.0712 | 0.0456 | **1.6** |
| jev-benchmark `jev-preview` | 60 | 10 @ [0,1] | 91.7% | 0.0505 | 0.0452 | **1.1** |

All three published ECEs reproduce exactly. Ratio is detectability, not severity:
a large n lowers the floor, so it says whether a study can speak, not how bad the
miscalibration is.

**jev-benchmark cannot measure calibration in either direction.** At n=60 with 10
bins a perfectly calibrated model scores ECE ≈ 0.045, and both reported figures sit
on top of that. Fifty of its sixty predictions land in one bin; its own `analyze.py`
warns about exactly this. The study's binding finding is the binning-independent
one — none of its five misses came at confidence 1.000 — and that stands.

**jev-spam-eval, usually cited as the evidence Jev is well calibrated, shows real
miscalibration once the middle is included.** Its reported extremes are genuinely
excellent (0.1% spam below 0.1, 99.9% above 0.9). But the curve crosses over around
0.6: below that Jev overstates P(spam) by up to 0.28, above it understates by up to
0.15. Those mid-range numbers are not thresholdable probabilities, they are a
monotone score whose calibrated boundary sits near 0.6. It matters less than it
sounds — bins 0.2–0.8 hold 7.9% of the corpus — which is precisely why reporting
only the extremes looked clean.

**jev-phishing-bench is overconfident in every bin**, worst at 0.85–0.95 where
stated confidence ~0.90 buys a 60% hit rate. At confidence ≥ 0.9: 30.8% coverage,
73.9% hit rate. There is no threshold at which its confidence is safe to route on,
which is the sharpest evidence yet against row 14.

### The hypothesis, and what is wrong with it

The framing recorded on 2026-09-17 — that Jev's calibration tracks its accuracy
rather than holding independently of it — survives the re-analysis only weakly, and
the mechanism argues against it being a single scalar relationship:

- Spam, 98.3% accurate: ECE 0.051, sigmoid-shaped, wrong in a thin middle band.
- Phishing, 62.6% accurate: ECE 0.154, uniformly overconfident across the range.

Absolute ECE does move with accuracy across those two points. But one is a shifted
decision boundary and the other is systematic overconfidence, and two points with
two different failure modes are not a trend. They are also confounded by task,
team, labels and prompt, and spam may be contaminated: its corpora are public and
old enough to sit in training data, which would inflate accuracy and calibration
together.

Distinguishing task difficulty from calibration needs one model, one harness, one
binning, across a deliberate difficulty gradient, reporting the reliability curve
per tier rather than a scalar — because the scalar hides which of those two
failure modes is occurring. That is issue #1.

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
