# ProofAegis — The Pitch

> **A vendor sends you the same bill twice, under two different numbers.**
> **Both invoices are perfect. Every AP system on the market pays both.**

---

## The one-liner

Say it to someone who has never worked in accounts payable, because that is
who is judging:

> A supplier bills you for the same work twice. The second invoice has a new
> number and a new date. Nothing on it is wrong — the purchase order agrees,
> the delivery note agrees, the arithmetic agrees. It is a perfect document.
> Your software approves it, because your software is looking at that invoice.
>
> **The evidence that it is a duplicate is in a different file.**

That is the shape of the five most expensive failures in AP, and none of them
are visible from inside the invoice they arrive on.

ProofAegis reads across the whole workspace. On our 320-case portfolio it
surfaces **₹10.66 lakh in exposure that a per-invoice system would have passed
for payment** — because 9 of those 13 findings scored a *full three-way match*
on their own documents.

**What passes is scarier than what fails.**

---

## The problem

An AP clerk gets an invoice. They check it against the purchase order and the
goods receipt. Three documents agree — pay it.

That check is real, it is necessary, and every commercial AP product on the
market does it. It is table stakes.

It is also **structurally incapable** of seeing five of the most expensive
things that go wrong in accounts payable, because every one of them is only
visible from *outside* the case:

| What goes wrong | Why the three-way match cannot see it |
|---|---|
| A vendor bills the same work twice under a new number | The duplicate is in a different case |
| Four instalments each pass, and together exceed the order | Each one is compared to the order alone |
| A supplier's bank details quietly change | This invoice looks completely normal |
| A rate creeps 3% a month, inside tolerance every month | Each month clears; the fourth is materially above the agreed price |
| The duplicate rule fires on every rent payment | Nothing in one case says "this is a schedule" |

Each of those invoices passes. That is the point. A system that only inspects
what it is handed will approve all five.

---

## What we built

Three layers, and the boundaries between them are the product.

### 1. A deterministic core

Matching, tolerance evaluation, financial impact and match score are **plain
Python**. No model is consulted, and none can be.

```
absolute_variance   = actual_value - expected_value
percentage_variance = absolute_variance / expected_value * 100
match_score         = round(100 * matched_count / evaluable_count)
```

**A number a human acts on never comes from a model.** Every other decision in
this system is downstream of that sentence.

### 2. A cross-case investigation layer

The differentiator. Five checks that query the rest of the workspace, all
deterministic:

- **Duplicate invoice** — exact, and the harder near-match
- **Cumulative over-billing** — the running total against the order
- **Changed payment details** — compared to the vendor's last invoice
- **Vendor price drift** — an OLS fit across their last six invoices
- **Recurring billing** — cadence detection, which is what stops the duplicate
  rule firing on rent

### 3. An AI layer that is kept away from the arithmetic

Four Gemini agents via Google ADK, each with a schema-validated output. They
handle **language and judgement** — severity, plain-English explanation, a cited
draft message, and ranked hypotheses about what to check next.

The fourth agent is the one that earns its place: it takes a computed finding
and produces **ranked candidate explanations, each paired with the evidence that
would confirm or rule it out.**

> Price variance of 10.42%. Candidates: (a) the vendor applied a revised rate
> card — look for a price revision notice dated after the order; (b) our PO
> carries a stale rate — check the quotation; (c) the wrong line was matched —
> compare the HSN codes.

**The AI tells you what to check. The code tells you what is true.**

That agent's output schema contains no numeric field at all. There is nothing
for a guardrail to catch, because the failure mode was designed out rather than
policed.

---

## The four things that make this defensible

### 1. We measure ourselves, and we own the failures

Most demos assert accuracy. We ship the harness.

```bash
python -m eval.run_eval --count 320 --json data/generated/eval_report.json
```

| Harness | Result |
|---|---|
| Pipeline — 320 cases, 11 exception types | recall **1.000**, precision **1.000** |
| Extraction — 66 documents across 6 layouts | **1.000** (0 wrong, 0 missed) |

**Ground truth is not derived from the code being graded.** The fixtures
generate *document field values* with an injected defect and say nothing about
the outcome; the label comes from a second, deliberately naive implementation of
the documented policy. If the label came from the matcher, 1.000 would mean
nothing — and a test asserts that independence by source inspection.

**The harness paid for itself immediately.** It found five real defects, all now
fixed, all with a regression test:

| Found | Effect |
|---|---|
| Vendor names compared as raw strings | 21 of 21 spelling variants → false mismatch; precision **1.00 → 0.87** |
| The same identity rule implemented twice, differently | A duplicate went unreported entirely |
| Quantity check skipped itemized invoices | A 4.2% variance silently cleared — money at risk, unflagged |
| A near-duplicate outranked a bank change | **Payment diversion reported as a possible re-submission** |
| Parser returned a document's own title as its supplier | `PURCHASE ORDER` extracted as a vendor name |

We also say what the number does *not* cover: the decision layer is scored on
clean field values, where the arithmetic does not have an error rate, and the
six document layouts are variation this project authored. It is a regression
measure over a known population, not an estimate for a real inbox.

### 2. We show our own AI being wrong

Every financial figure the reasoning agent states is compared against the
computed one before it reaches a screen. That check used to run silently.

Now it is a **trust row** on every case:

```
AI-STATED (INJECTED)   COMPUTED IN CODE   DIFFERENCE
    ₹31,200                ₹25,000        ₹6,200 (24.8%)
    ── struck through ──   ── highlighted ──

  ⛨ Deterministic value used. The AI's figure was discarded.
```

— and a **disagreement ledger** across the portfolio.

The ledger keeps three counts strictly apart, because merging them would turn a
measurement into a marketing figure:

- **model answered** — the only valid denominator for a disagreement rate
- **fallback answered** — the model was unreachable, so it said nothing and
  cannot be credited with agreeing
- **fault injection** — a value we corrupted on purpose, which proves the
  mechanism fires and says nothing about a model

This is the only screen in the product that shows its own AI being wrong. In a
day of demos where every AI is right, that is the thing people remember.

### 3. The cross-case layer is a BigQuery workload, and we say why

The obvious hostile question is *why BigQuery for 320 invoices?* At that size
Python is faster and free, and we say so in the code.

The answer is where the cross-case checks read from. Every one of them —
duplicate, cumulative over-billing, changed bank details, price drift over the
last six invoices, cadence — answers a question about ONE invoice by reading
the vendor's WHOLE history. Firestore serves that with an unfiltered
collection stream. At 320 cases that is free. At the volume a real AP function
runs, it is a full-collection scan per invoice — of exactly the feature that
makes this product different from a per-invoice matcher.

So BigQuery is not an analytics add-on here. **Cross-case investigation is the
differentiator, and cross-case questions are grouped aggregations over
history. That is where the differentiator has to live.**

Both engines are live behind one flag, and a test asserts they agree:
`tests/test_bigquery_parity.py` runs the real SQL through DuckDB offline and
compares every aggregate to the Python, over four windows and a population
seeded with the rows that break naive SQL — a null date, null money, a vendor
with no id. Writing it caught three bugs, including a `GROUP BY` that BigQuery
resolves and DuckDB does not, and naive timestamps that made every computed
age correct in London and wrong in Chennai.

The five analytics are also exposed as MCP Toolbox tools, so an agent can
answer *"which vendors should I audit this quarter?"* by calling one and
reading real rows. **There is no tool that accepts SQL.** The agent picks a
question and a window; it cannot compose an aggregation. That is the same
boundary as everywhere else in this system — a number a human acts on never
comes from a model — enforced at the data layer instead of checked afterwards.

### 4. Every finding traces to a page you can open

The evidence graph is **assembled deterministically** — it is the thing used to
verify everything else, so it cannot be allowed to hallucinate. Five columns:

```
Source documents → Extracted values → Rule applied → Findings → Routing
```

Click any node, land on the PDF it came from.

The provenance is honest at the edge level, too. An earlier version linked every
extracted value to every document on the case, so the graph claimed the unit
price came from the goods receipt *and* the rejection notice. Three of those
four edges were false — on the one screen whose entire job is being checkable.

---

## The numbers

From the current 320-case synthetic portfolio (seeded, reproducible):

| | |
|---|---|
| Invoices analysed | **323** |
| Exceptions | **77** (23.8%) |
| Clean invoices | **246** — the denominator that makes a rate meaningful |
| Found inside one case | 64 · ₹25.85L |
| **Found only across cases** | **13 · ₹10.66L** |
| Of those, with a **full** three-way match | **9 · ₹8.09L** |

That last row is the pitch. Nine invoices whose own documents agreed on
everything, carrying ₹8.09 lakh, that a per-invoice system would have paid.

---

## Why the boundaries are the product

Three places where we deliberately did **less**:

**We report a changed bank account. We do not adjudicate it.** Detecting the
change is exception detection. Asserting the new account is legitimate is
bank-account verification, which this is not. The tool raises the question; a
human answers it through a channel not taken from the invoice.

**We demote recurring bills instead of suppressing them.** A monthly retainer
is re-labelled and dropped down the order — not hidden. A duplicate can hide
inside a recurring series, and an *exact* duplicate is never demoted, or a
fraudster re-sending a rent invoice would be handed the suppression as cover.

**Mock data is never shown because a request failed.** A 500 is a real answer
and is surfaced as an error. The previous behaviour meant an expired token in
front of a judge rendered a complete, confident dashboard of fabricated numbers
with no indication anything was wrong. That failure mode is worse than an error
message.

---

## What we did not build

Naming this is worth more than being caught on it.

- **Credit and debit notes** — the most conspicuous missing document type, and
  it interacts directly with over-billing: a credit note is exactly what would
  resolve that finding, and the running total cannot see it.
- **No OCR by default** — a scanned, image-only PDF fails with a clear message
  rather than being silently processed.
- **The disagreement rate has a small denominator** — the reasoning agent runs
  per case on demand, so unless somebody opens a few hundred cases the
  "model answered" count stays low. The ledger reports the denominator next to
  the rate for exactly that reason.
- **Single workspace, no role enforcement, INR only, PDF only.**

The full list is in [`README.md` §17](README.md).

---

## The demo, in three minutes

| Time | Beat |
|---|---|
| 0:00–0:25 | The crime — two perfect invoices, and every AP system pays both |
| 0:25–1:00 | The trust moment — AI said ₹31,200, code said ₹25,000, code won |
| 1:00–1:50 | One hero case: upload → evidence graph → click a node to the source PDF |
| 1:50–2:30 | The cross-case catch — *"no single-invoice check can see this"* |
| 2:30–2:50 | Portfolio analytics — which vendors to audit, and why |
| 2:50–3:00 | Limitations, in our own words |

Full script: [`DEMO_GUIDE.md`](DEMO_GUIDE.md).

---

## Built on

Google ADK · Gemini 3.5 Flash / Flash-Lite · BigQuery · MCP Toolbox for
Databases · Cloud Run · Cloud Firestore · Cloud Storage · Firebase Auth ·
Firebase Hosting · Secret Manager — all in `asia-south1`.

**231 tests. Two eval harnesses. Zero contrast failures in either theme.**

> Synthetic data only. Every vendor, invoice, amount and document is
> fabricated. No real company, contract or payment is represented.

---

## See also

- [`USER_GUIDE.md`](USER_GUIDE.md) — who it is for and how to use it
- [`ARCHITECTURE_BACKEND.md`](ARCHITECTURE_BACKEND.md) · [`ARCHITECTURE_FRONTEND.md`](ARCHITECTURE_FRONTEND.md)
- [`GOOGLE_STACK.md`](GOOGLE_STACK.md)
