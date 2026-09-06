# ProofAegis

**From invoice rejection to resolution — with proof, not guesswork.**

ProofAegis helps Accounts Payable and Procurement teams investigate invoices that
cannot be automatically approved. It ingests invoice-related PDFs, extracts
structured fields, runs deterministic two-way and three-way matching, explains the
discrepancy with source-linked evidence, calculates the financial impact in code,
recommends the responsible team, drafts a cited resolution message, and records
every human action in an audit trail.

It also answers the question one case at a time cannot: **where the next
exceptions are likely to come from**, through vendor-level exception rates, value
at risk, ageing against SLA, and month-over-month trend.

> **Synthetic data only.** Every vendor, invoice, amount, and document in this
> repository is fabricated. No real company, contract, or payment is represented.

---

## Documentation

Seven documents, all in this folder. Start with the one that matches what you
are trying to do.

| Document | For |
|---|---|
| **[`PITCH.md`](PITCH.md)** | Why this exists. The argument, the numbers, and what we did not build |
| **[`USER_GUIDE.md`](USER_GUIDE.md)** | Who it is for, where to start, and every feature end to end |
| **[`DEMO_GUIDE.md`](DEMO_GUIDE.md)** | Recording the three-minute demo — prep, script, click path, what goes wrong |
| **[`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md)** | Running it locally, then on the internet. Assumes nothing |
| **[`ARCHITECTURE_BACKEND.md`](ARCHITECTURE_BACKEND.md)** | Flask, the four ADK agents, matching, the cross-case layer, every endpoint |
| **[`ARCHITECTURE_FRONTEND.md`](ARCHITECTURE_FRONTEND.md)** | React, routing, the API layer, the evidence graph, the theme |
| **[`GOOGLE_STACK.md`](GOOGLE_STACK.md)** | Every Google service, with commands, links and costs |

This file is the reference below — setup, environment variables, and the
limitations section.

[`ProofAegis_Documentation_Pack_v2.md`](ProofAegis_Documentation_Pack_v2.md) is
the original planning pack. It is **historical** — kept only because the code's
`FR-xxx` comments reference its requirement numbers.

---

## Contents

1. [What it is and is not](#1-what-it-is-and-is-not)
2. [Architecture](#2-architecture)
3. [Repository layout](#3-repository-layout)
4. [Prerequisites](#4-prerequisites)
5. [Run it locally — the 5-minute path](#5-run-it-locally--the-5-minute-path)
6. [Local with real Firestore, Cloud Storage and Gemini](#6-local-with-real-firestore-cloud-storage-and-gemini)
7. [Environment variables](#7-environment-variables)
8. [Generating synthetic data](#8-generating-synthetic-data)
9. [Tests, lint and build](#9-tests-lint-and-build)
10. [Google Cloud setup](#10-google-cloud-setup)
11. [Deploy the backend to Cloud Run](#11-deploy-the-backend-to-cloud-run)
12. [Deploy the frontend to Firebase Hosting](#12-deploy-the-frontend-to-firebase-hosting)
13. [Seeding a live Firestore](#13-seeding-a-live-firestore)
14. [Cost control and budget alerts](#14-cost-control-and-budget-alerts)
15. [Post-deploy verification](#15-post-deploy-verification)
16. [Troubleshooting](#16-troubleshooting)
17. [Known limitations](#17-known-limitations)

---

## 1. What it is and is not

> Most AP automation decides what to approve.
> **ProofAegis investigates what failed — and what shouldn't have passed.**

**It is** an exception-resolution assistant with a cross-case investigation
layer. The three-way match is table stakes; every commercial AP product does
it, and so does this one. The part that is not table stakes is the set of
checks that read the rest of the workspace rather than this invoice:

| Check | What it needs | Why a per-invoice system cannot do it |
|---|---|---|
| Duplicate invoice | the vendor's earlier invoices | the duplicate lives in a different case |
| Cumulative over-billing | every invoice raised against one order | each instalment passes on its own |
| Changed payment details | the account on their last invoice | this invoice looks entirely normal |
| Vendor price drift | the rate on their last six invoices | every monthly rise is inside tolerance |
| Recurring billing | the cadence across months | it is what stops the duplicate rule firing on rent |

Every one of those fires on an invoice whose own three-way match is clean.
That is the product: **what passes is scarier than what fails.** On the
current 320-case synthetic portfolio, 13 of 77 exceptions come from these
checks, and 9 of those 13 scored a full three-way match on their own
documents — a per-invoice system would have passed them for payment. The
Analytics screen computes that split live; see §9.1 for how to reproduce it.

**It is not** an ERP, a payment-release system, a bank-account verification
service, a legal or tax advisor, an autonomous fraud detector, or a supplier
lifecycle platform.

### The line that matters

| Layer | Who does it | Why |
|---|---|---|
| Matching, tolerance evaluation, financial impact, match score | **Deterministic code** (`services/matching_service.py`) | A number a human acts on must never come from a model |
| Evidence graph assembly | **Deterministic code** (`services/graph_service.py`) | It is the thing used to verify everything else, so it must be exactly reproducible |
| Portfolio analytics — rates, value at risk, ageing, trend | **Deterministic code** (`services/analytics_service.py`) | Same reason |
| Document classification and field extraction | Gemini via Google ADK, with a deterministic parser fallback | Reading a document is judgement; the fallback reads the real bytes, never invents |
| Cross-case findings — duplicates, over-billing, payment changes, price drift | **Deterministic code** (`services/history_service.py`) | The differentiating claim must be arithmetic, not a guess |
| Severity, plain-language explanation, recommended action | Gemini via Google ADK | Language, not arithmetic |
| Resolution draft | Gemini via Google ADK | Language, with structurally-enforced citations |
| Ranked candidate explanations and what to check | Gemini via Google ADK (`services/hypothesis_agent.py`) | Judgement about causes — and its output schema contains no numeric field at all |

Every AI output is review-only and labelled as such in the UI. `exception_agent.py`
enforces this on **every** call, live or fallback: the model's `financial_impact` is
compared against the deterministic `MatchResult` and overwritten on any mismatch,
and `requires_human_review` is forced to `true` regardless of what the model returns.

That override used to be silent — it corrected the number and wrote a log
line, which meant the most defensible property of this architecture was
visible only to someone tailing stderr. It is now recorded. Every comparison
produces a `TrustCheck` (`services/trust_ledger.py`), agreements included,
shown per case as a trust row and aggregated on the Analytics screen as a
disagreement ledger.

The ledger keeps three counts strictly apart, because merging them would turn
a measurement into a marketing figure:

- **model answered** — a live model produced a figure. The only denominator a
  disagreement rate is allowed to use.
- **fallback answered** — the model was unreachable and the deterministic
  template stood in. Recorded, and excluded from every rate: the model said
  nothing, so counting it as agreement would manufacture a perfect record out
  of an outage.
- **fault injection** — a figure corrupted on purpose so the override can be
  watched firing rather than described. `EXC-2026-0001` carries one (stated
  ₹31,200 against a computed ₹25,000); it is labelled as an injected fault in
  the UI and never added to the live totals. Turn it off with
  `DEMO_FAULT_INJECTION=false`.

---

## 2. Architecture

```
                        Browser
                           │
                           ▼
        ┌──────────────────────────────────┐
        │  React 19 + Vite                 │
        │  Firebase Hosting                │
        │  Firebase Auth (ID tokens)       │
        └───────────────┬──────────────────┘
                        │  /api/**  (Hosting rewrite → Cloud Run, same origin)
                        ▼
        ┌──────────────────────────────────┐
        │  Flask on Cloud Run              │
        │  asia-south1 · scale-to-zero     │
        │                                  │
        │  Auth · validation · orchestration│
        │  Matching      (deterministic)   │
        │  Evidence graph(deterministic)   │
        │  Analytics     (deterministic)   │
        └──┬────────────┬─────────────┬────┘
           │            │             │
           ▼            ▼             ▼
    ┌───────────┐ ┌───────────┐ ┌──────────────┐
    │ PyMuPDF   │→│ Gemini    │ │ Firestore    │
    │ PDF text  │ │ via ADK   │ │ cases, docs, │
    └───────────┘ │ extract   │ │ drafts,audit,│
                  │ reason    │ │ settings     │
                  │ draft     │ └──────────────┘
                  └───────────┘         │
                                        ▼
                                ┌──────────────┐
                                │Cloud Storage │
                                │ case PDFs    │
                                └──────────────┘
```

**Pipeline order is mandatory:** PyMuPDF extracts text *first*; only that text
reaches Gemini. The model never sees PDF bytes.

**Storage path** (workspace-scoped from the first byte written):

```
workspaces/{workspaceId}/cases/{exceptionId}/{documentId}.pdf
```

Documents are read back through an authenticated backend endpoint or a
short-lived signed URL. No permanent public URL is ever issued.

---

## 3. Repository layout

```
ProofAegis/
├── backend/                 ← Flask API (the active backend)
│   ├── app.py               application factory
│   ├── config.py            the ONLY place os.environ is read
│   ├── auth.py              require_auth / workspace resolution
│   ├── datastore.py         Firestore | in-memory repository split
│   ├── routes/              exceptions · dashboard · analytics · settings · auth
│   ├── services/            matching · graph · analytics · ingestion · storage · agents
│   ├── scripts/             seeding and synthetic data generators
│   ├── tests/               pytest
│   ├── Dockerfile           Cloud Run image
│   └── run.ps1              local launcher
├── proofaegis-frontend/     ← React client (the active frontend)
│   ├── src/                 pages · components · services · lib
│   ├── firebase.json        Hosting config + /api → Cloud Run rewrite
│   ├── styles.css           structure, layout, components
│   └── src/
│       ├── theme-tokens.css  the palette and type — light and dark
│       └── styles-color.css  categorical colour for the evidence graph
├── docs/                    FRD · architecture · setup notes
└── ProofAegis_Documentation_Pack_v2.md
```

> **`frontend/` and `scripts/` at the repository root are obsolete duplicates**
> superseded by `proofaegis-frontend/` and `backend/scripts/`. Do not build on
> them. `render.yaml` and `backend/Procfile` are leftovers from an earlier
> Render deployment and are **not** the supported path — Cloud Run is.


### 3.1 The theme, in one rule

Three stylesheets, loaded in this order — the order is what keeps all three
free of `!important`:

| File | Job |
|---|---|
| `styles.css` | structure, layout, components |
| `src/theme-tokens.css` | the palette and type, and corrections to anything that hardcoded a colour before a theme existed |
| `src/styles-color.css` | the evidence graph's categorical hues, which sit on top because they are identity rather than chrome |

**The rule the palette is built around: rust is reserved for risk.**

Primary actions are dark ink, not red. High risk, a breached variance, the
marker outside its tolerance band, a finding node's border, a month that got
worse — those are red, and nothing else ever is. A button coloured red would
put the loudest thing on screen on every panel and the exceptions would stop
standing out. `--viz-finding` is an alias of `--exception` rather than a
fourth categorical hue, so the graph's red and the queue's red cannot drift
apart.

Every signal token is solved rather than picked: each is the minimum step that
clears 4.5:1 against every surface it is actually used on, in both modes.
Eyeballing had put three of them between 4.1 and 4.5, which looks fine and is
not.

---

## 4. Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Python | 3.10+ (3.12 tested) | backend |
| Node.js | 18+ (20+ recommended) | frontend |
| npm | 9+ | frontend |
| Google Cloud SDK (`gcloud`) | latest | deployment only |
| Firebase CLI (`firebase`) | 13+ | deployment only |
| Docker | latest | optional — Cloud Build can build for you |

Nothing beyond **Python and Node** is required to run the whole application
locally. No Google Cloud account, no API keys, no billing.

```bash
python --version; node --version; npm --version
```

Install the deployment CLIs only when you reach section 10:

```bash
npm install -g firebase-tools
```

`gcloud` comes from the [Google Cloud SDK installer](https://cloud.google.com/sdk/docs/install).

---

## 5. Run it locally — the 5-minute path

This runs the **complete** application with no credentials, no cloud calls, and
nothing billed. Uploads write to disk, extraction uses the deterministic parser,
and the seeded cases come from a local JSON file. The ingestion pipeline is
otherwise entirely real.

### 5.1 Backend — one-time setup

```bash
cd backend
python -m venv venv
```

```bash
./venv/Scripts/python.exe -m pip install -r requirements.txt
```

*(macOS/Linux: `./venv/bin/python -m pip install -r requirements.txt`)*

### 5.2 Backend — run

```bash
cd backend; ./run.ps1
```

`run.ps1` sets local-safe defaults, generates the demo PDFs on first run, and
starts Flask on **http://localhost:8080**. It prints exactly what mode it is in.

Not on PowerShell? The equivalent is:

```bash
USE_MOCK_DATA=true STORAGE_BACKEND=local AUTH_REQUIRED=false ./venv/bin/python app.py
```

### 5.3 Frontend — one-time setup

```bash
cd proofaegis-frontend; npm install
```

### 5.4 Frontend — run

```bash
cd proofaegis-frontend; npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api` to port 8080, so no
environment variable is needed.

### 5.5 Sign in

With no Firebase project configured the app uses a local demo session:

- **Email:** `judge@demo.proofaegis.local`
- **Password:** `demo-only`

Or click **Continue with demo workspace**.

### 5.6 Try the real workflow

1. **New case from PDFs** on the Dashboard.
2. Drop in the generated PDFs from `backend/data/synthetic_cases/price_variance_001/`
   — there is no limit on how many documents a case can hold, and you can add
   more later.
3. Watch the case land on `price_variance`, **₹25,000**, owner Procurement — all
   read out of the PDF bytes, none of it seeded.
4. Open **Evidence graph** and hover the finding to light up its evidence chain.
5. Press **Ctrl+K** (⌘K on macOS) to jump to any case.

---

## 6. Local with real Firestore, Cloud Storage and Gemini

Only needed to exercise the live cloud path from your machine.

1. Complete [section 10](#10-google-cloud-setup) first.
2. Copy the template and fill it in:

```bash
cd backend; Copy-Item .env.example .env
```

3. Set at minimum:

```
USE_MOCK_DATA=false
AUTH_REQUIRED=true
GEMINI_API_KEY=<your key>
GOOGLE_CLOUD_PROJECT=proofaegis
STORAGE_BUCKET=gs://proofaegis.firebasestorage.app
FIREBASE_SERVICE_ACCOUNT_JSON={"type":"service_account", ...}
```

4. Seed Firestore — see [section 13](#13-seeding-a-live-firestore).
5. Run in live mode:

```bash
cd backend; ./run.ps1 -Live
```

For the frontend to send real ID tokens, create `proofaegis-frontend/.env.local`
from `.env.example` and fill in the Firebase **web app** config (these values are
public by design; never put a service-account key in a `VITE_` variable).

---

## 7. Environment variables

### Backend — `backend/.env`

| Variable | Default | Purpose |
|---|---|---|
| `USE_MOCK_DATA` | `true` | Seeded in-memory data; no Firestore, no Gemini |
| `AUTH_REQUIRED` | `false` | When true, a missing/invalid token is rejected with 401 |
| `ALLOWED_ORIGINS` | `http://localhost:5173,...` | CORS allow-list. Never `*` |
| `GEMINI_API_KEY` | — | Google AI Studio key |
| `GOOGLE_CLOUD_PROJECT` | `proofaegis-hackathon` | Project id |
| `FIREBASE_SERVICE_ACCOUNT_JSON` | — | Service-account JSON, one line. **Never commit** |
| `GOOGLE_APPLICATION_CREDENTIALS` | — | Alternative: path to the key file |
| `STORAGE_BUCKET` | falls back to `FIREBASE_STORAGE_BUCKET` | `gs://name` or bare name |
| `STORAGE_BACKEND` | `auto` | `auto` \| `local` — `local` forces on-disk |
| `LOCAL_STORAGE_DIR` | `backend/.local_storage` | Where local uploads go |
| `MAX_UPLOAD_SIZE_MB` | `15` | Per file |
| `MAX_FILES_PER_REQUEST` | `20` | Per request only — a **case** has no document limit |
| `SIGNED_URL_TTL_MINUTES` | `15` | Signed-URL lifetime |
| `DEFAULT_WORKSPACE_ID` | `demo-workspace` | Scopes cases and storage paths |
| `AI_CALL_TIMEOUT_SECONDS` | `20` | Per Gemini call |
| `AI_CALL_MAX_RETRIES` | `1` | Retries before falling back |
| `PORT` | `8080` | Cloud Run sets this |

### Frontend — `proofaegis-frontend/.env.local` (dev) / `.env.production` (build)

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | Leave **blank** in production — the Hosting rewrite handles it |
| `VITE_USE_MOCK_DATA` | `false` in production. `true` builds a no-backend demo bundle |
| `VITE_FIREBASE_API_KEY` etc. | Firebase **web** config — public by design |

> The app shows mock data in exactly two situations: `VITE_USE_MOCK_DATA=true`,
> or demo mode explicitly turned on. **A failed request never silently produces
> sample data** — 401/403/500 and unreachable-backend all surface as errors.

---

## 8. Generating synthetic data

### Demo PDFs — for the upload workflow

```bash
cd backend; ./venv/Scripts/python.exe scripts/generate_synthetic_pdfs.py
```

Writes three case folders to `backend/data/synthetic_cases/`. The
`missing_receipt_001` case has no goods receipt **on purpose** — that absence is
the finding.

### Portfolio — for the analytics screens

```bash
cd backend; ./venv/Scripts/python.exe scripts/generate_synthetic_data.py --count 420
```

Writes `portfolio.json`, `portfolio.ndjson` and `vendors.json` to
`backend/data/generated/`. The RNG is seeded, so the same command always produces
the same portfolio.

Both outputs are gitignored — regenerate rather than commit them.

---

## 9. Tests, lint and build

```bash
cd backend; ./venv/Scripts/python.exe -m pytest -q
```

```bash
cd proofaegis-frontend; npm run lint
```

```bash
cd proofaegis-frontend; npm run build
```

The test suite pins `STORAGE_BACKEND=local` and `USE_MOCK_DATA=true`, so a
machine holding real credentials can never have a test run reach a live bucket.

### 9.1 Measured accuracy — the eval harness

Two harnesses, kept apart on purpose: a combined number would leave every
failure ambiguous between "read the document wrong" and "reasoned about it
wrong", and those have completely different fixes.

```bash
cd backend; ./venv/Scripts/python.exe -m eval.run_eval --count 320 --json data/generated/eval_report.json
```

```bash
cd backend; ./venv/Scripts/python.exe -m eval.extraction_eval --json data/generated/extraction_report.json
```

Both write JSON that the Analytics screen reads (`GET /api/analytics/accuracy`),
so the figures on that screen are a published result with a command behind
them rather than the system grading itself on request.

**How ground truth is established.** `eval/fixtures.py` generates the field
values that would appear on a purchase order, a goods receipt and an invoice,
perturbs them with a named defect, and then says nothing about the outcome.
The pipeline reads those values and decides for itself — through the *same*
code the product runs, `build_matching_input` and `evaluate_exception`, via a
datastore stand-in. The label comes from `expected_outcome()`, a deliberately
naive second implementation of the documented policy written from the
specification rather than from `matching_service.py`.

That duplication is the entire value. If the label came from the matcher, the
eval would be a tautology and a score of 1.000 would mean nothing.
`tests/test_eval_harness.py` asserts it stays that way, and includes a case
that feeds the scorer a prediction it knows is wrong — a scorer that cannot
fail is the one bug that would make every other number here worthless.

**What it found.** The harness paid for itself immediately. Five real defects,
all now fixed, all with a regression test:

| Found | Effect | Fix |
|---|---|---|
| Vendor names compared as raw strings | 21 of 21 spelling variants reported as `vendor_mismatch`; detection precision 1.00 → 0.87 | `vendor_key()` folds legal form, honorific and punctuation — and nothing else |
| The same rule implemented twice, differently | A duplicate went unreported because `history_service` folded names differently from the matcher | One rule, defined once, imported |
| Quantity check skipped itemized invoices | A 4.2% quantity variance silently cleared — money at risk, unflagged | `billable_quantity()` recovers the single-line case, and still declines the genuinely multi-line one |
| A near-duplicate outranked a bank change | Payment diversion reported as a possible re-submission, sending the reviewer to check the wrong thing | Exact duplicate → payment change → over-billing → near duplicate |
| Two label dialects unrecognised; a parser returning a document's own title as its supplier | `receipt_number` missing on 40% of layouts; `PURCHASE ORDER` extracted as a vendor name | Alias list widened; `looks_like_document_title()` guard |

**What these numbers do not cover.** The decision layer is scored on clean
field values, where deciding whether 2,650 is more than 5% above 2,400 is
arithmetic — and arithmetic does not have an error rate. The harness therefore
also applies document conditions a real corpus carries (a vendor name spelled
differently, a tax basis that does not line up, an itemized invoice with no
scalar quantity, an unreadable date) and reports clean and degraded separately.

The extraction harness renders each case in six dialects — different label
wording, value placement, fonts, table versus rows, money formats, page
clutter, and an unlabelled supplier block. That variation is real, and it is
variation this project authored. It does **not** cover scans, OCR noise, skew,
handwriting, multi-page documents, or the layouts of vendors nobody here has
seen. Treat it as a regression measure over a known population, not as an
estimate of accuracy on a real inbox.

---

## 10. Google Cloud setup

### 10.1 Project and login

```bash
gcloud auth login
```

```bash
gcloud config set project proofaegis
```

### 10.2 Enable APIs

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com firestore.googleapis.com storage.googleapis.com secretmanager.googleapis.com logging.googleapis.com
```

Vertex AI is **not** needed — Gemini is called through the AI Studio API key.

### 10.3 Firestore

Create the database once, in the same region as Cloud Run:

```bash
gcloud firestore databases create --location=asia-south1
```

Collections are created on first write: `invoice_exceptions`, `documents`,
`resolution_drafts`, `exception_reasoning`, `audit_events`, `settings`.

### 10.4 Cloud Storage bucket

Firebase Storage provisions `proofaegis.firebasestorage.app`. Confirm it exists:

```bash
gcloud storage buckets describe gs://proofaegis.firebasestorage.app
```

Keep it **private**. ProofAegis reads objects through the authenticated backend;
nothing needs public access.

### 10.5 Service account and IAM

```bash
gcloud iam service-accounts create proofaegis-api --display-name="ProofAegis API"
```

Grant only what the service uses:

```bash
gcloud projects add-iam-policy-binding proofaegis --member="serviceAccount:proofaegis-api@proofaegis.iam.gserviceaccount.com" --role="roles/datastore.user"
```

```bash
gcloud projects add-iam-policy-binding proofaegis --member="serviceAccount:proofaegis-api@proofaegis.iam.gserviceaccount.com" --role="roles/storage.objectAdmin"
```

```bash
gcloud projects add-iam-policy-binding proofaegis --member="serviceAccount:proofaegis-api@proofaegis.iam.gserviceaccount.com" --role="roles/firebaseauth.viewer"
```

> **Signed URLs need one more role.** `roles/iam.serviceAccountTokenCreator` on
> itself lets the service sign URLs without a private key. Skip it if you only
> use the authenticated document endpoint.

```bash
gcloud iam service-accounts add-iam-policy-binding proofaegis-api@proofaegis.iam.gserviceaccount.com --member="serviceAccount:proofaegis-api@proofaegis.iam.gserviceaccount.com" --role="roles/iam.serviceAccountTokenCreator"
```

### 10.6 Gemini API key in Secret Manager

Get a key from [Google AI Studio](https://aistudio.google.com/apikey), then:

```bash
printf '%s' 'YOUR_GEMINI_KEY' | gcloud secrets create gemini-api-key --data-file=-
```

```bash
gcloud secrets add-iam-policy-binding gemini-api-key --member="serviceAccount:proofaegis-api@proofaegis.iam.gserviceaccount.com" --role="roles/secretmanager.secretAccessor"
```

### 10.7 Firebase Authentication

In the Firebase console → **Authentication** → enable **Email/Password**. Under
**Settings → Authorized domains**, add `proofaegis.web.app` and
`proofaegis.firebaseapp.com`.

---

## 11. Deploy the backend to Cloud Run

Deployed from source — Cloud Build uses `backend/Dockerfile`. On Cloud Run the
service uses its attached identity, so **no service-account JSON is needed**.

```bash
cd backend; gcloud run deploy proofaegis-api --source . --region asia-south1 --service-account proofaegis-api@proofaegis.iam.gserviceaccount.com --set-env-vars USE_MOCK_DATA=false,AUTH_REQUIRED=true,GOOGLE_CLOUD_PROJECT=proofaegis,STORAGE_BUCKET=proofaegis.firebasestorage.app,ALLOWED_ORIGINS=https://proofaegis.web.app --set-secrets GEMINI_API_KEY=gemini-api-key:latest --min-instances 0 --max-instances 3 --memory 1Gi --cpu 1 --timeout 300 --allow-unauthenticated
```

**Why each flag matters:**

- `USE_MOCK_DATA=false` — **the single most important one.** It defaults to
  `true`, so a deploy that omits it serves seeded data from a real, billed
  service while reporting `mock_mode: true` on `/api/health`.
- `--min-instances 0` — scale to zero. You pay nothing while idle.
- `--max-instances 3` — caps a runaway bill.
- `--memory 1Gi` — PyMuPDF and the ADK client need headroom.
- `--allow-unauthenticated` — Cloud Run's own IAM is open because the app
  enforces Firebase ID tokens itself (`AUTH_REQUIRED=true`). Both layers being
  closed would break the Hosting rewrite.

Verify:

```bash
curl -s https://proofaegis-api-<hash>-el.a.run.app/api/health
```

Expect `{"status":"ok","mock_mode":false,"auth_required":true}`. **If
`mock_mode` is `true`, stop and fix `USE_MOCK_DATA` before going further.**

---

## 12. Deploy the frontend to Firebase Hosting

`firebase.json` already rewrites `/api/**` to the Cloud Run service
`proofaegis-api` in `asia-south1`, so the frontend calls the API **same-origin**
— no CORS, no API URL to configure.

### 12.1 Log in and select the project

```bash
firebase login
```

```bash
cd proofaegis-frontend; firebase use proofaegis
```

### 12.2 Production environment

Create `proofaegis-frontend/.env.production` from `.env.example`, leaving
`VITE_API_BASE_URL` **blank** and `VITE_USE_MOCK_DATA=false`.

### 12.3 Build and deploy

```bash
cd proofaegis-frontend; npm run deploy
```

That runs `vite build` then `firebase deploy --only hosting`. Live at
**https://proofaegis.web.app**.

Preview channel instead of production:

```bash
cd proofaegis-frontend; npm run deploy:preview
```

---

## 13. Seeding a live Firestore

Run from your machine with credentials in `backend/.env`.

Hero cases and tolerance rules only:

```bash
cd backend; ./venv/Scripts/python.exe scripts/seed_firestore.py
```

Hero cases **plus** the synthetic portfolio the analytics screens need:

```bash
cd backend; ./venv/Scripts/python.exe scripts/seed_firestore.py --portfolio
```

Portfolio only, leaving the hero cases untouched:

```bash
cd backend; ./venv/Scripts/python.exe scripts/seed_firestore.py --portfolio-only
```

Generate the portfolio first (section 8) or the script will tell you it is
missing. Without `--portfolio` the Analytics page will be empty in that
environment — exception *rate* has no denominator with three cases.

---

## 14. Cost control and budget alerts

This runs comfortably inside Google Cloud free credit.

**Set a budget before deploying.** Billing → Budgets & alerts → create a budget
with thresholds at **25 / 50 / 75 / 90%**.

| Service | Control |
|---|---|
| Cloud Run | `--min-instances 0` (scale to zero) and `--max-instances 3` |
| Gemini | Gemini Flash only; 20s timeout, 1 retry, then a deterministic fallback |
| Firestore | A few hundred small documents; reads are per-request and unbatched by design at this size |
| Cloud Storage | A handful of small PDFs |
| Cloud Build | Each deploy builds one image — delete old revisions and images |

Clean up old Cloud Run revisions:

```bash
gcloud run revisions list --service proofaegis-api --region asia-south1
```

**Recommended Storage lifecycle rule** — expire uploaded demo documents after 30
days so the bucket cannot grow unbounded:

```bash
printf '%s' '{"lifecycle":{"rule":[{"action":{"type":"Delete"},"condition":{"age":30}}]}}' > lifecycle.json
```

```bash
gcloud storage buckets update gs://proofaegis.firebasestorage.app --lifecycle-file=lifecycle.json
```

---

## 15. Post-deploy verification

Work through this before showing anyone:

1. `curl https://proofaegis.web.app/api/health` → `mock_mode: false`.
2. Open https://proofaegis.web.app in a **private window** — cold, no cached session.
3. Sign up or sign in with a real Firebase account.
4. The mode banner should read **API connected**, not "Backend serving seeded data".
5. Create a case and upload the PDFs from `backend/data/synthetic_cases/price_variance_001/`.
6. Confirm the case resolves to `price_variance`, **₹25,000**, owner Procurement.
7. Open the **Evidence graph** and hover the finding — its chain should light up.
8. Generate the explanation and the resolution draft; both must show
   **Human review required**.
9. Change the status and confirm the change appears in the **Audit trail** with
   your verified email as the actor.
10. Open **Analytics** and confirm the vendor risk chart has data.
11. Stop the Cloud Run service briefly and reload — you must see a visible
    **error**, never fabricated data.

---

## 16. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `mock_mode: true` in production | `USE_MOCK_DATA` was not set to `false` on the Cloud Run service. It defaults to `true` |
| Analytics page empty after deploying | Firestore was seeded without `--portfolio` |
| `401 unauthorized` on every request | `AUTH_REQUIRED=true` and the frontend is not sending an ID token — check the `VITE_FIREBASE_*` values in the build |
| "The ProofAegis API is not responding" | Cloud Run is cold-starting or stopped. Check `gcloud run services logs read proofaegis-api --region asia-south1` |
| Uploads fail with "Could not store this file" | `STORAGE_BUCKET` is wrong or the service account lacks `roles/storage.objectAdmin` |
| Signed URLs return 501 | Grant `roles/iam.serviceAccountTokenCreator`, or use the authenticated document endpoint |
| `run.ps1` blocked by PowerShell | `powershell -ExecutionPolicy Bypass -File .\run.ps1` |
| Port 5173 or 8080 already in use | An earlier dev server is still running — stop it first |
| A document uploads but fails processing | It is likely a scanned image with no text layer. OCR is not in this build |

---

## 17. Known limitations

Stated plainly, because a submission that hides these is worse than one that
names them.

- **Single workspace.** Every case and storage path is scoped to
  `DEFAULT_WORKSPACE_ID`, and a verified token's `workspace_id` claim is honoured
  if present — but any signed-in user still sees the same workspace. This is not
  multi-tenant isolation. It is scoped correctly at the data layer so enabling
  real per-tenant claims later is a claims-and-rules change, not a migration.
- **No role enforcement.** `AP_ANALYST` / `PROCUREMENT` / `CONTROLLER` / `AUDITOR`
  are not implemented; any authenticated user can set any user-settable status.
- **No OCR by default.** A scanned, image-only PDF fails with a clear message
  rather than being processed. `OCR_ENABLED=true` needs Tesseract on PATH.
- **The synthetic portfolio carries pre-computed outcomes.** Its figures follow
  the same rules as `matching_service.py` but are not produced by it. The three
  hero cases, anything you upload, and every case in the eval harness are fully
  computed by the pipeline.
- **Analytics run in Python over Firestore, not BigQuery.** The metric functions
  are written as single grouped aggregations over a bounded window — the shape a
  BigQuery executor would take — but that executor is not built, and neither is
  the MCP Toolbox analytics agent the brief suggested. At a few hundred records
  the Python path costs nothing and returns in milliseconds; at real volume it
  would not, and this is the most obvious next piece of work.
- **The disagreement ledger is process-local.** It counts what this server
  instance has run since it started, not a stored history. Restarting the
  backend resets it. That is the honest scope for a figure about model
  behaviour in a demo; a durable version is a Firestore collection away.
- **The measured disagreement rate has a small denominator.** The reasoning
  agent runs per case on demand, so unless somebody opens a few hundred cases
  the "model answered" count stays low and the rate is not statistically
  meaningful. The ledger reports the denominator next to the rate for exactly
  this reason — read them together.
- **Recurring-billing suppression needs three occurrences and readable dates.**
  A retainer that has only billed twice, or whose invoice dates the extractor
  could not read, is still reported as a near-duplicate. That default is
  deliberate: the burden of proof sits on the suppression, because a missed
  duplicate costs more than a noisy one.
- **Price drift needs a single-line document and a stable item description.**
  A multi-line invoice has no one unit price to trend, and a description that
  changes between invoices reads as a different product. Both return no
  finding rather than a guess.
- **No credit or debit notes.** They are the most conspicuous missing document
  type and they interact directly with over-billing — a credit note against an
  over-billed order is exactly the thing that would resolve the finding, and
  the running total cannot see it. `find_duplicate_invoices` will also treat a
  debit note carrying an original invoice number as an exact duplicate.
- **No FX.** Everything is INR; a foreign-currency invoice is compared as if
  the numbers were commensurate.
- **PDF only.** No email bodies, no images, no spreadsheets.
- **`frontend/` and root `scripts/` are obsolete duplicates**, and `render.yaml`
  and `backend/Procfile` describe a deployment path that is no longer supported.

---

## Licence and data

Synthetic demo data only — not for financial processing. ProofAegis does not
release payments, modify vendor bank details, make final accounting decisions,
or replace an ERP. Every AI-generated output requires human review.
