# Laya on this repo's fixtures, and the playground 500 reproduced

Run 2026-10-01. Laya is the open-source local model whose API mirrors
Jev's (`{state, questions}` in, typed answers with probabilities out).
Two evaluations: (1) Laya over this repo's three committed Noul
fixtures, question payloads byte-identical to the committed Jev runs;
(2) a reproduction of the only public head-to-head, the 500-example
benchmark in `wdobry/laya-playground`, on its own rebuilt dataset.

Raw outputs are committed next to the Jev runs they are scored against:
`lab/runs/20261001T170333Z-laya-all.jsonl` (1,360 records) and its
`-scores.json`. The Jev arm is recomputed from the committed raw
responses by the same scorer, never copied from prose.

## Setup

- Package `laya 0.3.22`, checkpoint = the English root of
  `convaiinnovations/laya` (ModernBERT-large, 421M params, 512-token
  context): `model.safetensors` 842,609,210 bytes, SHA-256
  `891102d372…c86c`, identical to the hash pinned in the Laya repo's
  `verify/checkpoints.json` (whose pinned revision `1c5edc17…` carries
  the same weights as the revision `laya.load` resolves today,
  `55cf4c4e…`).
- This VM: 2 CPU cores, ~8 GB RAM, no GPU, torch CPU build, inference
  in fp32 (the checkpoint config's `amp_dtype: bf16` is a CUDA default;
  on CPU, bf16 autocast is opt-in via `LAYA_CPU_AMP` and was not set —
  verified in the installed `laya/agent.py`). Model load 16 s in the
  fixture runs (~31–36 s in two earlier smoke loads on the same VM).
- States: tiers 76–149 tokens, domains 45–73, negation 8–23.
  `state_tokens_dropped` = 0 and `truncated` = false on all 1,360
  records — nothing was cut by the 512-token window.

## Integration facts (each verified by direct observation)

- `pip install laya` as documented does not currently produce a working
  install: the package declares `transformers>=4.48` unbounded, which
  today resolves to transformers 5.x, under which `laya.load` crashes
  (observed during setup: `AttributeError: 'IterableList' object has no
  attribute 'items'`). Pinning `transformers<5` (4.57.6) works.
- `laya.load` also fails fully offline (`HF_HUB_OFFLINE=1`) even with a
  complete local cache (observed: `FileNotFoundError: Incompatible
  model`). Loading from a local checkpoint directory works.
- The shipped English config carries `choice:11+` temperature
  0.1006, outside the loader's own valid range [0.5, 5]; `laya 0.3.22`
  warns and clamps it to 0.5. No question in either evaluation has 11+
  options, so the clamp touches no number here. The Noul temperature
  actually applied is the shipped 1.9834 — Laya's own fitted value.
- The page hero ("322M params / 650 MB") describes the multilingual
  checkpoint. The English checkpoint used here and in the playground
  benchmark is 421M / 843 MB.

## Formulation differences (disclosed, then bounded)

The question payloads are byte-identical to the Jev runs. The states
differ in two ways, both forced by Laya's 512-token window:

1. **Batching.** Jev's states held many items (40 messages for tiers,
   chunks for domains, all 80 passages for negation); Laya's hold one.
   The shared state was visible to every Jev question — claims-audit
   row 18 isolates question *instructions*, not state — so this is a
   genuine confound: batched state gives cross-item contrast, and on
   negation both halves of every minimal pair were co-present for Jev.
2. **State format.** Jev's per-item state slices carried `[{id}]`
   markers under a header (`Messages:`, `Items:`, `Passages:`); Laya's
   states are the bare item text, so the id each instruction references
   ("Is message t1000…") appears nowhere in Laya's state.

**Control (measured, not argued).** Jev was re-run per-item — bare
single-item states, exactly what Laya received — on a 160-item subset
(the 40 t1 diagnostic items, 10 per domains slice, all 80 negation
items; raw responses in `lab/runs/20261001T181500Z-jev-peritem.jsonl`).
Batching is worth something to Jev, and it is not worth 40 points:

| subset | Jev batched | Jev per-item | Laya per-item |
|---|---|---|---|
| t1 diagnostic-40, acc | 1.000 (pass 0) | 0.900 | 0.500 |
| t1 diagnostic-40, ECE | 0.130 | 0.215 | — |
| negation-80, acc | 1.000 | 0.988 | 0.825 |
| negation pairs resolved | 40/40 | 39/40 | 26/40 |
| domains slices (n=10 each), acc | 1.00/1.00/0.94/0.98 (full slices) | 1.00/1.00/0.90/1.00 | — |

Per-item formulation costs Jev 4 of 40 items on the t1 diagnostic subset
(1.000→0.900; McNemar exact one-sided p=0.063, Newcombe 95% CI −0.6/+23.1
points) — a real-looking but imprecisely estimated effect, scoped to t1,
the only tier subset with a per-item Jev control (t2–t4 have none). It
costs one negation pair (40/40→39/40). The remaining gap to Laya on
identical per-item inputs is 40 points on t1 (0.900 vs 0.500, p<0.0001)
and 13 pairs on negation. The
dangling-id objection (difference 2) is bounded twice over: the
phrasing diagnostic below (id-free and minimal phrasings collapse
identically on tiers, ranking intact), and a direct rerun of Laya
with Jev's exact per-item state slices (`"[{id}]\n{text}"`) on 160
items — t1 acc 0.500 (unchanged), domains-40 0.675, negation 0.838
(vs 0.825 bare). State format changes nothing.

## Fixtures: Laya collapses on tiers, degrades on domains, holds up on negation

Laya, English 421M, per-item states. Jev recomputed from committed raw
(tiers: mean of the 3 passes; domains: rep 0 — per-rep Jev accuracies
are identical across reps in every slice, so the choice is immaterial).

| group | n | Laya acc | Laya ECE (×floor) | Laya Brier | Jev acc | Jev ECE |
|---|---|---|---|---|---|---|
| tiers t1_trivial | 200 | 0.510 | 0.438 (15.5×) | 0.408 | 0.972 | 0.116 |
| tiers t2_ordinary | 200 | 0.525 | 0.429 (14.6×) | 0.409 | 0.980 | 0.122 |
| tiers t3_hard | 200 | 0.500 | 0.455 (23.8×) | 0.453 | 0.937 | 0.139 |
| tiers t4_adversarial | 200 | 0.495 | 0.479 (21.1×) | 0.486 | 0.893 | 0.141 |
| domains code_security | 120 | 0.583 | 0.250 (3.4×) | 0.275 | 1.000 | 0.091 |
| domains code_security_rare | 120 | 0.767 | 0.064 (1.0×) | 0.179 | 1.000 | 0.087 |
| domains contract_liability | 120 | 0.500 | 0.210 (2.5×) | 0.263 | 0.942 | 0.197 |
| domains lab_safety | 120 | 0.667 | 0.122 (1.4×) | 0.214 | 0.975 | 0.178 |
| negation | 80 | 0.825 | 0.106 (1.1×) | 0.131 | 1.000 | 0.065 |

Mechanism on tiers: Laya assigns P(phishing) ≈ 0.00–0.10 to nearly
every message regardless of content (mean 0.05–0.07 per tier, max
0.49–0.91), phish and legitimate alike — e.g. a t1 "Action required:
verify your account within 24 hours" lure scores 0.027. Accuracy lands
on the legitimate base rate, flat across all four difficulty tiers;
there is no difficulty gradient because there is no discrimination at
the 0.5 threshold. As a forecaster it is worse than refusing to play:
Brier 0.41–0.49 on tiers vs 0.250 for a constant-0.5 predictor.
Coverage at p ≥ 0.9 is 0.000 in every group except t2 (0.005) — it
essentially never asserts the positive class at routing confidence,
which is the property this repo's use case runs on.

The ranking view, for fairness — Laya's probabilities are compressed,
so threshold accuracy understates what a fitted threshold would get:

| group | Laya AUC | best-threshold acc | note |
|---|---|---|---|
| tiers t1 | 0.872 | 0.830 | ranking intact, scale broken |
| tiers t2 | 0.747 | 0.695 | |
| tiers t3 | 0.593 | 0.600 | |
| tiers t4 | **0.246** | 0.500 | ranking *inverted* — no monotone recalibration fixes this |
| domains code_security | 0.714 | 0.692 | |
| domains code_security_rare | 0.603 | 0.775 | acc 0.767 ≈ always-negative baseline 0.750 (base rate 0.25) |
| domains contract_liability | 0.612 | 0.608 | |
| domains lab_safety | 0.733 | 0.708 | |
| negation | 0.918 | 0.850 | pairs fully resolved 26/40 (Jev 40/40) |

The t4 inversion is the signature of a cue-following judge: the
adversarial tier's surface cues point against the label by
construction, and Laya follows the cues. Recalibration (this repo's
row-23 recipe) is not applied to either arm — grading the shipped
probabilities is grading the product, and Jev received no fitted map
either.

Latency on this VM (single process, no batching): p50 2.33 s/item on
tiers, 1.61 s on domains, 1.37 s on negation. Jev's hosted latency is
not comparable from here (see the playground section).

## Phrasing is not the cause

Five variants over the same 40 balanced t1 items (20 phish / 20 legit).
A is the committed Jev payload verbatim; B drops the message-id
reference; C is a minimal "Is this email phishing?"; D keeps the
verbatim question but shrinks the state to the subject line; E drops
the criteria dict.

| variant | acc | mean P(phish) | AUC |
|---|---|---|---|
| A verbatim | 0.500 | 0.063 | 0.870 |
| B id-free instructions | 0.500 | 0.051 | 0.87–0.88 |
| C minimal question | 0.500 | 0.055 | 0.87–0.88 |
| D subject-line state only | 0.525 | 0.220 | 0.647 |
| E no criteria | 0.500 | 0.020 | 0.708 |

No variant recovers threshold discrimination (acc 0.500–0.525 across
all five): the collapse is not caused by the id reference or the surface
wording of the question. Ranking is a different story — it is sensitive
to the payload: dropping the criteria dict (E) degrades AUC 0.870→0.708
(paired bootstrap 95% CI on the drop excludes 0), and shortening the
state to the subject line (D) degrades it to 0.647 while quadrupling
mean P(phish). The lever is the input payload — state content and
criteria — not the surface phrasing.
The same checkpoint scores 0.96 on SMS spam in the benchmark below:
short single-purpose messages are its distribution; multi-sentence
formatted email is not.

## The playground 500, reproduced

The only public head-to-head lives in a third-party repo
(`wdobry/laya-playground`, MIT, unaffiliated): 500 examples, 5 public
tasks × 100, balanced, human gold from public test splits, recorded
2026-09-20 with Laya v0.3.4 and hosted `jev-1.13.0`. The upstream Laya
repo itself states it never measured Jev. The playground's raw texts
and raw Jev responses are git-ignored there, so the Jev arm here is
fresh API calls on their rebuilt dataset (`eval/build_dataset.py`,
seed 7 — regenerated `tasks.json`/`provenance.json` are byte-identical
to the committed originals, so the sample is exactly theirs).

Reproduction deltas: `laya 0.3.22` (weights hash-identical to their
0.3.4 checkpoint), local CPU vs their M1 Max GPU; the API served
`jev-1.13.0` — the same version they recorded. Their scoring code
(`read_answer`/`ece`/`summarise`) is used verbatim. Jev spend:
194,902 input tokens = $0.00819 — their recorded token count exactly,
so the payload stream was identical.

| task | type | Laya acc / ECE (here) | Laya (recorded) | Jev acc / ECE (here) | Jev (recorded) |
|---|---|---|---|---|---|
| AG News | choice ×4 | 0.930 / 0.061 | 0.93 / 0.061 | 0.920 / 0.074 | 0.92 / 0.073 |
| SMS spam | noul | 0.960 / 0.052 | 0.96 / 0.052 | 0.950 / 0.076 | 0.96 / 0.071 |
| DAIR Emotion | choice ×6 | 0.450 / 0.341 | 0.45 / 0.341 | 0.530 / 0.291 | 0.53 / 0.293 |
| Yelp stars | score ×5 | 0.350 / 0.399 | 0.35 / 0.399 | 0.700 / 0.146 | 0.70 / 0.134 |
| Prompt injection | noul | 0.650 / 0.353 | 0.65 / 0.353 | 0.710 / 0.173 | 0.71 / 0.163 |
| **overall** | | **0.668 / 0.241** | **0.668 / 0.241** | **0.762 / 0.152** | **0.764 / 0.147** |

Laya reproduces to ≤0.001 on every task, accuracy and ECE. Jev is
within one item (SMS accuracy) and ≤0.012 ECE per task. The recorded
result is real,
and its own headline — Jev is more accurate out of the box — is what
its data says. Two scope notes: AG News is in Laya's training mix
(disclosed in the playground data), so that row is an
in-distribution sanity check, not zero-shot evidence; and the sample
is short texts (≤1,200 chars) — the distribution where Laya works.
The Score row is the widest gap in either evaluation: 0.35 vs 0.70
exact-match (within-one-level 0.61 vs 0.96).

Latency: not comparable across setups. Their Laya p50 is 45 ms (M1
Max GPU); on this 2-core VM, in-process, uncontended, Laya runs
p50 1.20 s on the SMS texts. Their Jev p50 (278 ms) used a keep-alive
client; the CLI path used here adds ~1.2 s of process overhead per
call. Accuracy and ECE are the comparable quantities, and both
reproduce.

Raw outputs: `lab/runs/20261001T175300Z-playground500-laya.jsonl` and
`lab/runs/20261001T175300Z-playground500-jev.jsonl`,
aggregates in `lab/laya/versus-repro.json`, runner
`lab/repro_playground500.py`. (Per-example Jev responses are committed;
a fresh rerun of the identical payload stream costs ~$0.008 and
reproduces the aggregates within noise — exact per-example reproduction
not guaranteed, hosted-model non-determinism.)

## Verdicts

- "Laya is a drop-in Jev replacement" — **Refuted** for out-of-the-box
  use on held-out, multi-sentence inputs: at the shipped calibration
  it is at chance on this repo's phishing tiers and domains contracts,
  with ECE 14.6–23.8× the noise floor on tiers, and its ranking
  inverts on adversarial items. On short in-distribution texts (the
  playground benchmark) it is a real, weaker model: ~10 accuracy
  points behind Jev overall, ECE roughly 1.6× Jev's.
- "The playground 500-example head-to-head" — **Verified** as a real
  third-party measurement (it lives in `wdobry/laya-playground`, not
  in the Laya repo, which states it never measured Jev), and
  reproduced here within noise on both arms.
- "Laya's published application numbers (phishing 0.98–0.993 etc.)" —
  **Overstated** as capability evidence: upstream's own BENCHMARKS.md
  flags those datasets as in its training mix, and the held-out
  measurement here contradicts them for email.
- The `laya-integration` SKILL.md circulating with the project was
  reviewed as untrusted third-party content: no credential access, no
  exfiltration, no persistence. Its frontmatter trigger is a catch-all
  that also fires on Jev mentions; do not install it as-is alongside a
  Jev skill.
