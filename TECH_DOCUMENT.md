PROOFAEGIS
Technical Documentation

Subtitle: An evidence-first invoice exception investigation system, built on Google Cloud, Gemini and the Google Agent Development Kit.

Tagline: From invoice rejection to resolution — with proof, not guesswork.

Note on data: Every vendor, invoice, amount, bank detail and document referenced in this system is synthetic. No real company, contract or payment is represented.

────────────────────────────────────────────────────────────────

1. PROJECT DESCRIPTION

1.1 The problem

An Accounts Payable team receives thousands of vendor invoices a month. Most flow straight through. A minority fail the three-way match — invoice against purchase order against goods receipt — and drop into an exception queue. Each of those is then investigated by hand: open three PDFs, find the field that disagrees, work out what it costs, decide who owns the fix, and write to the vendor or the internal team. That loop takes 20–45 minutes per case, and it produces no reusable record of why the decision was made.

► There is a second, larger problem that AP tooling almost never addresses. A per-invoice matcher can only see the invoice in front of it. It cannot see that the same invoice was already paid last month, that this is the fourth instalment against a purchase order that has now been over-billed, or that the vendor's bank account silently changed since their previous submission. Those invoices match perfectly against their own documents. They pass.

► The design claim of ProofAegis: what passes is scarier than what fails.

1.2 What ProofAegis is

ProofAegis is an exception-resolution assistant with a cross-case investigation layer on top. For a single case it:

•  Ingests invoice-related PDFs (upload, or polled from a mailbox over IMAP)
•  Extracts structured fields — vendor, PO number, amounts, tax, line items, bank details
•  Runs deterministic two-way and three-way matching against configurable tolerances
•  Classifies the exception type and computes the financial impact in code
•  Assembles a source-linked evidence graph so every claim points at the document it came from
•  Explains the discrepancy in plain language and ranks candidate causes
•  Recommends the owning team and drafts a cited resolution message
•  Records every human action in an immutable audit trail

Across the whole workspace it answers the question a single case cannot: where the next exceptions are coming from — vendor exception rates, value at risk, ageing against SLA, and month-over-month trend.

1.3 What ProofAegis is not

It is not an ERP, a payment-release system, a bank-account verification service, a legal or tax advisor, an autonomous fraud detector, or a supplier lifecycle platform. No payment is ever released by this system. Every AI output is review-only and labelled as such in the interface.

1.4 The cross-case investigation layer — the differentiator

Five checks read the rest of the workspace rather than this one invoice. Each one fires on invoices whose own three-way match is clean.

•  Duplicate invoice — needs the vendor's earlier invoices. The duplicate lives in a different case, so a per-invoice system structurally cannot see it.
•  Cumulative over-billing — needs every invoice raised against one purchase order. Each instalment passes on its own; only the running total breaches.
•  Changed payment details — needs the bank account on the vendor's last invoice. This invoice looks entirely normal in isolation. This is the classic invoice-redirection fraud pattern.
•  Vendor price drift — needs the unit rate across the vendor's last six invoices. Every monthly rise sits inside tolerance; the twelve-month slope does not.
•  Recurring billing detection — needs the cadence across months. It is what stops the duplicate rule firing on legitimate rent and subscription invoices.

► Measured on the current 320-case synthetic portfolio: 13 of 77 exceptions come from these five checks, and 9 of those 13 scored a full three-way match on their own documents. A per-invoice system would have released all nine for payment. The Analytics screen computes this split live from the data rather than quoting it as a static claim.

1.5 The architectural rule the whole system is built around

► A number a human acts on must never come from a model.

The boundary is enforced in code, not in policy:

Owned by deterministic Python
•  Matching, tolerance evaluation, match score, financial impact — services/matching_service.py
•  Cross-case findings: duplicates, over-billing, payment changes, price drift, cadence — services/history_service.py
•  Evidence graph assembly — services/graph_service.py (it is the thing used to verify everything else, so it must be exactly reproducible)
•  Portfolio analytics: rates, value at risk, ageing, trend — services/analytics_service.py

Owned by Gemini, via the Google Agent Development Kit
•  Document classification and field extraction — judgement about reading a document, with a deterministic byte-level parser as fallback
•  Severity, plain-language explanation, recommended action — language, not arithmetic
•  Ranked candidate causes and what to check next — its output schema contains no numeric field at all, by design
•  Resolution draft — language, with structurally enforced citations
•  Portfolio narration — ranking and connecting figures it read from named tools

1.6 The trust ledger — the guardrail, made visible

On every reasoning call, live or fallback, the model's stated financial_impact is compared against the deterministic MatchResult. On any mismatch the model's figure is overwritten, and requires_human_review is forced to true regardless of what the model returned.

That override used to be silent — it corrected the number and wrote a log line, which meant the most defensible property of the architecture was visible only to someone tailing stderr. Every comparison now produces a TrustCheck record (services/trust_ledger.py), agreements included. It is shown per case as a trust row and aggregated on the Analytics screen as a disagreement ledger.

The ledger keeps three counts strictly apart, because merging them would turn a measurement into a marketing figure:

•  model answered — a live model produced a figure. The only denominator a disagreement rate is allowed to use.
•  fallback answered — the model was unreachable and the deterministic template stood in. Recorded, and excluded from every rate: counting an outage as agreement would manufacture a perfect record out of a failure.
•  fault injection — a figure corrupted on purpose so the override can be watched firing rather than described. Case EXC-2026-0001 carries one (stated ₹31,200 against a computed ₹25,000). It is labelled in the UI and never added to live totals.

1.7 The five agents

Four agents are handed their input; something upstream decided what mattered and put it in the prompt. The fifth is different — it is given tools and reads data itself.

•  Agent 1 — Document extraction (services/document_agent.py). Schema: InvoiceExtraction and siblings. Fallback: pdf_field_parser, which reads the real PDF bytes and never invents a value.
•  Agent 2 — Exception reasoning (services/exception_agent.py). Schema: ExceptionReasoning. Fallback: a template over the computed MatchResult.
•  Agent 3 — Resolution drafting (services/resolution_agent.py). Schema: ResolutionDraft. Fallback: a cited template.
•  Agent 4 — Investigation hypotheses (services/hypothesis_agent.py). Schema: HypothesisSet, containing no numeric field. Fallback: a fixed catalogue.
•  Agent 5 — Portfolio investigation (services/portfolio_agent.py). Reaches BigQuery through the MCP Toolbox for Databases. It is given five named, parameterised analytics tools and no tool that accepts SQL — so it can choose a question and a window, but cannot compose an aggregation. Every figure it narrates came out of a statement a human wrote and a test covers. If the Toolbox server is unreachable it returns unavailable rather than answering from memory.

1.8 Data used

Synthetic portfolio (backend/scripts/generate_synthetic_data.py)
•  320 invoice cases across a 20-vendor population, spanning 12 months
•  243 clean, 77 exceptions across 11 exception types
•  Exception mix: price_variance 25, quantity_variance 15, missing_goods_receipt 10, missing_purchase_order 6, vendor_mismatch 5, duplicate_invoice 4, po_over_billed 3, tax_total_mismatch 3, payment_details_changed 2, recurring_suspected 2, vendor_price_drift 2
•  Indian AP context throughout — INR, GST, HSN/SAC codes, Indian digit grouping
•  Two design properties that make it worth analysing rather than merely voluminous: clean invoices are the majority, because exception rate is the headline metric and a rate needs an honest denominator; and risk is concentrated in a handful of vendors rather than uniformly scattered, because uniform noise would make the "which vendors will fail next" claim hollow
•  The RNG is seeded, so the same command always reproduces the same portfolio
•  Emitted as portfolio.json (Firestore / in-memory), portfolio.ndjson (BigQuery load) and vendors.json (the vendor dimension)

Synthetic PDFs (backend/scripts/generate_synthetic_pdfs.py, pdf_layouts.py)
•  14 fully-documented demo cases, each a folder of real rendered PDFs — invoice, purchase order, goods receipt — covering the full exception vocabulary including the multi-document cross-case scenarios (duplicate_invoice_a/b, po_over_billed_a/b/c, payment_details_changed_a/b)
•  6 distinct document dialects: baseline, legacy_mono, erp_export, stacked_columns, gst_tax_invoice, unlabelled_gst — different label wording, value placement, fonts, table structure, money formats and page clutter

Evaluation harnesses (backend/eval/)
•  run_eval.py scores the decision. It hands labelled fixtures to the same shipping code path — ingestion, history checks, matching — through a datastore stand-in, so a score is a score of the product and not of a convenient copy of it. Over 320 labelled cases: detection recall 1.00, precision 1.00, exact exception-type accuracy 1.00 across 11 types.
•  extraction_eval.py scores the reading. It starts from PDF bytes, not field values. 66 documents, 288 scored fields, 6 layouts: 100% field accuracy and 100% document classification. The baseline layout — the one the parser was written against — is reported separately from the five unseen layouts, exactly as a control group is, because the interesting figure is the drop.
•  The two are kept apart deliberately. A combined number would leave every failure ambiguous between "read the document wrong" and "reasoned about it wrong", and those have completely different fixes.

1.9 Google technologies used

•  Gemini via Vertex AI — extraction, reasoning, drafting, hypothesis ranking, portfolio narration. SDK: google-genai. Region: global.
   – gemini-3.5-flash-lite for extraction: structured, low-judgement, latency-critical
   – gemini-3.5-flash for reasoning, drafting, hypotheses and portfolio narration: language tasks that need the stronger model
   ► Models are pinned, not floating aliases. gemini-flash-latest was measured at 75 seconds — and returning 503 UNAVAILABLE — on a 427-character extraction that a pinned flash-lite answers identically in about 1.4 seconds.
   ► GOOGLE_CLOUD_LOCATION=global is deliberate. Model availability is per-region: probed on 2026-09-04, asia-south1 served flash but returned 404 for flash-lite, and us-central1 returned 404 for both. Pinning a region would have silently lost the extraction model and sent every upload down the deterministic fallback.
   ► Vertex AI rather than the AI Studio Developer API is a billing decision, not a technical one. The Developer API bills a separate prepay wallet; running there produced 429 RESOURCE_EXHAUSTED while the Cloud console showed the project's trial credit entirely unused. Both were true at once. The switch is configuration only — no application code knows which backend it is on.

•  Google Agent Development Kit (google-adk) — the agent framework. Each agent declares a Pydantic output_schema that ADK validates, so a malformed model response and an unreachable model are handled identically: by falling back to a deterministic path. This is what makes the fallback story honest rather than aspirational.

•  MCP Toolbox for Databases — exposes five parameterised BigQuery statements (portfolio_summary, vendor_risk, monthly_trend, ageing, cross_case_value) as tools to Agent 5. The boundary is held one layer lower here than anywhere else in the system: there is no tool that accepts SQL, so the agent cannot compose a new aggregation.

•  Cloud Firestore (asia-south1) — the operational store. Seven collections: invoice_exceptions, documents, exception_reasoning, investigation_hypotheses, resolution_drafts, audit_events, settings.

•  BigQuery (asia-south1) — the analytics engine at volume. Partitioned on created_at, clustered on vendor_id.

•  Cloud Storage (asia-south1) — uploaded PDFs, workspace-scoped from the first byte written.

•  Firebase Authentication — sign-in and ID tokens, verified server-side by the Firebase Admin SDK.

•  Firebase Hosting — serves the React build on Google's global CDN, and rewrites /api/** to Cloud Run so the API is same-origin and there is no CORS preflight on any request.

•  Cloud Run (asia-south1, scale-to-zero) — the Flask API container.

•  Secret Manager — the Gemini key and the service-account JSON. Never in an image, never in a repository.

•  Artifact Registry — container images. Cloud Build — builds the image from source.

•  Cloud Logging and Monitoring — structured logs. Cloud Billing — budget alerts.

► Why asia-south1 (Mumbai) throughout: the portfolio is an Indian AP workspace, and keeping Firestore, Storage, BigQuery and Cloud Run in one region avoids cross-region egress and puts latency where the users would be. Firestore's location is permanent once set.

1.10 Why BigQuery is not an analytics add-on here

Every cross-case check answers a question about one invoice by reading the vendor's whole history. The document store serves that with an unfiltered collection stream — the entire collection, pulled into Python. At 320 cases that is free. At the volume a mid-size AP function actually runs — hundreds of thousands of invoices a year — it is a full-collection scan per request, and it is a scan of exactly the feature that makes this product different from a per-invoice matcher.

► So: BigQuery aggregates, Python writes the sentence. The GROUP BY, whose cost grows with the table, runs as SQL; what comes back is one narrow row per vendor, per month or per bucket. Turning those rows into a response then reuses the same helpers as the Firestore path rather than reimplementing them in SQL — because formatting logic that existed twice would drift, and a parity test would then be asserting that two copies of a bug agree. Only the aggregation is duplicated, and a parity test asserts the two engines produce identical numbers.

The engine is selected by the ANALYTICS_ENGINE variable. If BigQuery is selected and unreachable, the request fails; it does not quietly fall back to Firestore and serve numbers computed a different way than the response claims. A wrong answer delivered confidently is worse than an error message.

────────────────────────────────────────────────────────────────

2. PROJECT USE CASE

2.1 Who it is for

•  AP Analyst — works the exception queue. Needs to know what is wrong, what it costs, who owns it, and what to send.
•  AP Manager / Controller — needs the portfolio view: which vendors, how much value is at risk, what is breaching SLA, and whether the trend is improving.
•  Procurement — receives price and purchase-order exceptions with the variance already computed and cited.
•  Internal Audit — needs to reconstruct, months later, who decided what and on what evidence.

2.2 The end-to-end journey

Step 1 — Intake
An invoice arrives. Either an analyst creates a case and drops the PDFs in, or the IMAP poller picks up unread mail from allow-listed senders and creates the case automatically. There is no limit on how many documents a case can hold, and more can be added later. Attachments from the mailbox are validated exactly as an upload is — extension, PDF magic bytes, size — before a single byte is stored. Nothing is ever deleted from the mailbox; messages are marked seen so the same invoice is not ingested twice, and the original stays where it is, because that is the record a dispute is settled from.

Step 2 — Text extraction, before any model
PyMuPDF extracts the text layer from the PDF first. Only that text ever reaches Gemini.
► The model never sees PDF bytes. This ordering is mandatory, not incidental: it bounds what the model can be prompted with, and it means the deterministic fallback and the model path are reading the same input.

Step 3 — Field extraction
Agent 1 classifies the document (invoice, purchase order, goods receipt, or unrelated) and extracts fields into a validated Pydantic schema. If Gemini is unreachable or returns something the schema rejects, pdf_field_parser reads the same text deterministically. The UI labels which path produced the result. The system runs completely with no API key at all — extraction just becomes deterministic and says so.

Step 4 — Matching (deterministic)
The invoice is compared field by field against the purchase order and the goods receipt.
   absolute_variance   = actual_value − expected_value
   percentage_variance = absolute_variance ÷ expected_value × 100
   match_score         = round(100 × matched_count ÷ evaluable_count)
Default tolerances are 5% on price and 2% on quantity, overridable per vendor and per category. evaluable_count only counts comparisons where both source values existed — a case is never penalised for a document that is legitimately missing, because that is its own exception type.

Step 5 — Cross-case checks (deterministic)
The five history checks run against the vendor's prior invoices and against every invoice raised on the same purchase order. This is the step that catches what step 4 passed.

Step 6 — Reasoning and hypotheses
Agent 2 produces severity, a plain-language explanation and a recommended owner. Agent 4 produces ranked candidate causes and what to check next. The trust ledger compares Agent 2's financial figure against the computed one and records the result either way.

Step 7 — Evidence graph
A deterministic graph links each finding to the exact document and field it came from. Hovering a finding lights up its evidence chain. Nothing in the graph is model-generated, because the graph is the instrument used to verify everything else.

Step 8 — Resolution
Agent 3 drafts a message to the vendor or the internal team, with citations enforced by the output structure rather than requested in the prompt. The analyst edits and sends it themselves — the system never sends on anyone's behalf.

Step 9 — Action and audit
Status changes, approvals and overrides are recorded as audit events with actor, timestamp and prior state.

Step 10 — Portfolio
The Analytics screen aggregates exception rate by vendor, value at risk, ageing against a fortnight SLA, month-over-month trend, the cross-case split, and the trust disagreement ledger. Agent 5 answers free-text portfolio questions by calling the five named BigQuery tools.

2.3 A worked example — the case that fails

Case EXC-2026-0001, price variance. Three PDFs go in. Text is extracted, fields are read out of the bytes, and matching finds the invoiced unit rate above the purchase-order rate by more than the 5% tolerance. Financial impact: ₹25,000, computed in code. Owner: Procurement. Severity, explanation and draft come from Gemini; the number does not.

► This case also carries the deliberate fault injection. The model is fed a corrupted ₹31,200 against the computed ₹25,000, so a reviewer can watch the override fire, see the trust row record the disagreement, and confirm the case is forced to human review — rather than take the guardrail on trust. It is labelled as injected in the UI and excluded from the live disagreement rate.

2.4 The worked example that matters more — the case that passes

An invoice arrives from a known vendor. It matches its purchase order exactly. It matches its goods receipt exactly. Match score 100. Every tolerance clean. A per-invoice matcher approves it.

Then the cross-case layer reads the vendor's previous invoice and finds the bank account on this one is different. The invoice is correct in every respect except the one that matters, and the full invoice amount is put at risk pending verification, owned by Accounts Payable.

► Nine of the thirteen cross-case exceptions in the portfolio are of this shape. That is the argument for the product in one number.

2.5 Value

•  Investigation time compresses from 20–45 minutes of document archaeology to a reviewed decision, because the variance, the impact, the owner and the draft are all present when the case opens.
•  Exceptions that no per-invoice system can see — duplicates, cumulative over-billing, redirected payments, price drift — get caught before payment rather than in an annual audit.
•  Every decision leaves a source-linked, reconstructible record.
•  The portfolio view turns a queue into a prioritisation: which vendors, how much, how late, getting better or worse.

────────────────────────────────────────────────────────────────

3. ARCHITECTURE DIAGRAM

Formatting note for Google Docs: select the diagram blocks below and set them to Courier New (or any monospace font) so the boxes and rules line up.

3.1 System architecture

                                 Browser
                                    │
                                    ▼
              ┌───────────────────────────────────────────┐
              │  React 19 + Vite                          │
              │  Firebase Hosting  ·  global CDN          │
              │  Firebase Auth  ·  ID tokens              │
              └────────────────────┬──────────────────────┘
                                   │
                    /api/**  Hosting rewrite → Cloud Run
                    (same origin, no CORS preflight)
                                   │
                                   ▼
              ┌───────────────────────────────────────────┐
              │  Flask on Cloud Run                       │
              │  asia-south1  ·  scale-to-zero            │
              │                                           │
              │  Auth · validation · orchestration        │
              │  ────────────────────────────────────     │
              │  Matching          (deterministic)        │
              │  Cross-case checks (deterministic)        │
              │  Evidence graph    (deterministic)        │
              │  Analytics         (deterministic)        │
              │  Trust ledger      (deterministic)        │
              └──┬────────┬─────────┬──────────┬──────────┘
                 │        │         │          │
                 ▼        ▼         ▼          ▼
          ┌──────────┐ ┌────────┐ ┌─────────┐ ┌──────────────┐
          │ PyMuPDF  │→│ Gemini │ │Firestore│ │Cloud Storage │
          │ PDF text │ │via ADK │ │7 collns │ │ case PDFs    │
          └──────────┘ │ extract│ └─────────┘ └──────────────┘
                       │ reason │      │
                       │ draft  │      │  nightly / streamed load
                       │ hypoth.│      ▼
                       └────┬───┘ ┌──────────────┐
                            │     │  BigQuery    │
                            │     │  cases table │
                            │     │  partitioned │
                            │     │  + clustered │
                            │     └──────┬───────┘
                            │            │
                       ┌────▼────────────▼─────┐
                       │  MCP Toolbox for DBs  │
                       │  5 named SQL tools    │
                       │  (no run_sql tool)    │
                       └───────────┬───────────┘
                                   │
                       ┌───────────▼───────────┐
                       │ Agent 5 — Portfolio   │
                       │ narrates, never       │
                       │ computes              │
                       └───────────────────────┘

3.2 Case pipeline — the order is mandatory

  PDF upload            IMAP poll
  (browser)             (allow-listed senders)
       │                      │
       └──────────┬───────────┘
                  ▼
        ┌──────────────────────┐
        │ 1. Validate          │  extension · magic bytes · size
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │ 2. Store             │  workspaces/{ws}/cases/{exc}/{doc}.pdf
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │ 3. PyMuPDF → text    │  ◄── the model never sees PDF bytes
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │ 4. AGENT 1: extract  │  Gemini 3.5 flash-lite via ADK
        │    schema-validated  │  fallback → pdf_field_parser
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │ 5. MATCHING          │  DETERMINISTIC · no model
        │    2-way / 3-way     │  variance · match_score · impact
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │ 6. CROSS-CASE        │  DETERMINISTIC · reads history
        │    5 checks          │  duplicate · over-billing ·
        └──────────┬───────────┘  payment change · drift · cadence
                   ▼
        ┌──────────────────────┐
        │ 7. AGENT 2: reason   │  Gemini 3.5 flash via ADK
        │    AGENT 4: hypoth.  │  severity · owner · causes
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │ 8. TRUST LEDGER      │  model figure vs computed figure
        │                      │  mismatch → overwrite + record
        │                      │  requires_human_review → always true
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │ 9. EVIDENCE GRAPH    │  DETERMINISTIC · finding → field → doc
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │ 10. AGENT 3: draft   │  cited resolution message
        └──────────┬───────────┘
                   ▼
        ┌──────────────────────┐
        │ 11. Human decides    │  → audit_events
        └──────────────────────┘

3.3 The trust boundary, in one picture

    ┌─────────────────────────────────────────────────────┐
    │  DETERMINISTIC CODE — owns every number             │
    │                                                     │
    │  matching_service   variance, match score, impact   │
    │  history_service    the five cross-case findings    │
    │  graph_service      the evidence chain              │
    │  analytics_service  rates, value at risk, ageing    │
    └───────────────────────────┬─────────────────────────┘
                                │
                    the computed figure
                                │
                                ▼
    ┌─────────────────────────────────────────────────────┐
    │  TRUST LEDGER — compares, records, overrides        │
    │  model answered  |  fallback answered  |  injected  │
    │  (the only denominator)   (excluded)    (labelled)  │
    └───────────────────────────▲─────────────────────────┘
                                │
                    the model's figure
                                │
    ┌───────────────────────────┴─────────────────────────┐
    │  GEMINI via ADK — owns language only                │
    │                                                     │
    │  Agent 1  extract      Agent 2  explain, severity   │
    │  Agent 3  draft        Agent 4  rank causes         │
    │  Agent 5  narrate the portfolio (tools, not SQL)    │
    │                                                     │
    │  Every output schema-validated. Every failure       │
    │  falls back to a deterministic path. Every result   │
    │  labelled review-only in the UI.                    │
    └─────────────────────────────────────────────────────┘

3.4 Dual analytics engine

    routes/analytics.py
            │
            ▼
    analytics_gateway.py  ── reads ANALYTICS_ENGINE
            │
      ┌─────┴──────┐
      ▼            ▼
  firestore     bigquery
      │            │
  read whole    SQL GROUP BY,
  collection    partition-pruned
  → aggregate   → narrow rows
  in Python           │
      │               │
      └───────┬───────┘
              ▼
    shared formatting helpers
    (_risk_band, _why_at_risk, _cross_case_headline)
              │
              ▼
        same response body
    — asserted by a parity test —

  ► The read happens INSIDE the Firestore branch and nowhere else.
    If the gateway fetched cases and handed them to BigQuery it
    would have performed the very scan the SQL exists to avoid,
    and the engine switch would be theatre.

3.5 Data stores

Cloud Firestore — asia-south1 — seven collections
•  invoice_exceptions   (doc id EXC-2026-XXXX)  the case record
•  documents            (doc id DOC-XXXXXXXX)   per-document metadata + extraction
•  exception_reasoning  (doc id = exception id) Agent 2 output, cached
•  investigation_hypotheses (doc id = exception id) Agent 4 output, cached
•  resolution_drafts    (doc id = exception id) Agent 3 output, cached
•  audit_events         (auto id)               the audit trail
•  settings             (tolerance_rules, approval_policy) workspace policy

Cloud Storage — asia-south1
•  Path: workspaces/{workspaceId}/cases/{exceptionId}/{documentId}.pdf
•  ► Workspace-scoped from the first byte written. Documents are read back only through an authenticated backend endpoint or a short-lived signed URL. No permanent public URL is ever issued.

BigQuery — asia-south1 — proofaegis_analytics.cases
•  Partitioned on created_at, clustered on vendor_id. Every query carries the same bounded date predicate the Python path applies, so a 365-day window prunes to 365 days of partitions rather than scanning history.

3.6 API surface

/api/exceptions          list · create · get · patch · status
                         documents (upload, retry, content) · progress · readiness
                         match · graph · reasoning · hypotheses · resolution · trust · audit · analyze
/api/analytics           overview · cross-case · accuracy · trust · vendor-risk · trends · ageing · ask
/api/dashboard           summary
/api/settings            tolerance · mode
/api/auth                me
/api/intake              email (status) · email/poll

3.7 Frontend

React 19 on Vite, deployed to Firebase Hosting. Screens: Entry, Login, Signup, Dashboard, Exception Queue, Exception Detail (match table, evidence graph, reasoning, hypotheses, trust row, resolution draft, audit), Analytics, Invoices, Purchase Orders, Vendors, Settings. Ctrl+K / ⌘K opens a command palette that jumps to any case.

► The palette is built on one colour rule: rust is reserved for risk. Primary actions are dark ink, not red. High risk, a breached variance, a marker outside its tolerance band, a finding node's border, a month that got worse — those are red, and nothing else ever is. Every signal token is solved rather than picked: each is the minimum step that clears 4.5:1 contrast against every surface it actually sits on, in both light and dark mode.

3.8 Deployment topology

    Developer
        │  gcloud run deploy --source .
        ▼
    Cloud Build ──► Artifact Registry ──► Cloud Run (asia-south1)
                                              │
                                              ├── Secret Manager
                                              │   (GEMINI key, SA JSON)
                                              ├── Firestore (asia-south1)
                                              ├── Cloud Storage (asia-south1)
                                              ├── BigQuery (asia-south1)
                                              └── Vertex AI / Gemini (global)

    Developer
        │  npm run build && firebase deploy --only hosting
        ▼
    Firebase Hosting (global CDN) ── /api/** rewrite ──► Cloud Run

► The whole application also runs locally with no Google Cloud account, no API key and no billing: uploads write to disk, extraction uses the deterministic parser, and the seeded portfolio comes from a local JSON file. The ingestion pipeline is otherwise entirely real. Python and Node are the only prerequisites.

────────────────────────────────────────────────────────────────

END OF DOCUMENT
