# Review and roadmap

An audit of this repo against the public Jev benchmark work that appeared alongside it,
and a plan for what to do next. Written 2026-09-17.

## Verdict

The claim audit is the valuable part of this repo and it is close to being the best
thing written about Jev. The demos are not evidence and should stop being presented as
evidence. The central thesis — "nobody has run the calibration experiment" — was true
when it was written and is false now, which is both the biggest problem here and the
biggest opportunity.

Three things to change, in order of how much they matter:

1. Retire the "calibration is unmeasured" thesis and replace it with the question the
   public data actually raises: why do independent measurements of Jev's calibration
   disagree by 3x.
2. Stop reporting n=20 point estimates as findings. None of them survive a baseline.
3. Collapse three documents that argue the same thing into one, and fix the code.

---

## 1. The thesis is stale

The README says calibration has "*zero* public evidence", that the Enron test is the only
suggestive datapoint, and that the decisive experiment "hasn't been run." As of today at
least four independent public repos report calibration metrics on Jev:

| Repo | Task | n | Calibration reported | Accuracy |
|---|---|---|---|---|
| [themsquared/jev-benchmark](https://github.com/themsquared/jev-benchmark) | agent tool-call risk | 60 | ECE 0.0505 (preview) / 0.0712 (latest) | 91.7% |
| [anisselbd/jev-phishing-bench](https://github.com/anisselbd/jev-phishing-bench) | phishing email | 2,000 | ECE 0.154, Brier, reliability diagram | 62.6% |
| [bitnovus/jev-spam-eval](https://github.com/bitnovus/jev-spam-eval) | spam | 18,514 | bin-level hit rates | 98.3% |
| [anessbelbati/jev-rerank-bench](https://github.com/anessbelbati/jev-rerank-bench) | reranking, 14 datasets | 1,617 | bootstrap intervals on nDCG@10 | 0.692 nDCG@10 |

The interesting part is that they contradict each other on the exact claim this repo
cares about.

- jev-benchmark: "every incorrect answer came with hedged confidence", zero errors at
  confidence 1.000, the 0.9–1.0 bin runs at 98% accuracy. Confidence routing works.
- jev-phishing-bench: ECE 0.154 — worse calibration than Claude Haiku 4.5 (0.097) — with
  43.2% recall on phishing. Confident and wrong at scale.
- jev-spam-eval: nearly perfect at the extremes (0.1% spam below 0.1, 99.9% above 0.9)
  but the 0.5–0.6 band overestimates spam prevalence at 38%.

Read together these suggest a hypothesis nobody has tested: **Jev's calibration tracks its
accuracy rather than holding independently of it.** ECE roughly follows (1 − accuracy)
across the three: 91.7% accuracy → ECE 0.07, 62.6% accuracy → ECE 0.154. If that holds, it
is a direct refutation of the marketing position, because calibration is supposed to be
the property that survives when the model is out of its depth. A model that is
well-calibrated only when it is already right has not solved anything.

That is the thing to write. It is answerable from data that is already public, it has not
been said anywhere, and it is a sharper claim than "someone should run a calibration
curve."

Second-order finding worth stealing: jev-phishing-bench's held-out control found that
a plain regex on shorteners and domain mismatch scored 91.8% where Jev's best single
signal scored 89.4% (p = 0.003). The signals-plus-logistic-regression framing (Jev as a
cheap feature extractor feeding a model you fit yourself, 95.0% at 1/27th of Haiku's cost)
is a more defensible posture than "decision layer", and this repo's camp-4 conclusion
should absorb it.

---

## 2. The demos do not support their conclusions

I ran trivial non-AI baselines against the two bundled datasets (`lab/baselines.py`,
no API key needed). With Wilson 95% intervals:

| Measurement | Jev | Trivial baseline |
|---|---|---|
| Rerank relevance | 8/8, CI [67.6%, 100%] | word-overlap ≥2: 7/8, CI [52.9%, 97.8%] |
| Ticket urgency | 12/12, CI [75.7%, 100%] | keyword regex: 9/12, CI [46.8%, 91.1%] |
| Department routing | 10/12, CI [55.2%, 95.3%] | majority class: 5/12, CI [19.3%, 68.0%] |

Every Jev interval overlaps its baseline. At this sample size the demos cannot
distinguish Jev from word overlap, which means "8/8 correct, perfect ranking, decisive
separation" is not a result. The rerank set is the clearest case: the four distractors are
a company picnic, a revenue report, a sourdough recipe and an office lease, while every
relevant passage contains the literal string "PostgreSQL". The task has no discriminative
power by construction.

Other methodology problems, roughly in order of severity:

- **Post-hoc adjudication.** Both department misses are re-described as "ambiguous labels
  (defensible judgments, not errors)" after seeing Jev's answer. This is the same move the
  repo criticises TypeSafe for when it objects to reference answers being the average of
  two other LLMs. Either the labels are fixed before the run or they are not ground truth.
- **Single run, no variance.** jev-spam-eval reports that scores near 0.5 move between
  runs; jev-phishing-bench measured 2.2% label flips on a re-run. Every number here comes
  from one pass.
- **Latency is measured wrong.** `run_demos.py` times `subprocess.run()` of a fresh Python
  interpreter, so the reported 1.61s includes interpreter startup, process spawn and file
  I/O, and is then compared against TypeSafe's 70–500ms model-time claim to conclude their
  figure is "not reproduced from here." There is also no network floor measurement.
  jev-phishing-bench measures its floor explicitly (163ms from France, against a 239ms
  p50) which is the only way that comparison means anything.
- **Raw responses are discarded.** `results.json` holds rounded summaries only. It records
  no model version, no timestamp, no per-call payload, and 5 of the 7 claimed API calls
  (the edge probes and the statement verification) have no committed artifact at all —
  those numbers exist only in prose. Every serious repo in the table above commits raw
  per-call JSONL.
- **Five significant figures on one measurement.** "$0.00014" from a single 3,357-token
  call.

---

## 3. Code

Concrete items:

- `jev_statement_verifier.py:27` — `EXTRACTED_FIELDS` is defined and never referenced. It
  is shadowed by the `fields.json` argument. Dead code.
- `jev_statement_verifier.py:11` and `skills/jev/SKILL.md:16` — `export
  TYPESAFE_API_KEY=<redacted>` as literal instructional text. Say `ts-...` like the README
  does; `<redacted>` reads as a scrubbed real key.
- Three copies of one concern. `jev.py` and `jev_statement_verifier.py` each hand-roll the
  same urllib POST, and `run_demos.py` shells out to `jev.py` through a subprocess instead
  of importing it. One client module, imported everywhere.
- **No retry or backoff anywhere**, although `jev.py:56` prints advice to back off and the
  README states 429/529 require exponential retries. The code does the opposite of what
  the docs say.
- `jev_statement_verifier.py` hardcodes a 0.9 escalation threshold while the entire repo
  argues thresholds must be fit on your own data. Make it a CLI flag and say what it would
  take to fit it.
- The same escalation rule only inspects `noul` answers. `which_broker` could come back at
  0.04 confidence and nothing flags it. Gate Choice on `confidence` and Score on its
  distribution too.
- `run_demos.py` is top-level script code with no `main()`, no error handling, and writes
  `results.json` only at the very end, so a failure in demo 2 discards demo 1's paid call.
- `docs/claims-audit.md:98` points at `~/workspace/jev_claims_lab/`, which does not exist.
- No tests, no CI, no `pyproject.toml`, no LICENSE.

---

## 4. Prose

Three documents make one argument. The four-camp framing, the demo numbers, the
"typed output guarantees the interface, not truth" quote and the calibration conclusion
each appear in `README.md`, `docs/claims-audit.md` and `docs/thread.md`. Any correction has
to be made in three places, and the stale-thesis problem above is now wrong in three
places.

The voice is the tell: bolded lead-in on nearly every bullet, em-dash mid-sentence pivots,
a closing aphorism per section ("That's not nothing", "the product is the *distribution*,
not the answer", "Everything else is commentary", "/fin"), and tables carrying two rows of
content. It reads as generated because the rhythm never varies.

Fix: `README.md` becomes a short front page with the current state of each claim and links
out. `claims-audit.md` becomes the single evidence ledger. `thread.md` stays as the
narrative artifact, dated and frozen, with a note at the top saying it is a snapshot from
launch week and pointing at the ledger for current numbers.

---

## 5. Roadmap

**Reframe (small, highest value).** Rewrite the claim audit as a maintained ledger: one
row per claim, with status, the evidence for it, and a citation to whoever produced that
evidence including the repos above. The repo's differentiator is that nobody else
adjudicated the claims; lean into that rather than competing on demos, where four repos
already have 100x the sample size.

**The one experiment worth running.** Test whether Jev's calibration degrades with its
accuracy. Most of the data is already public — jev-phishing-bench, jev-benchmark and
jev-spam-eval all commit raw outputs — so this starts as a re-analysis rather than a data
collection: pull their per-call results, recompute ECE and reliability curves on a single
consistent binning, and plot ECE against accuracy per task. If you then add one or two
tasks of your own at deliberately varied difficulty, you have the first cross-task
calibration picture of Jev that exists. Budget is trivial at $0.042/MTok.

**Fix the lab or drop it.** If the demos stay, they need: pre-registered labels, a
committed baseline (`lab/baselines.py` is a start), intervals on every number, at least
three repeated runs with variance reported, raw JSONL committed with the model version,
and latency measured in-process against a network floor. If that is more than you want to
maintain, delete the demos and cite the bigger benchmarks instead. Keeping them as-is is
the worst option, because they are the weakest evidence in a repo whose whole argument is
about evidence quality.

**Then the code.** One client module with retries, threshold as configuration, escalation
covering all three primitives, a `pyproject.toml`, and a test that runs against recorded
fixtures so CI needs no API key.

## Ecosystem map

Worth knowing about before building anything, from
[awesome-typesafe](https://github.com/Hawxy/awesome-typesafe):

- [TheoLeeCJ/openjev](https://github.com/TheoLeeCJ/openjev) — reproduces the interface with
  logit reading on Qwen3.5-4B, 0.845 modal agreement against 0.883 for published Jev on
  102 aligned rows. This is the concrete answer to camp 3 ("a normal LLM can do this") and
  the README should cite it instead of asserting it.
- [iammrduncan/typesafe-ai-benchmark](https://github.com/iammrduncan/typesafe-ai-benchmark)
  — Jev vs Qwen-on-Cerebras with cost accounting.
- [Menny1337/jev-lab](https://github.com/Menny1337/jev-lab) — TypeScript latency
  experiments.
- TypeSafe's own evals live at evals.typesafe.ai: 711 cases over four tasks, reference
  answers from the average of GPT-6 Astra and Fable 5.1, summary statistics only rather
  than full raw predictions. The audit's characterisation of this is correct and should
  cite the case count.
