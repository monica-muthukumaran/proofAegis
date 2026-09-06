# Backend Architecture

**ProofAegis API — Flask + Google ADK on Cloud Run.**

Everything in this document describes code that exists in `backend/` today.
Line counts, endpoint paths, and figures were read out of the repository, not
remembered.

> Synthetic data only. Every vendor, invoice, amount, and document in this
> repository is fabricated.

---

## Contents

1. [The one rule the whole design follows](#1-the-one-rule-the-whole-design-follows)
2. [Request flow](#2-request-flow)
3. [Module map](#3-module-map)
4. [The deterministic core](#4-the-deterministic-core)
5. [The cross-case layer](#5-the-cross-case-layer)
6. [The AI layer — four ADK agents](#6-the-ai-layer--four-adk-agents)
7. [The trust ledger](#7-the-trust-ledger)
8. [Data model](#8-data-model)
9. [Persistence](#9-persistence)
10. [Complete API reference](#10-complete-api-reference)
11. [Authentication](#11-authentication)
12. [Configuration](#12-configuration)
13. [The eval harness](#13-the-eval-harness)
14. [Tests](#14-tests)
15. [Failure behaviour](#15-failure-behaviour)

---

## 1. The one rule the whole design follows

**A number a human acts on never comes from a model.**

Every architectural decision below is downstream of that sentence. It is why
matching is plain Python, why the evidence graph is assembled rather than
generated, why the AI layer's outputs are checked against the deterministic
ones before they reach a screen, and why the fourth agent's output schema has
no numeric field in it at all.

| Layer | Who does it | Module |
|---|---|---|
| Matching, tolerance evaluation, financial impact, match score | **Deterministic code** | `services/matching_service.py` |
| Cross-case findings — duplicates, over-billing, payment changes, drift, recurrence | **Deterministic code** | `services/history_service.py` |
| Evidence graph assembly | **Deterministic code** | `services/graph_service.py` |
| Portfolio analytics — rates, value at risk, ageing, trend, cross-case split | **Deterministic code** | `services/analytics_service.py` |
| Document classification and field extraction | Gemini via ADK, deterministic parser fallback | `services/document_agent.py`, `services/pdf_field_parser.py` |
| Severity, plain-language description, recommended action | Gemini via ADK | `services/exception_agent.py` |
| Resolution draft with enforced citations | Gemini via ADK | `services/resolution_agent.py` |
| Ranked candidate explanations — what to check next | Gemini via ADK | `services/hypothesis_agent.py` |

---

## 2. Request flow

### 2.1 Upload → finding

```
POST /api/exceptions                      create an empty case
        │
POST /api/exceptions/<id>/documents       one or more PDFs, multipart
        │
        ├─ ingestion_service.validate_upload      extension, size, magic bytes
        ├─ ingestion_service.extract_text_from_bytes   PyMuPDF text layer
        │     └─ (optional) extract_text_with_ocr      only if no text layer
        │                                              AND OCR_ENABLED
        ├─ pdf_field_parser.classify_document      scored, refuses to guess
        ├─ document_agent.extract_fields           Gemini (ADK, output_schema)
        │     └─ fallback → pdf_field_parser.parse_document
        ├─ storage_service.upload                  GCS or local mirror
        │
        └─ ingestion_service.run_analysis
              ├─ build_matching_input             pairs PO/GRN to the invoice
              │     └─ history_service.*          the cross-case queries
              ├─ case_service.tolerance_for       vendor > category > default
              └─ matching_service.evaluate_exception
                      → MatchResult (type, impact, score, risk, comparisons)
```

`run_analysis` is idempotent. It rebuilds `matching_input` from every document
currently on the case and re-runs the matcher, so uploading a late goods
receipt three days later produces a correct result with no special path.

### 2.2 Finding → explanation

These are separate, on-demand endpoints. Nothing calls a model during upload.

```
POST /api/exceptions/<id>/reasoning/generate   severity + description
POST /api/exceptions/<id>/hypotheses/generate  what to check next
POST /api/exceptions/<id>/resolution/generate  cited draft message
GET  /api/exceptions/<id>/graph                evidence graph (deterministic)
GET  /api/exceptions/<id>/trust                the guardrail's own record
```

---

## 3. Module map

```
backend/
├── app.py                    Flask factory, CORS, blueprints, error handlers
├── config.py                 every env var read in one place
├── auth.py                   @require_auth decorator
├── datastore.py              repository layer — InMemory | Firestore
├── schemas.py                Pydantic models; ADK output_schema contracts
│
├── routes/
│   ├── exceptions.py   (500) cases, documents, match, graph, reasoning,
│   │                         hypotheses, trust, resolution, audit, status
│   ├── analytics.py    (156) overview, cross-case, accuracy, trust,
│   │                         vendor-risk, trends, ageing
│   ├── dashboard.py     (74) queue summary
│   ├── settings.py      (49) tolerance rules, runtime mode
│   ├── auth.py          (24) whoami
│   └── intake.py        (95) email intake status + manual poll
│
├── services/
│   ├── matching_service.py    (963) three-way match, tolerance, impact
│   ├── pdf_field_parser.py    (902) deterministic extraction from PDF text
│   ├── ingestion_service.py   (812) validate, extract, link, analyse
│   ├── history_service.py     (600) the cross-case checks
│   ├── analytics_service.py   (443) portfolio aggregation
│   ├── case_service.py        (236) glue: fetch → match → graph
│   ├── hypothesis_agent.py    (223) ADK agent 4
│   ├── trust_ledger.py        (213) AI-vs-deterministic record
│   ├── graph_service.py       (187) evidence graph assembly
│   ├── email_intake.py        (179) IMAP → cases
│   ├── exception_agent.py     (176) ADK agent 2 + the guardrail
│   ├── storage_service.py     (162) GCS with an on-disk mirror
│   ├── document_agent.py      (161) ADK agent 1
│   ├── approval_service.py    (133) approval policy checks
│   ├── resolution_agent.py     (84) ADK agent 3
│   ├── ai_fallback.py          (69) retry + fall back to deterministic
│   ├── auth_service.py         (66) Firebase ID token verification
│   └── audit_service.py        (29) audit event construction
│
├── mock_data/
│   ├── seed_cases.json         the three hero cases
│   ├── mock_extractions.py     hand-written outputs + FAULT_INJECTED_CASES
│   ├── generic_mocks.py        template fallbacks over a real MatchResult
│   └── hypothesis_fallback.py  catalogue fallback for agent 4
│
├── eval/
│   ├── fixtures.py             labelled portfolio — documents, not answers
│   ├── run_eval.py             scores the pipeline
│   └── extraction_eval.py      scores extraction across 6 layouts
│
├── scripts/
│   ├── generate_synthetic_data.py   the 320-case portfolio
│   ├── generate_synthetic_pdfs.py   demo PDFs, any layout
│   ├── pdf_layouts.py               6 document dialects
│   └── seed_firestore.py            push seed + portfolio to Firestore
│
└── tests/                      231 tests, 18 files
```

---

## 4. The deterministic core

### 4.1 `matching_service.py`

The formulas, verbatim from the requirements:

```
absolute_variance   = actual_value - expected_value
percentage_variance = absolute_variance / expected_value * 100
match_score         = round(100 * matched_count / evaluable_count)
```

`evaluable_count` counts only comparisons where **both** sides existed. A
comparison is never penalised because a document is legitimately missing —
that absence is its own exception type.

**Comparison fields:** `vendor`, `po_number`, `quantity`, `unit_price`, `tax`,
`total`, `subtotal`, `line_items`, `tax_arithmetic`, `quoted_price`,
`po_billed_total`.

**Classifications:** `matched`, `within_tolerance`, `outside_tolerance`,
`missing`, `unable_to_verify`, `requires_human_review`.

Three pieces of judgement worth knowing about:

**Vendor identity.** Names are compared through `vendor_key()`, which folds
legal form (`Pvt.`/`Private`, `Ltd.`/`Limited`), the `M/s` honorific, `&`
versus `and`, and punctuation — and nothing else. Two suppliers differing in
an actual word still compare as different. Before this existed the eval
measured 21 false `vendor_mismatch` results out of 21 spelling variants, which
took detection precision from 1.00 to 0.87 on its own.

**Tax basis.** A tax-inclusive total compared against a tax-exclusive one is a
units error, not a variance — a PO quoted ex-GST at ₹53,000 against an invoice
of ₹62,540 is an 18% "breach" that describes the tax rate. `tax_basis()`
establishes whether each side is `gross`, `net` or `unknown` from what the
document itself shows, and the totals row reports `unable_to_verify` rather
than inventing a variance.

**Line-level comparison.** A single overcharged line can hide inside an order
whose total still looks acceptable, so `compare_line_items()` pairs each PO
line with the invoice line that bills it (by description, then by position)
and reports unpaired lines rather than dropping them.

### 4.2 Exception precedence

The matcher returns exactly one `exception_type`, ordered by what a reviewer
must act on first:

| # | Type | Why here |
|---|---|---|
| 1 | `duplicate_invoice` (exact) | Same vendor + invoice number. Do not pay at all — every variance becomes irrelevant |
| 2 | `payment_details_changed` | A fraud indicator about *where money goes*. Must not be buried by a suspicion about the amount |
| 3 | `po_over_billed` | Running total exceeds the order across several invoices |
| 4 | `duplicate_invoice` (near) | Same vendor + amount, different number, within 90 days |
| 5 | `tax_total_mismatch` | The invoice does not reconcile against itself |
| 6 | `vendor_mismatch` | Billed by someone other than who was ordered from |
| 7 | `missing_purchase_order` | Nothing to match against |
| 8 | `missing_goods_receipt` | Nothing confirms delivery |
| 9 | `quantity_variance` | Invoiced above what was received |
| 10 | `price_variance` | Invoiced above the ordered rate |
| 11 | `recurring_suspected` | A recognised billing schedule — a note, not a variance |
| 12 | `vendor_price_drift` | A rate that crept; this invoice passes on its own |
| — | `no_exception` | A real outcome. The evidence chain still proves the invoice is payable |

Positions 2 and 4 used to be a single branch. The eval harness caught it: an
invoice for a familiar amount from a familiar vendor with an *unfamiliar bank
account* was reported as a possible re-submission — which is precisely the
payment-diversion pattern, described in a way that sends the reviewer to check
the wrong thing.

---

## 5. The cross-case layer

`services/history_service.py`. These are the checks a single case cannot
perform on itself, and they are the product's actual claim. All deterministic.

| Function | Finds | Method |
|---|---|---|
| `find_duplicate_invoices` | exact / near / recurring | vendor + number, or vendor + amount within 90 days |
| `detect_recurring_pattern` | a billing schedule | ≥3 occurrences, interval CV ≤ 0.25, mean gap 20–400 days |
| `cumulative_billing` | over-billing across instalments | running total against the order value |
| `find_payment_detail_changes` | a changed bank account | compares only the vendor's most recent prior invoice |
| `detect_price_drift` | a creeping rate | OLS fit over (months, unit price), ≥4 points, majority of steps rising |

### 5.1 Recurring suppression — why it matters

"Same vendor, same amount, within 90 days" finds a genuine re-submission. It
also fires on every rent payment, retainer, AMC and subscription in the
ledger — and `duplicate_invoice` outranks everything, so the false positive is
loud.

What separates them is **cadence**. Three or more invoices whose gaps cluster
tightly around a common period is a billing schedule, not an accident. The
finding is re-labelled `recurring_suspected`, dropped to low severity, and
booked at **zero** financial impact — counting every month's rent as
value-at-risk would make the portfolio headline meaningless.

Two guards keep this honest:

- An **exact** duplicate is never demoted. A fraudster re-sending a rent
  invoice would otherwise be handed the suppression as cover.
- Unparseable dates return `None`, meaning "no evidence of a schedule". The
  burden of proof sits entirely on the suppression side, because a missed
  duplicate costs more than a noisy one.

### 5.2 Boundary — payment details

Detecting that a bank account **changed** is exception detection and belongs
here. Asserting the new account is **legitimate** would be bank-account
verification, which this product explicitly is not. The module raises the
question; a human answers it, through a channel not taken from the invoice.

---

## 6. The AI layer — four ADK agents

All four use `google-adk` `LlmAgent` with a Pydantic `output_schema`, so ADK
validates the model's response at the framework level.

**They reach Gemini through Vertex AI**, not the AI Studio Developer API —
`GOOGLE_GENAI_USE_VERTEXAI=true`, `GOOGLE_CLOUD_LOCATION=global`. That is a
billing decision (Vertex bills the Cloud project; the Developer API bills a
separate AI Studio prepay wallet) and no agent code knows about it. See
[`GOOGLE_STACK.md` §5.1](GOOGLE_STACK.md#51-which-gemini-backend--and-why-it-is-vertex). A validation failure
and an unreachable model are handled identically: fall back to a deterministic
path (`services/ai_fallback.py`), and label the result `source: "mock"`.

| # | Agent | Model | Output schema | Fallback |
|---|---|---|---|---|
| 1 | `document_agent` | `gemini-3.5-flash-lite` | `InvoiceExtraction` etc. | `pdf_field_parser` — reads the real bytes |
| 2 | `exception_agent` | `gemini-3.5-flash` | `ExceptionReasoning` | template over the computed `MatchResult` |
| 3 | `resolution_agent` | `gemini-3.5-flash` | `ResolutionDraft` | cited template |
| 4 | `hypothesis_agent` | `gemini-3.5-flash` | `HypothesisSet` | fixed catalogue by exception type |

Extraction gets the fast model deliberately: it is a structured, low-judgement
task, and the floating `-latest` aliases were measured at 75s (and 503s) for
work a pinned flash-lite answers identically in ~1.4s.

### 6.1 Agent 4 — the one doing work a template cannot

Agents 1–3 all have fallbacks that are *nearly as good as the model*, which is
a fair criticism of the whole AI layer: if a template does the job, the model
is decoration.

Agent 4 is given the job a template genuinely cannot do. From a computed
finding it produces **ranked candidate explanations, each paired with the
evidence that would confirm or rule it out**:

> Price variance of 10.42%. Candidates: (a) the vendor applied a revised rate
> card — look for a price revision notice dated after the order; (b) our PO
> carries a stale rate — check the quotation it was raised from; (c) the wrong
> line was matched — compare the HSN codes.

Ranking those requires weighing each cause against what this vendor has been
doing for six months. A lookup table can list causes; it cannot know that this
supplier's rate has climbed since April and that "one-off keying error" is
therefore the least likely item on the list.

**The safety property is structural, not enforced.** `HypothesisSet` has no
numeric field. There is nothing for a guardrail to check because the failure
mode was designed out. The agent is also passed only *qualitative* vendor
context — no amounts — because an instruction not to use a number is weaker
than the number not being there.

Its fallback is deliberately **worse** than the model, and the UI says so
("generic checklist — model unavailable"). The value of a hypothesis set is
the ranking, and a fixed catalogue has none.

---

## 7. The trust ledger

`services/trust_ledger.py`. `exception_agent` has always overwritten the
model's stated `financial_impact` with the computed one. It used to do that
silently, which meant the most defensible property of the architecture was
visible only to someone tailing stderr.

Every comparison now produces a `TrustCheck` — **agreements included**, because
a fire rate with no denominator is not a measurement.

```
ai_value → compared against → computed_value
   │
   ├─ difference ≤ ₹0.01  → agreement, recorded
   └─ difference >  ₹0.01 → OVERRIDE: deterministic value wins, recorded
```

There is no band in which the model's number is preferred, at any size of gap,
for any reason.

### 7.1 Three counts kept strictly apart

Merging these would turn a measurement into a marketing figure:

| Count | Meaning | Counts toward the rate? |
|---|---|---|
| `model_answered` | A live model produced a figure | **Yes** — the only valid denominator |
| `fallback_answered` | Model unreachable; template stood in | **No.** The model said nothing, so there is nothing for it to have agreed with. Counting these would manufacture a perfect record out of an outage |
| `fault_injection` | A value corrupted on purpose | **No.** Proves the mechanism fires; says nothing about a model |

`overrides_applied` counts overrides from *any* source, so the summary can
never claim "no override required" while one sits in its own recent-overrides
table.

### 7.2 The seeded fault

`EXC-2026-0001` carries a deliberately wrong stated impact — **₹31,200 against
a computed ₹25,000** — so the override can be watched firing rather than
described. It fires deterministically whether or not Gemini is reachable
(`DEMO_FAULT_INJECTION`, default on).

The honesty cost is paid in full: stamped `kind="fault_injection"`, excluded
from every model statistic, and labelled in the UI as *"Injected fault — a
figure corrupted on purpose so the check can be watched running. Not model
output."* Turn it off with `DEMO_FAULT_INJECTION=false`.

---

## 8. Data model

`schemas.py`. These Pydantic models are used twice: as ADK `output_schema`
contracts, and as the shape of API responses.

### 8.1 Extraction schemas

`InvoiceExtraction`, `PurchaseOrderExtraction`, `GoodsReceiptExtraction`,
`QuotationExtraction`, `RejectionNoticeExtraction`.

Two details that carry weight:

- **`line_items: List[LineItem]`.** Real POs and invoices are multi-line.
  Forcing a three-line document into a single `quantity`/`unit_price` pair did
  not merely lose detail, it produced *wrong numbers* — the extractor returned
  `quantity=3`, the row count, next to the first row's unit price. On a
  multi-row document the scalar pair is now `None`, and a comparison against
  `None` is reported as "missing", which is the honest outcome.
- **Bank fields** (`bank_account_number`, `bank_ifsc`, `bank_name`) are stored
  per invoice so a change against the vendor's previous invoice is detectable.

### 8.2 `MatchResult`

The central object. Carries `exception_type`, `comparisons`,
`line_comparisons`, `match_score`, `financial_impact`,
`financial_impact_basis`, `recommended_owner`, `risk_level`, plus the
cross-case payloads (`duplicate_of`, `po_billing`, `payment_detail_changes`,
`price_drift`) and a `cross_case: bool` flag.

`cross_case` is set once, in the matcher, and the analytics partition on it —
so the headline figure cannot drift away from what the matcher actually does.
`CROSS_CASE_TYPE_VALUES` in `schemas.py` is the single declaration, and
`tests/test_cross_case_and_identity.py` asserts every copy agrees with it.

### 8.3 Status model

**System-set** (pipeline owns these): `received`, `processing`,
`exception_detected`, `assigned`, `cleared`.

**User-settable**: `awaiting_procurement`, `awaiting_receiving`,
`awaiting_vendor`, `approved_with_exception`, `resolved`, `closed`.

The pipeline only writes a status while the case is still in a system-set
state. Once a human moves it to `awaiting_vendor`, re-analysis cannot yank it
back.

---

## 9. Persistence

`datastore.py` is a repository layer so routes never touch Firestore directly.
Two implementations behind one interface, chosen once at import by
`config.USE_MOCK_DATA`:

- **`InMemoryDatastore`** — seeded from `mock_data/seed_cases.json`, plus
  `data/generated/portfolio.json` when present. What the test suite runs
  against.
- **`FirestoreDatastore`** — real reads and writes.

### 9.1 Firestore collections

| Collection | Holds |
|---|---|
| `invoice_exceptions` | the case record |
| `documents` | per-document metadata + extraction |
| `exception_reasoning` | agent 2 output, cached |
| `investigation_hypotheses` | agent 4 output, cached |
| `resolution_drafts` | agent 3 output, cached |
| `audit_events` | FR-012 audit trail |
| `settings` | `tolerance_rules`, `approval_policy` |

One composite index is needed: `documents(document_type, processing_state)`,
for the cross-case query. Firestore prints the creation link on the first call
if it is missing.

### 9.2 Object storage

`services/storage_service.py`. Path shape:

```
workspaces/{workspace_id}/cases/{exception_id}/{document_id}.pdf
```

`STORAGE_BACKEND=auto` uses GCS when a bucket **and** credentials are both
present, otherwise writes to `LOCAL_STORAGE_DIR` — an on-disk mirror of the
exact same object paths, so local development and the test suite exercise the
real ingestion code end to end with zero cloud calls. The test suite pins
`local`, so a developer machine holding real credentials can never have a test
run reach a live bucket.

Documents are served through an authenticated route
(`GET /api/exceptions/<id>/documents/<doc_id>/content`), never a bucket URL.

---

## 10. Complete API reference

All routes are prefixed `/api`. All carry `@require_auth`.

### Exceptions — `/api/exceptions`

| Method | Path | Purpose |
|---|---|---|
| GET | `` | list cases |
| POST | `` | create an empty case |
| GET | `/<id>` | one case |
| GET | `/<id>/documents` | documents on the case |
| POST | `/<id>/documents` | upload PDFs (multipart, ≤20/request) |
| POST | `/<id>/documents/<doc_id>/retry` | re-extract one document |
| GET | `/<id>/documents/<doc_id>/content` | authenticated PDF bytes |
| GET | `/<id>/progress` | per-document processing state |
| GET | `/<id>/readiness` | what is still missing, and why |
| POST | `/<id>/analyze` | re-run the match (idempotent) |
| GET | `/<id>/match` | the `MatchResult` |
| GET | `/<id>/graph` | the evidence graph |
| GET | `/<id>/trust` | the guardrail's record — 404 until reasoning has run |
| GET | `/<id>/reasoning` | cached agent 2 output — 404 if not generated |
| POST | `/<id>/reasoning/generate` | run agent 2 |
| GET | `/<id>/hypotheses` | cached agent 4 output — 404 if not generated |
| POST | `/<id>/hypotheses/generate` | run agent 4 |
| GET | `/<id>/resolution` | cached agent 3 output — 404 if not generated |
| POST | `/<id>/resolution/generate` | run agent 3 |
| GET | `/<id>/audit` | audit trail |
| PATCH | `/<id>/status` | set a user-settable status |

### Analytics — `/api/analytics`

| Method | Path | Purpose |
|---|---|---|
| GET | `/overview` | everything the Analytics screen needs, one round trip |
| GET | `/cross-case` | what a per-invoice check would have missed |
| GET | `/trust` | the disagreement ledger |
| GET | `/accuracy` | the last recorded eval run — 404 if none |
| GET | `/vendor-risk` | vendors ranked by value at risk |
| GET | `/trends` | monthly exception rate |
| GET | `/ageing` | open cases bucketed against SLA |

Every analytics route takes a bounded `days` window (clamped to 730) and caps
returned rows. Those are the constraints a BigQuery-backed version needs to
keep scans small, so swapping the execution engine later does not change this
surface.

`/accuracy` is served **from disk** — from the JSON the eval harness writes.
That indirection is deliberate: a route that recomputed a score on request
would be the system grading itself, and the value of an eval is that somebody
else can run the command and get the same answer.

### Others

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | unauthenticated liveness + mode |
| GET | `/api/auth/me` | verified identity |
| GET | `/api/dashboard/summary` | queue KPIs |
| GET | `/api/settings/tolerance` | resolved tolerance rules |
| GET | `/api/settings/mode` | mock/live, storage, Gemini state |
| GET | `/api/intake/email` | email intake status |
| POST | `/api/intake/email/poll` | manual IMAP poll |

---

## 11. Authentication

`auth.py` / `services/auth_service.py`. Firebase ID tokens, verified with the
Admin SDK. `@require_auth` is two-speed:

- **`AUTH_REQUIRED=false`** (default) — a missing or invalid token never
  blocks. A token that *is* sent is still verified and `g.user` populated.
  This keeps the demo flow working with zero Firebase setup.
- **`AUTH_REQUIRED=true`** — missing or invalid token gets an immediate 401.

CORS is an explicit allow-list (`ALLOWED_ORIGINS`), never `*`, because Firebase
ID tokens are accepted. `allow_headers` must include `Authorization` or the
browser's preflight strips it before Flask ever sees the token.

---

## 12. Configuration

Everything is read in `config.py`; nothing else touches `os.environ`.

| Variable | Default | Notes |
|---|---|---|
| `USE_MOCK_DATA` | `true` | also forced true when no credentials exist |
| `AUTH_REQUIRED` | `false` | flip on when real sign-in is wired |
| `ALLOWED_ORIGINS` | `localhost:5173` | comma-separated, never `*` |
| `GEMINI_API_KEY` | — | absent → deterministic path throughout |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | extraction |
| `GEMINI_REASONING_MODEL` | `gemini-3.5-flash` | agents 2, 3, 4 |
| `GOOGLE_CLOUD_PROJECT` | `proofaegis-hackathon` | |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | — | one-line JSON, for hosts without a file mount |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | path to a key file |
| `STORAGE_BUCKET` | falls back to Firebase bucket | `gs://` or bare name |
| `STORAGE_BACKEND` | `auto` | `local` forces on-disk |
| `LOCAL_STORAGE_DIR` | `backend/.local_storage` | |
| `MAX_UPLOAD_SIZE_MB` | `15` | per file |
| `MAX_FILES_PER_REQUEST` | `20` | per request; a **case** has no limit |
| `DEFAULT_PRICE_TOLERANCE_PERCENT` | `5` | fallback only; Firestore is source of truth |
| `DEFAULT_QUANTITY_TOLERANCE_PERCENT` | `2` | |
| `AI_CALL_TIMEOUT_SECONDS` | `20` | |
| `AI_CALL_MAX_RETRIES` | `1` | |
| `DEMO_FAULT_INJECTION` | `true` | the seeded guardrail demonstration |
| `OCR_ENABLED` | `false` | needs Tesseract on PATH |
| `OCR_DPI` | `300` | render resolution when OCR runs |
| `SIGNED_URL_TTL_MINUTES` | `15` | lifetime of a signed object URL |
| `DEFAULT_WORKSPACE_ID` | `demo-workspace` | |

### Email intake

Inert unless `EMAIL_INTAKE_ENABLED` is true **and** host, user and password are
set **and** at least one sender is allowed. An empty allow-list processes
nothing, deliberately: an inbox that accepts documents from anyone is an open
door into an approval queue. Messages are marked `\Seen`, never deleted.

| Variable | Default |
|---|---|
| `EMAIL_INTAKE_ENABLED` | `false` |
| `EMAIL_INTAKE_HOST` | — |
| `EMAIL_INTAKE_PORT` | `993` |
| `EMAIL_INTAKE_USER` | — |
| `EMAIL_INTAKE_PASSWORD` | — (use an app password, not an account password) |
| `EMAIL_INTAKE_FOLDER` | `INBOX` |
| `EMAIL_INTAKE_BATCH_SIZE` | `20` |
| `EMAIL_INTAKE_ALLOWED_SENDERS` | — comma-separated; an address or a domain (`@vendor.com`) |

### Set by the platform, not by you

`K_SERVICE` is set automatically by Cloud Run on every running revision.
`config.py` reads it as one of three signals that real credentials exist —
which is how a Cloud Run deployment picks up Application Default Credentials
without a key file, and why `USE_MOCK_DATA` correctly resolves to false there.

### Tolerance resolution

Specificity wins: **vendor rule > category rule > workspace default**.
Overrides merge key by key, so a rule setting only a price tolerance keeps the
default quantity tolerance rather than blanking it. The resolved record reports
`tolerance_source`, because a reviewer asking "why was this within tolerance?"
needs to know which rule answered.

---

## 13. The eval harness

`backend/eval/`. Two harnesses, kept apart so a failure is never ambiguous
between "read the document wrong" and "reasoned about it wrong".

```bash
python -m eval.run_eval --count 320 --json data/generated/eval_report.json
```
```bash
python -m eval.extraction_eval --json data/generated/extraction_report.json
```

### 13.1 Why it is not a tautology

`eval/fixtures.py` generates the **field values** that would appear on a PO, a
goods receipt and an invoice, perturbs them with a named defect, and says
nothing about the outcome. The pipeline decides for itself — through the same
`build_matching_input` and `evaluate_exception` the product runs, via a
datastore stand-in that serves the fixture's own prior invoices.

Ground truth comes from `expected_outcome()`, a deliberately naive second
implementation of the documented policy, written from the specification rather
than from `matching_service.py`. **If the label came from the matcher, a score
of 1.000 would mean nothing.** `tests/test_eval_harness.py` asserts that
independence by source inspection, and includes a case that feeds the scorer a
prediction it knows is wrong — a scorer that cannot fail would invalidate every
other number here.

### 13.2 Current results

| Harness | Figure |
|---|---|
| Pipeline — 320 cases, 11 types | recall **1.000**, precision **1.000**, exact-type **1.000** |
| — on clean documents (262) | 1.000 |
| — on degraded documents (58) | 1.000 |
| Extraction — 66 documents, 6 layouts, 288 comparisons | **1.000** (0 wrong, 0 missed) |
| Document classification | **1.000** |

### 13.3 What it found

Five real defects, all fixed, all with a regression test:

| Defect | Effect |
|---|---|
| Vendor names compared as raw strings | 21/21 spelling variants → false `vendor_mismatch`; precision 1.00 → **0.87** |
| The same identity rule implemented twice, differently | A duplicate went unreported and fell through to `po_over_billed` |
| Quantity check skipped itemized invoices | A 4.2% quantity variance silently cleared |
| A near-duplicate outranked a bank change | Payment diversion reported as a possible re-submission |
| Missing label aliases; parser returned a document's own title as its supplier | `receipt_number` missing on 2 of 6 layouts; `PURCHASE ORDER` extracted as a vendor name |

### 13.4 Scope — read this before quoting the numbers

The decision layer is scored on clean field values, where deciding whether
2,650 is more than 5% above 2,400 is arithmetic, and **arithmetic does not
have an error rate**. The harness therefore also applies document conditions a
real corpus carries — a vendor name spelled differently, a tax basis that does
not line up, an itemized invoice with no scalar quantity, an unreadable date,
a receipt with no stated quantity — and reports clean and degraded separately.

The extraction harness renders each case in six dialects. That variation is
real, and it is variation **this project authored**. It does not cover scans,
OCR noise, skew, handwriting, multi-page documents, or the layouts of vendors
nobody here has seen. Treat it as a regression measure over a known
population, not an estimate of accuracy on a real inbox.

---

## 14. Tests

**231 tests across 18 files.**

```bash
cd backend && ./venv/Scripts/python.exe -m pytest -q
```

| File | Covers |
|---|---|
| `test_matching_service.py` | variance formulas, tolerance boundaries |
| `test_history_checks.py` | duplicates, cumulative billing, payment changes |
| `test_recurring_and_drift.py` | cadence suppression both ways; drift, including the negatives |
| `test_cross_case_and_identity.py` | vendor identity folding; the cross-case set matches the matcher |
| `test_trust_ledger.py` | the guardrail, and what the ledger refuses to count |
| `test_eval_harness.py` | the harness cannot become a tautology, and can still fail |
| `test_ingestion.py` | validation, extraction, linking |
| `test_document_linking.py` | PO/GRN pairing by reference, not recency |
| `test_real_document_layouts.py` | parser against realistic layouts |
| `test_graph_service.py` | graph provenance — no false edges |
| `test_exception_agent.py` | agent 2 + guardrail |
| `test_unconfirmed_risk.py` | risk banding for missing receipts |
| `test_approval_and_intake.py` | approval policy, email intake |
| `test_auth.py` | token verification, two-speed auth |

The suite pins `STORAGE_BACKEND=local` and `USE_MOCK_DATA=true`.

---

## 15. Failure behaviour

| Failure | What happens |
|---|---|
| Gemini unreachable / 503 / schema violation | Retry once, then fall back to the deterministic path. Result labelled `source: "mock"`; the UI shows it |
| No `GEMINI_API_KEY` | Deterministic extraction throughout. Nothing breaks |
| No GCP credentials | `USE_MOCK_DATA` forced true; in-memory datastore, on-disk storage |
| Scanned PDF, `OCR_ENABLED=false` | Clear message. Never silently processed |
| PDF with no usable invoice | `readiness` explains what is missing; the case is a legitimate state, not an error |
| Firestore write of a trust check fails | Logged, request still succeeds. Losing the audit row is strictly less bad than losing the answer |
| Any unhandled exception | 500 `{"error": "internal_error"}`. Stack traces never reach the client |

**OCR is only ever a fallback.** A PDF with a real text layer is never OCR'd,
because embedded text is exact and OCR output is inference.

---

## See also

- [`ARCHITECTURE_FRONTEND.md`](ARCHITECTURE_FRONTEND.md)
- [`GOOGLE_STACK.md`](GOOGLE_STACK.md) — every Google technology, command and link
- [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md)
- [`README.md`](README.md) — limitations, stated plainly
