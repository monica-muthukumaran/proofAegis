# The Most Dangerous Output Is a Confident One

### We built a system to stop AI from inventing financial figures. Then our own deterministic code invented one.

A supplier sends an invoice. The accounts payable system checks it against the purchase order and the goods receipt note. Quantities agree, rates agree, tax agrees. It is approved and paid, and it should have been.

Six weeks later the same supplier bills for the same work under a new invoice number and a new date. The purchase order still agrees. The goods receipt still agrees. The arithmetic still agrees. It is a flawless document, and the system approves it — because the system is looking at *that invoice*.

The evidence that it is a duplicate is in a different file.

This is not a story about bad software. The three-way match is real, necessary, and every commercial AP product does it correctly. It is also **structurally incapable** of seeing the most expensive failures in accounts payable, because none of them are visible from inside the document they arrive on.

---

## Five failures that live outside the case

**A vendor bills the same work twice under a new number.** The duplicate is in a different case, so the match has nothing to compare against.

**Four instalments each pass, and together exceed the order.** Every one is compared to the order alone. Nobody holds the running total.

**A supplier's bank details quietly change.** The invoice looks completely normal, because it *is* completely normal — apart from twelve digits nobody has a prior copy of.

**A rate creeps three percent a month, inside tolerance every month.** By the fourth month the price is materially above what was agreed, and no single month ever tripped a rule.

**The duplicate rule fires on every rent payment.** The mirror image: nothing inside one case says "this is a schedule," so the honest recurring bill looks exactly like fraud — and the alert gets ignored, along with the real one beside it.

Each of those invoices passes its own check. That is the point. So we built ProofAegis around the opposite question: not *what failed the match*, but *what passed and shouldn't have*.

---

## The boundary we started with

The reflex is to point a language model at the problem. We didn't, and the reason became the organising rule of the codebase:

> **A number a human acts on must never come from a model.**

An analyst reading "over-billed by ₹2,14,000" will hold a payment or open a dispute. If that figure was generated rather than computed, everything downstream — the audit trail, the routing, the recommended action — is confidently wrong in a way that is very hard to catch, because it all looks impeccable.

So matching, tolerance evaluation, financial impact and match score are plain Python, and the five cross-case checks are too. The AI layer gets language and judgement: severity, plain-English explanation, a cited draft to the vendor, and ranked hypotheses about what to check next.

That last agent is the one that earns its place, and its safety property is architectural rather than policed. From a *computed* finding it produces candidate explanations, each paired with the evidence that would settle it — "the vendor applied a revised rate card; look for a price revision notice dated after the order." It cannot fabricate a figure because **its output schema contains no numeric field at all.** There is nothing for a guardrail to catch. As the code puts it: the failure mode was designed out rather than caught.

Every financial figure the reasoning agent *does* state is compared against the computed one and overwritten on any mismatch above one paisa. That check used to run silently — correcting the number and writing a log line nobody reads. A silent safety net proves nothing, so it now surfaces as a trust row on every case and a portfolio ledger that keeps three counts strictly apart: **model answered** (the only valid denominator), **fallback answered** (the model was unreachable, so it cannot be credited with agreeing), and **fault injection** (a value corrupted on purpose, never added to live totals). Merging them would turn a measurement into a marketing figure.

That was the architecture we set out to build, and we were quite pleased with it.

---

## Then the deterministic core fabricated a finding

Somebody uploaded the wrong purchase order into a case. An invoice for 100 steel pipes, matched against an order for 12 office chairs.

The system reported a quantity variance of **211,200** at high risk, with the basis "88 unreceived units × implied unit price."

88 is 100 pipes minus 12 chairs.

Every digit of that finding was fabricated. No model was involved. It came out of plain arithmetic, which is exactly what we had been calling the trustworthy half of the system — and it was phrased identically to a real finding, because it *was* a real finding, computed correctly from a premise nobody had checked.

Every comparison in the matcher took one thing for granted and none of them verified it: that the two documents describe the same transaction.

This reframed the whole project. Confident fabrication is not a property of language models. It is a property of any system that answers a question without checking whether the question makes sense. The model just makes it cheaper.

The fix is a coherence check that runs *before* the variance branches and returns one of three answers with evidence attached: `consistent`, `unverified`, or `contradicted`. What is interesting is where the bar sits, and why:

> Missing a mismatch leaves things as they were — the reviewer sees a variance and, being a person looking at two documents, notices they are unrelated. Wrongly declaring documents unrelated sends them to re-upload files that were fine, and if it happens twice they stop believing the check.

So `contradicted` requires evidence a person would accept, and everything weaker is reported as `unverified` rather than rounded up. The failure modes are not symmetric, so the threshold isn't either.

And zero word overlap is deliberately *not* conclusive on its own, because "Annual maintenance contract" and "AMC renewal Q1 FY26" share no word and are the same transaction. What separates that from the steel-pipes case is the money: the AMC invoice is ₹30,000 against a ₹1,20,000 order, which is what partial billing looks like. Two independent dimensions have to disagree before the system will assert anything — which means legitimate partial billing can never trigger it.

That pattern repeats everywhere once you look for it. Recurring bills are identified by *cadence* — three or more invoices whose gaps cluster with a coefficient of variation under 0.25 — and are re-labelled and demoted rather than suppressed, because an exact duplicate hiding inside a rent series would otherwise be handed the suppression as cover. Goods-versus-services is decided by whether the line items carry HSN or SAC codes, a fact printed on the document, because demanding a goods receipt for a consulting engagement is a finding that should never have existed.

---

## Measuring, including the measurement

Most demos assert accuracy. The pipeline harness runs 320 labelled cases through the shipping code — not a convenient copy of it — and currently scores **1.000 precision and recall across 11 exception types**, including 58 deliberately degraded documents (blank receipt quantities, itemised-only invoices, vendor spelling variants, unreadable dates).

The number only means something because **ground truth is not derived from the code being graded**: fixtures generate document field values with an injected defect and say nothing about the outcome, and the label comes from a second, deliberately naive implementation of the documented policy. A test asserts that independence by source inspection.

The harness paid for itself by finding real defects. Vendor names compared as raw strings turned 21 of 21 spelling variants into false mismatches — precision was actually 0.87. The same identity rule was implemented twice, differently, so an invoice failed to match its own duplicate and the duplicate went unreported. A percentage variance against a zero expected value returned `float("inf")`, which serialised as bare `Infinity` — not valid JSON — so the browser's parse of the *entire* match result failed and a single zero on a purchase order emptied the whole workspace. And a near-duplicate once outranked a bank change, meaning **payment diversion was reported as a possible re-submission**.

Then there is the one still open at the time of writing, which is the most on-brand bug in the repository. The extraction harness reports 97.4% field accuracy over 300 documents. All 35 "failures" are cases where the parser read the document correctly and the harness's expected value was wrong — the fixtures gained deliberate overrides (a different invoice date, a mismatched vendor name, a broken total) and the ground-truth function kept returning the defaults. Every one of those overrides is *the defect the fixture exists to test*.

A harness whose entire selling point is that ground truth is independent of the code being graded had a ground-truth bug. It failed in the safe direction — understating our own accuracy — which is the only reason it survived this long unnoticed. That is the same lesson as the steel pipes, arriving by a different road: the code that checks the work needs its own check, and "it produced a number" is never evidence that the number means anything.

---

## The numbers

From a 320-case synthetic portfolio, seeded and reproducible: **77 exceptions** against **243 clean invoices** — the denominator that makes a rate meaningful. **64** were found inside a single case, worth ₹25.85 lakh. **13** were found only across cases, worth ₹10.66 lakh.

Of those 13, **nine — worth ₹8.09 lakh — scored a full three-way match on their own documents.** Nine invoices whose own paperwork agreed on everything, that a per-invoice system would have paid without hesitation.

Behind that: 427 passing tests, two eval harnesses, and a test that reads the MCP tool manifest as text and asserts every constant it restates still matches its Python source — because the duplicated-identity-rule bug already proved that restated constants drift, and a drifting constant there would be silent.

---

## Where we deliberately did less

**We report a changed bank account. We do not adjudicate it.** Detecting the change is exception detection. Asserting the new account is legitimate is bank-account verification, which this is not. The tool raises the question; a human answers it through a channel not taken from the invoice.

**Analytics fail rather than fall back.** If BigQuery is selected and unreachable, the request errors. It does not quietly serve numbers computed a different way than the response claims — the same reason mock data never appears because a request failed. A confident wrong answer is worse than an error message.

And the honest gaps: no credit or debit notes, the missing document type that interacts most directly with over-billing. No OCR by default. Single workspace, INR only, PDF only. The disagreement ledger is process-local and its denominator is small, which is why the rate is always shown next to the count.

---

Naming the limits is not modesty. In a system whose entire proposition is that its numbers can be checked, the boundary *is* the product — and the failure worth designing against was never "the AI might make something up." It was that **anything in the stack can produce a confident, well-formatted, completely fabricated answer**, and the only defence is a layer whose job is to doubt the one below it.

*ProofAegis runs on Google ADK, Gemini, BigQuery, Cloud Run, Firestore, Cloud Storage and Firebase. All data is synthetic — every vendor, invoice, amount and document is fabricated, and no real company, contract or payment is represented.*
