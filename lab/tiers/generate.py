"""Generate the difficulty-gradient dataset for issue #1.

Deterministic and seeded, so the committed dataset can be rebuilt byte for byte
and audited by rerunning rather than by trusting the file.

    python3 lab/tiers/generate.py --out lab/tiers/dataset.jsonl

Two things make the labels trustworthy:

**Ground truth is chosen before the message exists.** The generator decides
"phishing" or "legitimate" and then builds a message to match, so the label never
depends on anyone reading the finished text. That removes the after-the-fact
adjudication issue #6 ran into.

**Every message carries a DECISIVE element matching its label, in every tier.**
A phishing message always contains the malicious act itself -- a payment
redirected to a new account, credentials requested at an off-domain host, an MFA
code solicited by reply. A legitimate one always contains something that settles
it the other way -- no sensitive ask, first-party destinations only, a
verifiable internal route. The decisive element is never removed or weakened,
only surrounded.

Difficulty is the number of surrounding CUES pointing *against* the label. Cues
are surface texture: urgency, scary subject lines, generic greetings, chatty
context, casual sign-offs. They never determine the answer.

  t1_trivial      2 cues agreeing with the label, 0 against
  t2_ordinary     1 cue agreeing, 0 against
  t3_hard         0 cues either way; the decisive element stands alone
  t4_adversarial  0 agreeing, 2 against -- calm, specific phishing and
                  alarming-sounding legitimate mail

So a t4 phishing message reads like an ordinary colleague's note and still
redirects payment to a new account; a t4 legitimate message shouts about account
suspension and still asks for nothing and links only first-party. Both remain
answerable from the text, which is the property that makes the tier usable.

An earlier version of this generator varied the decisive element itself, so a t4
"phishing" item was a message with nothing malicious in it. Those items were not
hard, they were mislabelled, and a model would have been penalised for being
right. That design is recorded in README.md as the mistake to not repeat.

Difficulty is falsifiable rather than asserted: a lexical baseline should fall
from near-perfect on t1 to *below* chance on t4. If it does not, the gradient is
not real and the experiment is void. README.md records the measured baseline.

Known limitation, stated because it bounds what the result can claim: these are
synthetic messages, and t4 is adversarial *to surface cues*. Whether it is
adversarial to Jev is the open question, not an assumption.
"""
from __future__ import annotations

import argparse
import json
import os
import random

HERE = os.path.dirname(os.path.abspath(__file__))

TIERS = {
    "t1_trivial": {"with": 2, "against": 0},
    "t2_ordinary": {"with": 1, "against": 0},
    "t3_hard": {"with": 0, "against": 0},
    "t4_adversarial": {"with": 0, "against": 2},
}

QUESTION_TEMPLATE = (
    "Is message {id} a phishing or otherwise malicious email, as opposed to a "
    "legitimate message? Judge the message on its own content."
)


def lookalike(domain: str, rng: random.Random) -> str:
    """A domain that reads like the real one at a glance."""
    trick = rng.choice(["rn", "hyphen", "tld", "sub", "digit"])
    name, _, tld = domain.partition(".")
    if trick == "rn" and "m" in name:
        return name.replace("m", "rn", 1) + "." + tld
    if trick == "hyphen":
        mid = max(2, len(name) // 2)
        return name[:mid] + "-" + name[mid:] + "." + tld
    if trick == "tld":
        return name + "." + rng.choice(["co", "net", "info", "biz"])
    if trick == "sub":
        return name + "." + rng.choice(["secure", "verify", "account"]) + "-portal.com"
    return name.replace("a", "4", 1).replace("o", "0", 1) + "." + tld


class Builder:
    """Assembles one message from a label, its decisive element, and its cues."""

    def __init__(self, parts: dict, rng: random.Random):
        self.p = parts
        self.rng = rng

    def _company(self):
        i = self.rng.randrange(len(self.p["companies"]))
        return self.p["companies"][i], self.p["domains"][i]

    def build(self, label: str, with_cues: list, against_cues: list) -> dict:
        rng = self.rng
        company, domain = self._company()
        sender_name = rng.choice(self.p["people"])
        recipient = rng.choice(self.p["people"])
        role = rng.choice(self.p["roles"])
        phish = label == "phishing"

        # Matched pair: same topic and vocabulary on both sides, so the label
        # cannot be read off the words. Only who-does-what-where differs.
        pair = rng.choice(self.p["decisive_pairs"])
        decisive = {"kind": pair["topic"], "text": pair["phish" if phish else "legit"]}
        decisive["text"] = (
            decisive["text"]
            .replace("{acct}", rng.choice(self.p["accounts"]))
            .replace("{sort}", rng.choice(self.p["sort_codes"]))
            .replace("{url}", rng.choice(self.p["phish_urls"]))
            .replace("{person}", sender_name)
            .replace("{domain}", domain)
            .replace("{path}", rng.choice(self.p["benign_link_paths"]))
            .replace("{role}", role)
        )

        cues = [(c, True) for c in with_cues] + [(c, False) for c in against_cues]
        kinds = {c["kind"] for c, _ in cues}

        # A cue may set the greeting or the subject; otherwise defaults apply.
        if "generic_greeting" in kinds:
            greeting = rng.choice(self.p["generic_greetings"])
        else:
            greeting = f"Hi {recipient.split()[0]},"

        if "alarming_subject" in kinds:
            subject = rng.choice(self.p["alarming_subjects"])
        elif "routine_subject" in kinds:
            subject = rng.choice(self.p["routine_subjects"])
        else:
            # No subject cue: draw from the neutral pool so the subject line
            # cannot leak the label on its own.
            subject = rng.choice(self.p["routine_subjects"])

        opener = rng.choice(self.p["legit_bodies"] if not phish else self.p["legit_bodies"])
        lines = [f"From: {sender_name.split()[0].lower()}@{domain}",
                 f"Subject: {subject}", "", greeting, opener]

        # Cue sentences that carry text, in a stable order for readability.
        for cue, _ in cues:
            if cue.get("text"):
                lines.append(cue["text"])

        lines.append(decisive["text"])
        lines.append("")
        lines.append(sender_name)
        lines.append(f"{role}, {company}")
        return {
            "text": "\n".join(lines),
            "decisive_kind": decisive["kind"],
            "cue_kinds_with": sorted(c["kind"] for c in with_cues),
            "cue_kinds_against": sorted(c["kind"] for c in against_cues),
        }


def generate(per_tier: int = 200, seed: int = 20260918) -> list:
    rng = random.Random(seed)
    with open(os.path.join(HERE, "components.json"), encoding="utf-8") as fh:
        parts = json.load(fh)
    builder = Builder(parts, rng)

    items = []
    for tier, mix in TIERS.items():
        for i in range(per_tier):
            # Balanced labels within every tier, so accuracy is comparable across
            # tiers and a majority-class baseline sits at exactly 50% everywhere.
            label = "phishing" if i % 2 == 0 else "legitimate"
            own = parts["cue_phish_flavour" if label == "phishing" else "cue_legit_flavour"]
            other = parts["cue_legit_flavour" if label == "phishing" else "cue_phish_flavour"]
            with_cues = rng.sample(own, min(mix["with"], len(own)))
            against_cues = rng.sample(other, min(mix["against"], len(other)))

            built = builder.build(label, with_cues, against_cues)
            items.append(
                {
                    "id": f"{tier[:2]}{i:03d}",
                    "tier": tier,
                    "label": label,
                    "is_phishing": label == "phishing",
                    "decisive": built["decisive_kind"],
                    "cues_with_label": built["cue_kinds_with"],
                    "cues_against_label": built["cue_kinds_against"],
                    "text": built["text"],
                }
            )
    return items


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default=os.path.join(HERE, "dataset.jsonl"))
    ap.add_argument("--per-tier", type=int, default=200)
    ap.add_argument("--seed", type=int, default=20260918)
    args = ap.parse_args(argv)

    items = generate(args.per_tier, args.seed)
    with open(args.out, "w", encoding="utf-8") as fh:
        for item in items:
            fh.write(json.dumps(item, sort_keys=True) + "\n")
    print(f"Wrote {len(items)} items to {args.out}")
    for tier in TIERS:
        n = sum(1 for i in items if i["tier"] == tier)
        phish = sum(1 for i in items if i["tier"] == tier and i["is_phishing"])
        print(f"  {tier:<16} n={n:<4} phishing={phish} legitimate={n - phish}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
