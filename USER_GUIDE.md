# ProofAegis — User Guide

Everything you can do in the application, who it is for, and what to expect.

> **Synthetic data only.** Every vendor, invoice, amount and document is
> fabricated. ProofAegis does not release payments and does not verify bank
> accounts. Nothing it produces should be acted on without human review.

---

## Contents

1. [Who this is for](#1-who-this-is-for)
2. [What it does, and what it does not](#2-what-it-does-and-what-it-does-not)
3. [Where to start](#3-where-to-start)
4. [The screens](#4-the-screens)
5. [Walkthrough — resolving one exception](#5-walkthrough--resolving-one-exception)
6. [Reading a finding](#6-reading-a-finding)
7. [The twelve exception types](#7-the-twelve-exception-types)
8. [Uploading your own documents](#8-uploading-your-own-documents)
9. [Keyboard shortcuts and conveniences](#9-keyboard-shortcuts-and-conveniences)
10. [What the AI does, and how to tell](#10-what-the-ai-does-and-how-to-tell)
11. [Troubleshooting](#11-troubleshooting)
12. [Limits you should know about](#12-limits-you-should-know-about)

---

## 1. Who this is for

| Role | What you get |
|---|---|
| **Accounts Payable analyst** | A blocked invoice explained in plain English, with every number traceable to the page it came from, and a drafted message you can send |
| **Procurement** | Cases routed to you with the specific price or quantity question already isolated, plus which vendors are drifting |
| **Receiving** | Cases waiting on a goods receipt, with the exact quantity gap stated |
| **Financial controller** | Where the next exceptions will come from — vendor exception rates, value at risk, ageing against SLA |
| **Internal audit** | A complete evidence chain and audit trail per case, and a measured record of every time the system's own AI was overruled |

**You do not need to be technical.** If you can read an invoice, you can use
this. Everything numeric is computed and shown with its working.

---

## 2. What it does, and what it does not

### It does

- Reads invoice-related PDFs and pulls out the fields that matter
- Runs a two-way and three-way match with configurable tolerances
- Calculates the money at risk **in code**, and shows the arithmetic
- Finds problems that **no single invoice can reveal** — duplicates,
  cumulative over-billing, changed bank details, price drift
- Traces every finding back to a document page you can open
- Suggests what to check next, and drafts a cited message to the right team
- Records every human action in an audit trail

### It does not

- Release payments
- Verify that a bank account is legitimate — it reports that one **changed**
- Approve or reject anything on its own. **Every AI output is review-only**
- Replace your ERP
- Give legal or tax advice

---

## 3. Where to start

You have two doors.

### Door 1 — the guided tour (no account needed)

From the entry screen, choose **Start guided tour**. Ten steps, about two
minutes, following one blocked invoice from its source documents through the
evidence graph to a cited resolution draft. No login, no backend required.

**Start here if you have never seen the product.**

At the end you can keep exploring as a guest or sign in.

### Door 2 — sign in

Use your account. If the deployment is running without a Firebase project, the
demo account is:

```
judge@demo.proofaegis.local
demo-only
```

You land on the **Dashboard**.

---

## 4. The screens

### Dashboard — *what needs me today*

Four figures at the top:

| Card | Meaning |
|---|---|
| **Open exceptions** | Cases still consuming someone's attention |
| **Value on hold** | Money blocked pending review |
| **Awaiting action** | Cases sitting with a named team |
| **Average match score** | How much of what could be checked, agreed |

Below: the highest-priority case, the exception-type distribution, and recent
activity.

The coloured chips near the top are the **mode banner** — whether the API is
connected, whether data is seeded or live, where files are stored, and whether
Gemini is on. If it says *"Gemini off — deterministic extraction"*, the app is
reading documents with its own parser, and nothing on screen came from a model.

### Exceptions — *the queue*

Every case that could not clear automatically. Cleared invoices are one filter
away — they matter, because an exception **rate** needs a denominator.

- Search by exception, invoice, vendor or PO
- Filter by type, risk and status
- Sort any column
- The coloured rail on the left of a row is its risk level

Filtering and sorting happen instantly in your browser.

### Exception detail — *the investigation*

Seven tabs. Covered in detail in §5.

### Analytics — *what shouldn't have passed*

Ordered as an argument:

1. **What a per-invoice check would have missed** — the headline. How many
   findings needed the rest of the workspace, what they are worth, and how many
   of them scored a *full* three-way match on their own documents.
2. **Portfolio KPIs** — invoices analysed, clean rate, exception rate, value at
   risk.
3. **Disagreement ledger** — how often the code had to overrule the AI.
4. **Measured accuracy** — the eval results, with every disagreement named.
5. **Vendors to act on**, monthly trend, and ageing against a 14-day SLA.

Every figure on this screen is arithmetic over stored outcomes. No model
produces a number here, and the page says so.

### Settings

The tolerance rules currently in force, and which rule applied — workspace
default, a category rule, or a vendor-specific one. Read-only in this build.

---

## 5. Walkthrough — resolving one exception

Open **EXC-2026-0001** (Chennai Industrial Supplies).

### Tab 1 — Summary

What was found, in a sentence, and what is still outstanding. Start here.

### Tab 2 — Documents

Every document on the case: type, extraction confidence, and a preview.

Click one. The PDF appears beside the fields that were pulled out of it, so you
can check the extraction against the page yourself. A field the system could not
find reads **"not stated"** — never a zero, because *not stated* and *zero* are
different facts.

### Tab 3 — Match

The heart of it.

**Tolerance bands** draw each variance to scale — the shaded zone is what was
allowed, the marker is where this invoice landed. You can see *how far* outside
tolerance something is, not just that it was.

**The trust row** shows what the AI said the money was, next to what the code
computed:

```
AI-STATED (INJECTED)   COMPUTED IN CODE   DIFFERENCE
    ₹31,200                ₹25,000        ₹6,200 (24.8%)

  ⛨ Deterministic value used. The AI's figure was discarded.
```

**The comparison table** lists every field checked, with expected, actual,
variance, tolerance and result. Breached rows are tinted.

**Line by line** appears when both documents are itemised — a single
overcharged line can hide inside an order whose total still looks fine.

If the finding came from looking across cases, a banner says so at the top.

### Tab 4 — Evidence graph

The provenance chain, left to right:

```
Source documents → Extracted values → Rule applied → Findings → Routing
```

- **Hover** any node to light up its evidence chain and dim everything else
- **Click** a node to open its source detail
- **Drag** to rearrange a dense case
- **Text view** for a linear, screen-reader-friendly version

Each node is colour-coded *and* labelled with its type, so you never have to
rely on colour alone.

### Tab 5 — Investigate

Ranked candidate explanations for the finding, each with the evidence that
would confirm or rule it out:

> **1. The vendor has applied a revised rate card that we do not have on file.**
> Check: a price revision notice or updated rate card dated after the purchase
> order.
> Confirms it if a revision exists and its effective date precedes the invoice.
> Rules it out if none exists, or its date is after this invoice.

**This tells you what to look at. It never concludes.** If the badge says
*"generic checklist — model unavailable"*, the ranking is a fixed list rather
than reasoned against this vendor's history.

### Tab 6 — Resolution

A drafted message to the responsible team or the vendor. Every claim carries a
citation you can click through to its source document.

**You send it. The system never does.**

### Tab 7 — Audit trail

Every state change, who made it, when, and any note attached.

### Then: set a status

From the header, move the case to `awaiting_procurement`,
`awaiting_receiving`, `awaiting_vendor`, `approved_with_exception`, `resolved`
or `closed`. Add a note; it goes into the audit trail.

Re-analysis will never drag a case back out of a status you set.

---

## 6. Reading a finding

Four things appear on every case. Here is how to read them.

**Exception type** — the single most important thing wrong. When several things
are wrong at once, you get the one you must act on *first*: a duplicate outranks
a price variance, because if it is a duplicate you should not pay it at all and
the variance stops mattering.

**Financial impact** — the money at risk, with its basis stated. A variance
exposes the size of the gap; a missing document exposes the whole invoice. It
is **exposure surfaced for review**, not a claim of loss prevented.

**Match score** — what share of the checks that *could* run, agreed. A
comparison is never counted against you because a document is legitimately
missing.

> A **100% match score next to "high risk"** is not a contradiction. The score
> measures whether the documents on file agree. The finding can be about a
> document that is *not* on file — or about the other invoices in the
> workspace. The "What is outstanding" sentence explains which.

**Risk level** — low, medium or high, from the size and nature of the finding.

---

## 7. The twelve exception types

### Found inside one case

| Type | Meaning |
|---|---|
| `price_variance` | Billed above the ordered rate, beyond tolerance |
| `quantity_variance` | Billed for more than was received |
| `missing_goods_receipt` | Nothing confirms delivery or completion |
| `missing_purchase_order` | No authorising order on file |
| `vendor_mismatch` | Billed by someone other than who was ordered from |
| `tax_total_mismatch` | The invoice does not add up against itself |
| `no_exception` | Everything agreed. A real outcome — the evidence chain proves it is payable |

### Found only by looking across cases

These are the ones a per-invoice system cannot reach. **Every one of them can
fire on an invoice whose own three-way match is clean.**

| Type | Meaning |
|---|---|
| `duplicate_invoice` | This bill appears to have been submitted already |
| `po_over_billed` | Several invoices, each fine alone, together exceed the order |
| `payment_details_changed` | Same vendor, different bank account than last time |
| `vendor_price_drift` | A rate climbing steadily — inside tolerance every month, materially above the agreed price by the fourth |
| `recurring_suspected` | A recognised billing schedule — rent, a retainer, an AMC. **Not** a duplicate |

### About `recurring_suspected`

"Same vendor, same amount, close in time" describes a genuine duplicate. It
also describes every rent payment in the ledger.

When the same amount arrives on a **regular cadence** — three or more times at a
consistent interval — it is reported here at low severity with **no money booked
as at risk**, instead of at the top of the case as a duplicate.

It is still reported, because a duplicate can hide inside a recurring series.
And an **exact** duplicate (same invoice number) is never demoted this way.

### About `payment_details_changed`

The system reports that a vendor's bank details **changed**. It does not judge
whether the new account is legitimate — that is bank-account verification, which
this product is not.

**Confirm the change through a channel you already trust — never a phone number
or address taken from the invoice itself.**

---

## 8. Uploading your own documents

**New case from PDFs** on the Dashboard, or **Add documents** on an existing
case.

| | |
|---|---|
| Format | PDF only |
| Size | up to 15 MB per file |
| Per upload | up to 20 files |
| Per case | **no limit** — a real investigation accumulates evidence over days |

### What it understands

Vendor invoice · Purchase order · Goods receipt note · Rejection notice ·
Quotation.

Types are detected automatically. **When the evidence is thin, it asks you
rather than guessing** — a misfiled document silently corrupts the comparison.

### What happens

1. Each file is validated and stored
2. Text is pulled out and fields extracted
3. Documents are linked by the order reference the invoice names — **not by
   which arrived most recently**. If they had to be paired by recency, the case
   says so
4. The match runs
5. Cross-case checks run against everything else in the workspace

You can watch it, per document, while it happens.

### Try it now

Sample PDFs live in `backend/data/synthetic_cases/`. Regenerate them, or
produce them in five other document layouts:

```bash
cd backend && ./venv/Scripts/python.exe scripts/generate_synthetic_pdfs.py
```
```bash
cd backend && ./venv/Scripts/python.exe scripts/generate_synthetic_pdfs.py --all-layouts --out data/layout_variants
```

`missing_receipt_001` has no goods receipt **on purpose** — that absence is the
finding.

---

## 9. Keyboard shortcuts and conveniences

| Shortcut | Does |
|---|---|
| `Ctrl`/`Cmd` + `K` | Command palette — jump to any screen or search cases |
| `Enter` / `Space` | Activate a focused row or graph node |
| `Tab` | Move through everything; focus is always visible |

**Theme** — light, dark, or follow your system. Toggle in the topbar.

**Deep links** — `/exceptions/EXC-2026-0001` is a real URL. Share it; it
survives a refresh.

---

## 10. What the AI does, and how to tell

Four AI agents, and they are kept away from the arithmetic.

| The AI writes | The code computes |
|---|---|
| Field extraction (with a deterministic fallback) | Every variance and percentage |
| Severity and the plain-English description | Financial impact |
| Ranked hypotheses about what to check | Match score |
| The resolution draft | The exception type |
| | The evidence graph |
| | Every analytics figure |

### How to tell what you are looking at

- Anything AI-generated is **labelled** and marked review-only
- The mode banner says whether Gemini is on at all
- The **trust row** on each case shows what the AI said next to what the code
  computed, and which one was used
- The **disagreement ledger** on Analytics counts how often they differed

**The deterministic value always wins.** There is no gap size at which the AI's
number would be preferred.

### The injected fault

On `EXC-2026-0001` the trust row shows the AI stating **₹31,200** against a
computed **₹25,000**, and says *"Injected fault — a figure corrupted on purpose
so the check can be watched running. Not model output."*

That is real: a deliberately wrong value, so you can watch the guardrail fire
rather than take our word for it. It is counted separately from anything a live
model actually did.

---

## 11. Troubleshooting

| You see | What it means | Do this |
|---|---|---|
| *"Cannot reach the ProofAegis API"* | Backend is down or starting | Wait a few seconds and retry — a scaled-to-zero service takes a moment to wake |
| *"Your session has expired"* | Token lapsed | Sign in again |
| *"This case needs a readable vendor invoice"* | No usable invoice yet | Add one. Everything else is optional |
| *"Could not tell what kind of document this is"* | Classification evidence was too thin | Set the type manually — better than a wrong guess |
| A scanned PDF is rejected | Image-only, OCR is off | Use a PDF with a real text layer, or enable OCR server-side |
| Fields read **"not stated"** | The value was not found | Open the preview and check the page. Not-stated is never treated as zero |
| *"Check these documents belong together"* | Documents were paired by recency, not a matching reference | Confirm they describe the same order |
| Badge: *"generic checklist — model unavailable"* | The model did not answer | Hypotheses are a fixed list, not ranked for this vendor. Everything computed is unaffected |
| A monthly bill flagged | Expected | Check whether it says `duplicate_invoice` or `recurring_suspected` — they mean opposite things |

---

## 12. Limits you should know about

Stated plainly, because a tool that hides these is worse than one that names
them.

- **PDF only.** No email bodies, images or spreadsheets.
- **No OCR by default.** A scanned, image-only PDF is refused with a clear
  message rather than silently processed.
- **INR only.** No currency conversion.
- **Single workspace.** Every signed-in user sees the same workspace. This is
  not multi-tenant isolation.
- **No role enforcement.** Any authenticated user can set any user-settable
  status.
- **No credit or debit notes.** The most conspicuous missing document type, and
  it interacts directly with over-billing — a credit note is exactly what would
  resolve that finding, and the running total cannot see it.
- **Recurring detection needs three occurrences and readable dates.** A retainer
  that has only billed twice is still reported as a near-duplicate. That default
  is deliberate: a missed duplicate costs more than a noisy one.
- **Price drift needs a single-line document and a stable item description.** A
  multi-line invoice has no one unit price to trend. It returns no finding
  rather than a guess.
- **The disagreement ledger is per server session.** Restarting the backend
  resets it.

The complete list is in [`README.md` §17](README.md).

---

## See also

- [`PITCH.md`](PITCH.md) — why this exists
- [`DEMO_GUIDE.md`](DEMO_GUIDE.md) — the three-minute script
- [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) — running it yourself
