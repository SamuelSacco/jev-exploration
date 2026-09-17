# Jev: claim audit + demos

Exploratory findings, 2026-09-16/17. Sources: TypeSafe docs + launch post (read directly),
my own live API calls (7 total, all within normal use), and a sweep of launch coverage:
HN (1,797 pts, 474 comments), The Register, SiliconANGLE, The Rundown, Cherry Creek audit,
Actionbox review, LumaDock, Every, Near Here, Good Start Labs, and founder/social posts.
Jev launched Sept 15, 2026 — discussion is ~48h old. No Reddit threads, no peer-reviewed
evals, no published calibration data exist yet.

---

## 1. Claims I verified myself (live API + docs)

**The HTTP contract is exactly as documented.** One endpoint —
`POST https://api.typesafe.ai/v1/systemone` — taking `{state, model, questions}` and
returning `{model, answers, usage}`. Three question types, no more: Noul → P(yes) float,
Choice → winner + full distribution + confidence, Score → probability-weighted position
(between levels allowed) + distribution + confidence. Verified across 7 live calls.

**Parallel batching works as advertised.** 36 questions (12 tickets × 3 judgments) in
ONE call, 1.61s round trip. 8 rerank questions in one call, 1.69s. Adding questions did
not blow up latency.

**Outputs are tiny; output is free.** My calls used 89–997 output tokens. TypeSafe prices
input at $0.042/MTok and output at $0 ("too cheap to meter") — published in the launch
post, consistent with usage blocks I received. Concrete: the 12-ticket triage call cost
3,357 input tokens ≈ **$0.00014 — 36 judgments for a tenth of a cent.**

**The honest-uncertainty behaviors check out.** When I asked an unknowable question
("will the user renew?") it returned 0.49. When I forced a Choice with no good option
and no "other," it picked at 0.52 probability with **0.04 confidence** — the distribution
itself flags the garbage-in case, which is exactly why the docs say to include a
no-match option. Contradictory evidence returned 0.40, leaning correctly but uncertain.

**Documented limits confirmed present, unpublished limits confirmed absent.** 255-option
Choice cap and ~32k-token request budget are documented. No public rate limits, SLA, or
uptime commitment exist (only 429/529 + backoff guidance in the API reference).

---

## 2. Claims that are true but smaller than the marketing

**Speed/cost multipliers.** Official surfaces disagree with each other: 193.6x/444.6x
(homepage), 40–200x (blog), 20–200x (founder thread), 100x (launch video) — and the
homepage's own 0.114s-vs-8.566s Doom demo is a 75x ratio, not 193.6x. TypeSafe's own
caveat: headline figures are "on the higher end of real world gains." Independent tests:
~5x faster / 8.6x cheaper (Near Here, n=50), ~25x faster / ~580x cheaper (Every, vs a
heavy-reasoning flagship). Direction: true. Headline numbers: best-case marketing.

**"Similar intelligence to frontier LLMs."** TypeSafe's 4 workflow evals: Jev 67.8%
agreement at $0.0004/case vs GPT-5.6 Terra 67.9% at $0.0304 — i.e., Jev *ties a mid-tier
LLM* and trails top reasoning models (Sol 74.1%, Opus 73.1%). Worse: reference answers
are the *average output of two other LLMs*, not ground truth — TypeSafe acknowledges
the bias. Independent: Near Here got 96% vs 84–86% for small LLMs on moderation;
Every's Jev caught 6/7 planted defects vs Fable's 7/7. Verdict: competitive with
mid-tier models on bounded classification, not frontier, at a fraction of the cost.

**My latency vs theirs.** They claim 70–500ms end-to-end. I measured 1.6–3.7s from my
VM (includes network). Independent testers measured 0.35–0.59s. Their number is
plausible near their infra; not reproduced from here.

---

## 3. Claims I can debunk (or that debunk themselves)

**"Can't hallucinate."** Debunked as stated — including by TypeSafe. Their 0% chart
carries the footnote *"Our number is not empirical. Schema matching is guaranteed."*
Their own docs: **"Typed output guarantees the interface, not truth."** What Jev can't
do is emit a malformed answer; it can absolutely emit a confident wrong valid value.
Constrained decoding gives any LLM the same shape guarantee (LumaDock, HN consensus).

**"0% structured-output error rate."** Definitional, not measured — admitted in their
own footnote. Not a benchmark result.

**"New model class" as a scientific category.** No weights, no paper, no parameter
count, no architecture details published. "System One Model" is TypeSafe's product
category name, not an established scientific classification. The RLCD training method
is a name plus a stated objective ("epistemically honest probabilities") — nothing
more is public. Unverifiable either way.

---

## 4. Claims still unverifiable (the important ones)

**Calibration — the central claim — has zero public evidence.** No calibration curve,
no ECE figure, no paper. The entire "new model class" bet rests on probabilities
meaning what they say, and nobody outside TypeSafe has measured it. My n=4 edge probes
are suggestive (0.49 on unknowable, 0.04 confidence on forced choice) but prove nothing.
The community Enron test (93.7% accuracy at ≥95% confidence) is suggestive but reports
no coverage. **This is the experiment that matters, and it hasn't been run publicly.**

**Rate limits, SLA, fine-tuning, context beyond 32k** — all unpublished.

---

## 5. Demos: where Jev makes sense, with data

All run live 2026-09-16, jev-1.13.0, data + scripts in `~/workspace/jev_claims_lab/`.

**A. Support-ticket triage (the "decision layer" pattern).** 12 hand-labeled tickets,
3 questions each (department Choice, urgency Noul, frustration Score), one call:
1.61s, 3,357 in / 997 out tokens (~$0.00014). Department 10/12, urgency 12/12,
frustration mean-abs-error 0.25. Both department "misses" were genuinely ambiguous
labels (feature-request → "other" vs my "technical"; quote dispute → "billing" vs my
"sales") — defensible judgments, not errors. *Makes sense when:* high-volume routing
where you need several judgments per item in one shot and thresholds live in code.

**B. RAG rerank.** 8 passages (4 relevant, 4 distractors), one Noul each, one call:
1.69s, 975 in / 140 out tokens. 8/8 correct, perfect ranking, decisive separation
(0.94–0.98 vs 0.01). *Makes sense when:* gating retrieved context before expensive
generation — a cheap relevance filter.

**C. Statement verification (prior session).** GPT-extracts / Jev-verifies: clean
statement 0.99 across fields, planted transposed digit → 0.01 with auto-escalation,
truncated doc → completeness 0.01 at 0.99 confidence. *Makes sense when:* a generative
model produces claims and you need a cheap, typed verifier with an escalation rule.

**D. Edge cases (this session).** See section 1 — the product is the *distribution*,
not the answer. *Makes sense when:* you will actually use confidence to route,
escalate, or abstain. If you ignore the probabilities and just take the top label,
you've rebuilt a worse classifier.

**Where it does NOT make sense:** anything needing generation, reasoning traces,
exact computation, or ground-truth-critical calls without human review. Even
enthusiasts frame it as complement: "Jev decides, LLM writes."

---

## 6. Bottom line

- **Camp "basically a classifier":** structurally correct, and independent tests show
  Jev ties mid-tier LLMs on bounded classification — at ~1/75th the cost.
- **Camp "normal LLM can do it":** true, and the open-source crowd is already
  replicating the shape (constrained decoding + logit reading). What they can't
  replicate is the calibration — which is also what TypeSafe hasn't proven.
- **Camp "new model class":** unproven. One real idea (RLCD/calibration objective),
  zero public evidence. The name is marketing until a calibration curve exists.
- **Camp "use it as a decision layer":** the only actionable one, and the posture
  TypeSafe's own docs push ("typed output guarantees the interface, not truth";
  "validate performance in the target domain").

The feed is arguing about taxonomy. The question is calibration. Nobody has run the
experiment — which means the most valuable thing a Jev user can do right now is run it
on their own data: a few hundred judgments against ground truth, predicted probability
vs. hit rate. Everything else is commentary.
