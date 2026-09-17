# What is Jev, actually? — the exploratory thread



_24 posts. Written 2026-09-16, the day after Jev launched._

---

### 1/24

Everyone on my feed is fighting about Jev, TypeSafe's new model. Four camps, four confident takes. This thread starts from zero — normal LLM APIs — builds up to what Jev actually is, and at the end we'll see which camps survive contact with evidence.

---

### 2/24

Start with what you know. A normal LLM API looks like this: you POST a list of messages, the model generates text, you get text back. OpenAI's chat completions, Anthropic's messages, Ollama locally — same deal. Text in, text out.

---

### 3/24

Ollama makes it concrete because it's yours: POST /api/chat with {"messages": [...]}, tokens stream back. Underneath, the model is a next-token prediction machine wearing a chat costume. Every "decision" you get out of it is you interpreting generated text.

---

### 4/24

Here's the rub: you usually didn't want a paragraph. You wanted a decision. Is this ticket urgent? Which broker issued this statement? So you prompt "answer with only YES or NO" and parse the output with code, praying the model obeys. This is prompt-and-parse, and half the industry runs on it.

---

### 5/24

Function calling was the industry's fix: you declare a JSON schema, the model "calls" your function by emitting matching JSON. Better! But look underneath: it's still a text generator emitting tokens that happen to be JSON. The structure is a costume too.

---

### 6/24

And there's a deeper problem no costume fixes: trust. Ask a chatbot "how confident are you?" and it will happily say 90% — a number with no relationship to reality. Its logprobs are uncalibrated. You cannot set a threshold on vibes. "Flag everything below 0.9" is meaningless when 0.9 doesn't mean 90%.

---

### 7/24

Now flip the API inside out. Jev's endpoint doesn't take a conversation and return text. It takes a state (the world to judge) and a set of typed questions, and returns judgments — numbers, not prose. POST https://api.typesafe.ai/v1/systemone. That's the whole surface area. One endpoint.

---

### 8/24

The request shape: an "Authorization: Bearer <key>" header, and a JSON body with three things — "state" (the evidence: a plain string, or structured JSON), "model" ("jev-latest"), and "questions": a map where YOU choose the keys, each holding one typed question. The response echoes your keys back with one answer each, plus a usage block with input_tokens and output_tokens. Typed in, typed out.

---

### 9/24

Three question types. That's the entire expressive surface of the model. First — Noul: a yes/no question. It returns P(yes) as a float between 0 and 1. Not "yes." Not a paragraph. A number.

---

### 10/24

Second — Choice: pick one option from a set you define. It returns the winner, the full probability distribution across every option, and a confidence. You don't just get the answer; you see the runner-up. Ties and near-ties are visible instead of hidden.

---

### 11/24

Third — Score: rate along ordered levels you describe in plain language ("truncated" → "mostly complete" → "complete"). It returns a position that can land between levels, plus the distribution and confidence. Graded judgment, not a bucket.

---

### 12/24

The anatomy of a question matters. "instructions" holds the judgment ("Does this statement indicate the total is $X?"); "criteria" defines the possible answers. State is the evidence, instructions are the ask, criteria are the answer space. You're designing a measurement instrument, not writing a prompt.

---

### 13/24

And here's the philosophical split: code owns the workflow. Jev never generates text, never calls your functions, never decides what happens next. It's a pure function — judgment in, number out. Thresholds, weights, routing, escalation: all in your code, where you can actually test them.

---

### 14/24

Why would you want this instead of prompt-and-parse? Three operational reasons. One: parallelism — independent questions over the same state go in ONE call; I asked six at once. Two: tiny outputs — my calls used ~864 input tokens and ~23 output tokens. Three: speed — my round trips were about two seconds including network.

---

### 15/24

(Their own cookbook claims batching 13 questions into one call is 12.2x cheaper and 10x faster than the alternative, with no change in answers. That's their number, not mine — but the direction matches what I measured.)

---

### 16/24

Camp 1: "This is a new model class." The steelman: TypeSafe's stated bet is training for calibrated decisions instead of next-token text generation. If 0.9 actually means 90% — if the numbers are honest — that IS a different optimization target than a chatbot, even on a familiar architecture. The claim is about the training objective, not the transformer.

---

### 17/24

Camp 2: "It's basically a classifier." The steelman: Noul is binary classification, Choice is multiclass, Score is ordinal regression. Structurally, this camp is just… correct. The rebuttal: most classifiers don't take arbitrary natural-language rubrics over arbitrary state and return calibrated probabilities plus confidence in a single call. It's a classifier with a natural-language API. That's not nothing.

---

### 18/24

Camp 3: "You can already do most of this with a normal LLM." Also correct! Prompt GPT with "answer YES/NO and give a confidence score" and parse it. You absolutely can. The rebuttal is economics and reliability: you pay for output tokens, you fight format drift, your "confidence" is uncalibrated, and it's slower. Same territory, strictly worse operations. This camp confuses "possible" with "practical."

---

### 19/24

Camp 4: "I don't care what it is, just use it as a decision layer." The only camp offering advice instead of ontology. And notably, it's the posture TypeSafe's own docs push: keep policy in code, fit thresholds on YOUR data, treat answers as measurements. You don't have to believe it's a new model class to use it well.

---

### 20/24

What did our tests actually probe? Three scenarios, one call each. Clean statement: every extracted field verified at 0.99, broker classified with full confidence. Then I planted a transposed digit in the total ($1,274,392.11 → $1,284,392.11): Jev returned 0.01 and the escalation rule flagged it automatically. Truncated document: completeness scored 0.01 at 99% confidence. Small-n and synthetic — suggestive, not proof — but the shape behaved: decisive when evidence is clear, near-zero when it's wrong, graded when it's partial.

---

### 21/24

So which camps are right? 2 and 3 describe the mechanism (it's classifier-shaped; an LLM could emulate it). 1 describes the bet (calibration as the optimization target — real IF the numbers are honest). 4 describes the correct posture (a decision layer inside code-owned workflows). They're not mutually exclusive: mechanism, bet, and posture are three different questions, and the feed is arguing past itself.

---

### 22/24

The experiment that would actually settle camp 1's claim: a calibration curve on YOUR data. Run a few hundred Jev judgments where you know ground truth, and plot predicted probability vs. actual hit rate. If 0.9 ≈ 90%, camp 1 earns the name. If not, it's camp 2 with good marketing. That's the real test — and your statement pipeline is already shaped to run it, once we feed it real extractions.

---

### 23/24

Practical rules if you use it, from their docs plus our tests: one narrow judgment per question; always include a no-match or "unclear" option; confidence measures how concentrated the distribution is, NOT whether the answer is correct; thresholds are yours to fit — 0.9 is a starting guess, not a law; and respect the API (a 429 means back off with retries, and the usage block shows input vs. output tokens so you can watch cost).

---

### 24/24

TL;DR: Jev is a judgment API — three typed primitives returning probabilities instead of prose. It's classifier-shaped, LLM-emulable, and possibly genuinely new in its calibration objective. The right move is camp 4: use it as a decision layer, keep policy in code, and let a calibration curve on your own data decide whether camp 1 deserves the crown. /fin
