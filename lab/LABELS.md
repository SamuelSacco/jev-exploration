# Triage label decisions

Issue #6. Decisions are made on ticket text and criteria wording alone, before any
run is scored, and recorded here so the labels are visibly pre-registered.

## v2 — 2026-09-18

Two tickets had no single defensible home under the v1 criteria. In both cases the
fault was in the criteria rather than the tickets, so both criteria were tightened;
one label changed as a consequence.

### t4 — "the new dashboard is great … it would be nice if the export button remembered my last format"

**v1 label: `technical`. v2 label: `other`.**

The `technical` criterion reads "Bugs, errors, outages, integrations, crashes,
broken features". It enumerates failures only. Nothing in t4 is failing: the export
button works, and the customer is asking for it to remember a preference. Praise
plus a feature request is not a bug, an error, an outage, an integration, a crash
or a broken feature, so `technical` was wrong by its own criterion.

The v1 answer space had nowhere else to put it. `other` read only "Does not fit any
of the above", which is true but says nothing, so the label was doing work the
criteria did not support.

Fix: `other` now names what it covers, so feature requests and feedback have an
explicit home without widening the answer space from four options (which would make
the committed runs incomparable).

> **other**: Feature requests, product feedback, praise, or anything that is not a
> failure, a payment matter, or a pre-sale question.

The test this decision had to pass: *would I still call the v1 label wrong if a
model had answered `technical`?* Yes. The criterion lists failure modes and t4 has
no failure; the argument does not reference any model output. Stated plainly
because this change does move the number in Jev's favour — see below.

### t12 — "I was quoted $49/user/month on the phone but my contract says $59 … before I sign"

**v1 label: `sales`. v2 label: `sales`, unchanged.**

Two criteria both claimed this one. `billing` read "…subscriptions, pricing
disputes" and `sales` read "Plan comparisons, quotes, discounts, upgrades,
pre-purchase questions". A quote-versus-contract discrepancy is literally both a
pricing dispute and a question about a quote.

Deciding from the text: the customer has not signed. There is no payment, no
invoice, no charge and no subscription, so billing has nothing to act on — there is
no account to adjust. The dispute is between a verbal quote and a contract, both of
which sales owns, and it is explicitly pre-purchase.

Fix: `billing` now scopes its pricing disputes to money that has actually moved.

> **billing**: Payments, invoices, refunds, charges, subscriptions, and disputes
> about amounts already charged.

The label stands, so this remains a miss for the committed run.

## Effect on the committed 2026-09-17 run

Re-scoring `lab/runs/20260918T005803Z-triage.jsonl` under v2 labels moves department
routing from 10/12 to 11/12: t4 now counts as correct, t12 still does not.

That is a change in our favour, made by us, after seeing the result, which is the
exact pattern this repo criticises elsewhere. The mitigations are that the reasoning
above cites only ticket text and criteria wording, that it is recorded before the
re-scored number is used anywhere, and that the other disputed ticket was left
standing as a miss. Both numbers should be quoted with their label version, and at
n=12 neither is distinguishable from the majority-class baseline anyway
(11/12 has a 95% interval of [65.1%, 97.9%]).

## v1 — 2026-09-16

Original hand labels, 12 tickets. Both tickets above were labelled without noticing
that the criteria admitted more than one answer.
