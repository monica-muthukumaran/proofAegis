# Google Technology Stack

Every Google product ProofAegis uses, why it was chosen, the exact commands,
and where the documentation lives.

Copy-paste ready. Every command below was written against the actual
configuration in this repository (`backend/Dockerfile`,
`proofaegis-frontend/firebase.json`, `backend/requirements.txt`).

---

## Contents

1. [At a glance](#1-at-a-glance)
2. [Set your variables once](#2-set-your-variables-once)
3. [Google Cloud CLI + Firebase CLI](#3-google-cloud-cli--firebase-cli)
4. [Project and APIs](#4-project-and-apis)
5. [Gemini via Google ADK](#5-gemini-via-google-adk)
6. [Cloud Firestore](#6-cloud-firestore)
7. [Cloud Storage](#7-cloud-storage)
8. [Firebase Authentication](#8-firebase-authentication)
9. [Cloud Run](#9-cloud-run)
10. [Firebase Hosting](#10-firebase-hosting)
11. [Secret Manager](#11-secret-manager)
12. [Artifact Registry](#12-artifact-registry)
13. [Cloud Logging and Monitoring](#13-cloud-logging-and-monitoring)
14. [Billing and budget alerts](#14-billing-and-budget-alerts)
15. [Cost model](#15-cost-model)
16. [Command cheat sheet](#16-command-cheat-sheet)
17. [Not used, and why](#17-not-used-and-why)
18. [Diagnosing "Gemini isn't working"](#18-diagnosing-gemini-isnt-working)

---

## 1. At a glance

| Product | Role | Package / config | Region |
|---|---|---|---|
| **Gemini via Vertex AI** | extraction, reasoning, drafting, hypotheses | `google-genai>=2.9,<3` | `global` |
| **Google ADK** | agent framework — schema-validated LLM calls | `google-adk==2.5.0` | — |
| **Cloud Firestore** | cases, documents, drafts, audit, settings | `google-cloud-firestore==2.16.1` | `asia-south1` |
| **Cloud Storage** | uploaded PDFs | `google-cloud-storage==2.18.2` | `asia-south1` |
| **Firebase Auth** | sign-in, ID tokens | `firebase-admin==6.5.0` | — |
| **Firebase Hosting** | static client + `/api` rewrite | `firebase.json` | global CDN |
| **Cloud Run** | the Flask API | `backend/Dockerfile` | `asia-south1` |
| **Secret Manager** | Gemini key, service-account JSON | — | `asia-south1` |
| **Artifact Registry** | container images | — | `asia-south1` |
| **Cloud Logging** | structured logs | built in | — |
| **Cloud Billing** | budget alerts | — | — |

**Why `asia-south1` (Mumbai).** The synthetic portfolio is an Indian AP
workspace — INR, GST, HSN/SAC codes, the Indian digit grouping. Keeping
Firestore, Storage and Cloud Run in one region avoids cross-region egress and
puts latency where the users would be. Firestore's location is **permanent**
once set.

### How the pieces connect

```
        Browser
           │
           ▼
  Firebase Hosting  ── serves dist/  ── global CDN
           │
           │  /api/**  (same-origin rewrite, no CORS preflight)
           ▼
     Cloud Run  ·  proofaegis-api  ·  asia-south1  ·  scale-to-zero
           │
    ┌──────┼───────────────┬──────────────────┐
    ▼      ▼               ▼                  ▼
 Gemini  Firestore   Cloud Storage    Firebase Auth
 (ADK)   7 collections  PDFs           ID token verify
```

---

## 2. Set your variables once

Every later command reuses these. Run this block first in each new shell.

**macOS / Linux / Git Bash**

```bash
export PROJECT_ID="proofaegis"
export REGION="asia-south1"
export SERVICE_NAME="proofaegis-api"
export BUCKET="${PROJECT_ID}.firebasestorage.app"
export HOSTING_URL="https://${PROJECT_ID}.web.app"
```

**Windows PowerShell**

```powershell
$env:PROJECT_ID   = "proofaegis"
$env:REGION       = "asia-south1"
$env:SERVICE_NAME = "proofaegis-api"
$env:BUCKET       = "$($env:PROJECT_ID).firebasestorage.app"
$env:HOSTING_URL  = "https://$($env:PROJECT_ID).web.app"
```

> Replace `proofaegis` with your own project ID if you are not using this one.
> Project IDs are globally unique.

---

## 3. Google Cloud CLI + Firebase CLI

### Install gcloud

- Docs: https://cloud.google.com/sdk/docs/install
- Windows installer: https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe

```bash
gcloud version
```

### Install the Firebase CLI

Already a dev dependency of the frontend, so this works with no global install:

```bash
cd proofaegis-frontend && npx firebase --version
```

Or install it globally:

```bash
npm install -g firebase-tools
```

- Docs: https://firebase.google.com/docs/cli

### Log in

```bash
gcloud auth login
```
```bash
gcloud auth application-default login
```
```bash
npx firebase login
```

The first authenticates the CLI. The second writes **Application Default
Credentials**, which is what lets the backend talk to Firestore and Storage
from your laptop without a key file. The third authenticates Firebase.

---

## 4. Project and APIs

### Create or select

```bash
gcloud projects create $PROJECT_ID --name="ProofAegis"
```
```bash
gcloud config set project $PROJECT_ID
```

Link billing (required for Cloud Run, Storage and Gemini beyond the free tier):

```bash
gcloud billing accounts list
```
```bash
gcloud billing projects link $PROJECT_ID --billing-account=YOUR_BILLING_ACCOUNT_ID
```

### Enable every API this project needs

```bash
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  generativelanguage.googleapis.com \
  firebase.googleapis.com \
  identitytoolkit.googleapis.com
```

| API | Needed for |
|---|---|
| `run.googleapis.com` | Cloud Run |
| `cloudbuild.googleapis.com` | building the container from source |
| `artifactregistry.googleapis.com` | storing that image |
| `firestore.googleapis.com` | the database |
| `storage.googleapis.com` | uploaded PDFs |
| `secretmanager.googleapis.com` | Gemini key, service-account JSON |
| `generativelanguage.googleapis.com` | the Gemini API |
| `firebase.googleapis.com` | Hosting |
| `identitytoolkit.googleapis.com` | Firebase Auth |

Verify:

```bash
gcloud services list --enabled --project=$PROJECT_ID
```

---

## 5. Gemini via Google ADK

**Agent Development Kit** is the framework; **Gemini** is the model. ADK is
what lets each agent declare a Pydantic `output_schema` that the framework
validates — so a malformed model response and an unreachable model are handled
identically, by falling back to a deterministic path.

- Gemini API docs: https://ai.google.dev/gemini-api/docs
- Get an API key: https://aistudio.google.com/app/apikey
- ADK docs: https://google.github.io/adk-docs/
- ADK Python repo: https://github.com/google/adk-python
- Pricing: https://ai.google.dev/pricing

### Models in use

| Setting | Default | Used by |
|---|---|---|
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` | agent 1 — document extraction |
| `GEMINI_REASONING_MODEL` | `gemini-3.5-flash` | agents 2, 3, 4 |

### 5.1 Which Gemini backend — and why it is Vertex

`google-genai` can reach Gemini two ways, and **the choice is a billing
decision, not a technical one**:

| Backend | Auth | Bills from |
|---|---|---|
| AI Studio Developer API | `GEMINI_API_KEY` | an AI Studio **prepay wallet** |
| **Vertex AI** ← in use | service account / ADC | **the Cloud project's billing account** |

Those are two separate wallets. Running on the Developer API produced:

```
429 RESOURCE_EXHAUSTED
"Your prepayment credits are depleted."
```

— while the Cloud console showed the full GCP trial credit **unused**. Both
were true at once. Switching to Vertex puts the spend where the credit
actually is.

It is config-only. No application code knows which backend it is on:

```bash
GOOGLE_GENAI_USE_VERTEXAI=true
GOOGLE_CLOUD_PROJECT=proofaegis
GOOGLE_CLOUD_LOCATION=global
```

Plus, once per project:

```bash
gcloud services enable aiplatform.googleapis.com --project=$PROJECT_ID
```
```bash
gcloud projects add-iam-policy-binding $PROJECT_ID   --member="serviceAccount:${SA}" --role="roles/aiplatform.user"
```

> **Grant the role to the account that actually runs the code.** Cloud Run uses
> its `--service-account`, which is usually *not* the Firebase Admin SDK
> account you use locally. Missing this gives
> `403 Permission 'aiplatform.endpoints.predict' denied`. IAM takes about a
> minute to propagate — a 403 immediately after granting is usually just that.

> **`GOOGLE_CLOUD_LOCATION=global` is deliberate.** Model availability is
> per-region. Probed 2026-09-04:
>
> | Region | `gemini-3.5-flash` | `gemini-3.5-flash-lite` |
> |---|---|---|
> | `asia-south1` | serves | **404** |
> | `us-central1` | **404** | **404** |
> | `global` | serves | serves |
>
> Pinning a region would silently lose the extraction model and send every
> upload down the deterministic fallback.

**Why pinned, not `-latest`.** The floating aliases resolve to the busiest
endpoint. `gemini-flash-latest` was measured at **75 seconds** — and returning
`503 UNAVAILABLE` — for a 427-character extraction that a pinned flash-lite
answers identically in about **1.4 seconds**. Extraction is structured and
low-judgement, so it gets the fast model; severity reasoning, drafting and
hypothesis ranking are language tasks and get the stronger one.

### The four agents

| # | File | Output schema | Fallback |
|---|---|---|---|
| 1 | `services/document_agent.py` | `InvoiceExtraction` etc. | `pdf_field_parser` — reads the real bytes |
| 2 | `services/exception_agent.py` | `ExceptionReasoning` | template over the computed `MatchResult` |
| 3 | `services/resolution_agent.py` | `ResolutionDraft` | cited template |
| 4 | `services/hypothesis_agent.py` | `HypothesisSet` — **no numeric field** | fixed catalogue |

### Set the key locally

```bash
echo "GEMINI_API_KEY=your-key-here" >> backend/.env
```

Without a key everything still works — the deterministic parser reads the real
PDF bytes and the UI labels the result as deterministic.

### Verify

```bash
cd backend && ./venv/Scripts/python.exe -c "from config import config; print('key set:', bool(config.GEMINI_API_KEY)); print('models:', config.GEMINI_MODEL, '|', config.GEMINI_REASONING_MODEL)"
```

---

## 6. Cloud Firestore

- Docs: https://firebase.google.com/docs/firestore
- Console: https://console.firebase.google.com/project/_/firestore

### Create the database

**Location is permanent.** Choose once.

```bash
gcloud firestore databases create --location=$REGION --type=firestore-native
```

### Collections

| Collection | Document ID | Holds |
|---|---|---|
| `invoice_exceptions` | `EXC-2026-XXXX` | the case record |
| `documents` | `DOC-XXXXXXXX` | per-document metadata + extraction |
| `exception_reasoning` | exception ID | agent 2 output, cached |
| `investigation_hypotheses` | exception ID | agent 4 output, cached |
| `resolution_drafts` | exception ID | agent 3 output, cached |
| `audit_events` | auto | FR-012 audit trail |
| `settings` | `tolerance_rules`, `approval_policy` | workspace policy |

### The one composite index you need

The cross-case query — the product's differentiator — scans documents across
cases:

```bash
gcloud firestore indexes composite create \
  --collection-group=documents \
  --field-config=field-path=workspace_id,order=ascending \
  --field-config=field-path=document_type,order=ascending \
  --field-config=field-path=processing_state,order=ascending
```

`workspace_id` leads it because the lookback stops at the workspace boundary —
the check asserts two documents are *the same bill*, and unscoped it would
report a new user's first genuine invoice as a duplicate of a seeded one. A
previously built two-field index no longer serves this query.

If you skip this, Firestore prints a one-click creation link the first time the
query runs. Check status:

```bash
gcloud firestore indexes composite list
```

### Seed it

```bash
cd backend && ./venv/Scripts/python.exe scripts/seed_firestore.py
```

Writes the three hero cases from `mock_data/seed_cases.json` plus the 320-case
portfolio from `data/generated/portfolio.json` — the same data the in-memory
datastore uses, so switching `USE_MOCK_DATA` off does not change what the demo
shows. Firestore caps a batch at 500 writes; the script batches at 400.

### Security rules

The API is the only writer, and it authenticates server-side. Lock clients out
entirely:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} { allow read, write: if false; }
  }
}
```

```bash
npx firebase deploy --only firestore:rules
```

---

## 7. Cloud Storage

- Docs: https://cloud.google.com/storage/docs
- Firebase Storage: https://firebase.google.com/docs/storage

### Create the bucket

```bash
gcloud storage buckets create gs://$BUCKET \
  --location=$REGION \
  --uniform-bucket-level-access \
  --public-access-prevention
```

`--public-access-prevention` matters: uploaded invoices are served through an
authenticated API route, never a bucket URL.

### Object path shape

```
workspaces/{workspace_id}/cases/{exception_id}/{document_id}.pdf
```

### The local mirror

`STORAGE_BACKEND=auto` uses GCS when a bucket **and** credentials are both
present, otherwise writes to `backend/.local_storage/` — **the same object
paths, on disk**. Local development and the whole test suite therefore exercise
the real ingestion code with zero cloud calls and zero cost. The test suite
pins `local`, so a developer machine holding real credentials can never have a
test run reach a live bucket.

### Optional lifecycle rule

```bash
cat > /tmp/lifecycle.json <<'JSON'
{"rule":[{"action":{"type":"Delete"},"condition":{"age":90}}]}
JSON
gcloud storage buckets update gs://$BUCKET --lifecycle-file=/tmp/lifecycle.json
```

### Verify

```bash
gcloud storage ls gs://$BUCKET/workspaces/
```

---

## 8. Firebase Authentication

- Docs: https://firebase.google.com/docs/auth
- Console: https://console.firebase.google.com/project/_/authentication/providers

Enable **Email/Password** in the console (there is no gcloud command for
enabling a provider).

Add your Hosting domains to the authorised list —
**Authentication → Settings → Authorized domains**:

```
proofaegis.web.app
proofaegis.firebaseapp.com
localhost
```

### How tokens flow

1. Client signs in → Firebase returns an ID token.
2. `services/api.js` attaches `Authorization: Bearer <token>` to every request.
3. `services/auth_service.py` verifies it with the Admin SDK.
4. `auth.py` populates `g.user` with the decoded claims.

`AUTH_REQUIRED=false` (the default) verifies a token when one is sent but never
blocks a request without one. `AUTH_REQUIRED=true` returns 401 immediately.

### Create a demo user

```bash
npx firebase auth:import users.json --project $PROJECT_ID
```

Or add one by hand in the console. With `VITE_FIREBASE_API_KEY` blank, the app
falls back to a `sessionStorage` demo account
(`judge@demo.proofaegis.local` / `demo-only`) and needs no Firebase project at
all.

---

## 9. Cloud Run

- Docs: https://cloud.google.com/run/docs
- Pricing: https://cloud.google.com/run/pricing

### Service account and IAM

```bash
gcloud iam service-accounts create proofaegis-api \
  --display-name="ProofAegis API runtime"
```
```bash
export SA="proofaegis-api@${PROJECT_ID}.iam.gserviceaccount.com"
```

Grant the minimum:

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" --role="roles/datastore.user"
```
```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" --role="roles/storage.objectAdmin"
```
```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" --role="roles/secretmanager.secretAccessor"
```
```bash
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:${SA}" --role="roles/firebaseauth.viewer"
```

| Role | Why |
|---|---|
| `datastore.user` | read/write Firestore |
| `storage.objectAdmin` | read/write objects in the bucket |
| `secretmanager.secretAccessor` | read the Gemini key at runtime |
| `firebaseauth.viewer` | verify ID tokens |

### Deploy from source

Cloud Build reads `backend/Dockerfile` — Python 3.12-slim, gunicorn, 1 worker,
4 threads, 120s timeout.

```bash
cd backend
gcloud run deploy $SERVICE_NAME \
  --source . \
  --region $REGION \
  --service-account $SA \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 3 \
  --memory 1Gi \
  --cpu 1 \
  --timeout 120 \
  --set-env-vars "USE_MOCK_DATA=false,AUTH_REQUIRED=true,GOOGLE_CLOUD_PROJECT=${PROJECT_ID},FIREBASE_STORAGE_BUCKET=${BUCKET},STORAGE_BUCKET=${BUCKET},ALLOWED_ORIGINS=${HOSTING_URL},DEFAULT_WORKSPACE_ID=demo-workspace" \
  --set-secrets "GEMINI_API_KEY=gemini-api-key:latest"
```

**`--allow-unauthenticated` is correct here.** Cloud Run's IAM layer is not the
auth boundary; Firebase ID tokens verified inside Flask are. Requiring IAM as
well would block the browser, which has no Google IAM identity.

**`--min-instances 0`** means scale to zero — you pay nothing when idle, at the
cost of a cold start of a few seconds on the first request after a quiet
period. For a demo, warm it up beforehand (see the demo guide).

### Verify

```bash
curl -s "$(gcloud run services describe $SERVICE_NAME --region $REGION --format='value(status.url)')/api/health"
```

Expect: `{"auth_required":true,"mock_mode":false,"status":"ok"}`

### Update just the environment

```bash
gcloud run services update $SERVICE_NAME --region $REGION \
  --update-env-vars "ALLOWED_ORIGINS=${HOSTING_URL}"
```

### Roll back

```bash
gcloud run revisions list --service $SERVICE_NAME --region $REGION
```
```bash
gcloud run services update-traffic $SERVICE_NAME --region $REGION \
  --to-revisions REVISION_NAME=100
```

---

## 10. Firebase Hosting

- Docs: https://firebase.google.com/docs/hosting

The config already in `proofaegis-frontend/firebase.json` does three things:

1. Serves `dist/`.
2. **Rewrites `/api/**` to the Cloud Run service** — so the API is same-origin.
   No CORS preflight, no `VITE_API_BASE_URL`, no cross-origin token handling.
3. Rewrites everything else to `/index.html`, so `/exceptions/EXC-2026-0001` is
   a real, shareable, refreshable URL.

```json
"rewrites": [
  { "source": "/api/**", "run": { "serviceId": "proofaegis-api", "region": "asia-south1", "pinTag": true } },
  { "source": "**", "destination": "/index.html" }
]
```

Caching is deliberate: `no-cache` on HTML so a deploy is picked up immediately,
`immutable` for a year on hashed assets.

### Deploy

```bash
cd proofaegis-frontend
npm install
npm run build
npx firebase deploy --only hosting --project $PROJECT_ID
```

Or the packaged script, which does build + deploy:

```bash
cd proofaegis-frontend && npm run deploy
```

### Preview channel — a temporary URL, no effect on production

```bash
cd proofaegis-frontend && npm run deploy:preview
```

---

## 11. Secret Manager

- Docs: https://cloud.google.com/secret-manager/docs

```bash
printf 'YOUR_GEMINI_API_KEY' | gcloud secrets create gemini-api-key \
  --data-file=- --replication-policy=automatic
```

Rotate:

```bash
printf 'NEW_KEY' | gcloud secrets versions add gemini-api-key --data-file=-
```

Grant access (already covered by the IAM step above):

```bash
gcloud secrets add-iam-policy-binding gemini-api-key \
  --member="serviceAccount:${SA}" --role="roles/secretmanager.secretAccessor"
```

`printf` rather than `echo`: `echo` appends a newline, and a trailing newline in
an API key produces a confusing 401.

---

## 12. Artifact Registry

Cloud Build pushes here automatically on `gcloud run deploy --source`.

```bash
gcloud artifacts repositories list --location=$REGION
```

Images accumulate and cost storage. Clean up periodically:

```bash
gcloud artifacts docker images list ${REGION}-docker.pkg.dev/${PROJECT_ID}/cloud-run-source-deploy
```

---

## 13. Cloud Logging and Monitoring

- Docs: https://cloud.google.com/logging/docs

Tail the API:

```bash
gcloud run services logs tail $SERVICE_NAME --region $REGION
```

Find every time the deterministic layer overrode the model:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND textPayload:"trust_override"' --limit 50
```

Find AI fallbacks:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND textPayload:"ai_call_failed"' --limit 50
```

Errors only, last hour:

```bash
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' --freshness=1h --limit 50
```

The backend logs structured events on purpose: `trust_override`,
`ai_call_failed`, `ai_call_exhausted_falling_back_to_mock`,
`trust_check_persist_failed`.

---

## 14. Billing and budget alerts

- Docs: https://cloud.google.com/billing/docs/how-to/budgets

```bash
gcloud billing budgets create \
  --billing-account=YOUR_BILLING_ACCOUNT_ID \
  --display-name="ProofAegis monthly" \
  --budget-amount=10USD \
  --threshold-rule=percent=50 \
  --threshold-rule=percent=90 \
  --threshold-rule=percent=100
```

Set this **before** the first deploy, not after.

---

## 15. Cost model

Realistic for a demo or a small pilot.

| Service | Free tier | What this app does | Practical cost |
|---|---|---|---|
| Cloud Run | 2M requests, 360k GB-s / month | scale-to-zero, max 3 instances | **₹0** at demo volume |
| Firestore | 50k reads, 20k writes, 1 GiB / day | ~330 cases | **₹0** |
| Cloud Storage | 5 GB | PDFs are tens of KB | **₹0** |
| Firebase Hosting | 10 GB transfer / month | ~500 kB bundle | **₹0** |
| Firebase Auth | 50k MAU | a handful | **₹0** |
| Secret Manager | 6 versions free | 1–2 | **₹0** |
| Artifact Registry | 0.5 GB | ~200 MB/image | pennies |
| **Gemini** | rate-limited free tier | see below | **the only real cost** |

### Where Gemini spend actually goes

Only three things call a model, and none of them run during upload:

| Action | Calls | Model |
|---|---|---|
| Extract fields from one document | 1 | flash-lite |
| Generate reasoning for a case | 1 | flash |
| Generate hypotheses for a case | 1 | flash |
| Generate a resolution draft | 1 | flash |

Analytics, matching, the evidence graph and every cross-case check are **free**
— they never touch a model.

Four cost controls are already in the code:

- Every analytics route takes a bounded `days` window (clamped to 730) and caps
  returned rows.
- Agent outputs are **cached** in Firestore; re-opening a case costs nothing.
- `AI_CALL_MAX_RETRIES=1` — one retry, then fall back.
- With no key, the app runs entirely deterministically and still demonstrates
  the full workflow.

---

## 16. Command cheat sheet

### Local

```bash
cd backend && ./venv/Scripts/python.exe app.py
```
```bash
cd proofaegis-frontend && npm run dev
```
```bash
cd backend && ./venv/Scripts/python.exe -m pytest -q
```

### Regenerate synthetic data

```bash
cd backend && ./venv/Scripts/python.exe scripts/generate_synthetic_data.py --count 320
```
```bash
cd backend && ./venv/Scripts/python.exe scripts/generate_synthetic_pdfs.py
```
```bash
cd backend && ./venv/Scripts/python.exe scripts/generate_synthetic_pdfs.py --all-layouts --out data/layout_variants
```

### Run the evals

```bash
cd backend && ./venv/Scripts/python.exe -m eval.run_eval --count 320 --json data/generated/eval_report.json
```
```bash
cd backend && ./venv/Scripts/python.exe -m eval.extraction_eval --json data/generated/extraction_report.json
```

### Deploy

```bash
cd backend && gcloud run deploy $SERVICE_NAME --source . --region $REGION
```
```bash
cd proofaegis-frontend && npm run deploy
```

### Inspect

```bash
gcloud run services describe $SERVICE_NAME --region $REGION
```
```bash
gcloud run services logs tail $SERVICE_NAME --region $REGION
```
```bash
gcloud firestore indexes composite list
```
```bash
gcloud storage ls gs://$BUCKET/workspaces/
```

---

## 17. Not used, and why

Stated plainly, because a stack diagram that implies more than was built is
worse than one that admits its edges.

| Product | Status |
|---|---|
| **BigQuery** | **Used**, as the analytics engine behind `ANALYTICS_ENGINE=bigquery`. `services/bigquery_executor.py` runs the five aggregations as SQL over a table partitioned on `created_at` and clustered on `vendor_id`; `services/analytics_gateway.py` dispatches, and the collection read lives inside the Firestore branch so the BigQuery path never loads a case into the process. The reason is the cross-case layer, not the analytics screen: every cross-case check answers a question about one invoice by reading the vendor's whole history, which Firestore serves as an unfiltered collection stream. `tests/test_bigquery_parity.py` runs the real SQL through DuckDB offline and asserts it produces the same numbers as the Python path. |
| **MCP Toolbox for Databases** | **Used.** `backend/mcp/tools.yaml` exposes the five analytics as parameterised BigQuery tools; `services/portfolio_agent.py` is the fifth ADK agent and the only one that reads data itself, answering "which vendors should we audit this quarter, and why" by calling them. There is deliberately **no tool that accepts SQL** — the agent picks a question and a window and cannot compose an aggregation, which puts the "a number a human acts on never comes from a model" boundary at the data layer rather than in a check afterwards. With the Toolbox unreachable the agent is not run against a substitute; it returns unavailable with no answer field. `tests/test_mcp_manifest.py` asserts every constant the YAML restates against its Python source. |
| **Vertex AI** | **Now the Gemini backend** — see §5.1. Switched from the AI Studio Developer API because that API bills from a separate prepay wallet, while Vertex bills the Cloud project and therefore draws on GCP credit. |
| **Document AI** | Not used. PyMuPDF plus a deterministic parser reads the text layer exactly and for free. Document AI would be the right answer for scans at volume — see the OCR limitation. |
| **Cloud Tasks / Pub-Sub** | Not used. Ingestion is synchronous within a request. Fine at demo volume; a queue is the right shape for bulk intake. |
| **Cloud Scheduler** | Not used. Email intake exposes a manual poll endpoint rather than running on a timer. |
| **Cloud Armor / Load Balancing** | Not used. Hosting fronts Cloud Run directly. |

---

## See also

- [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) — the same commands, in order, explained step by step
- [`ARCHITECTURE_BACKEND.md`](ARCHITECTURE_BACKEND.md)
- [`README.md`](README.md) — limitations

---

## 18. Diagnosing "Gemini isn't working"

The failure is almost never in the application code — every AI call falls back
to a deterministic path, so the symptom is always the same ("model unavailable"
in the UI) regardless of cause. Work down this list; each step produces a
different, unambiguous error.

### Step 1 — is the key the right *kind* of key?

A Firebase **Web API key** and a Gemini API key are both Google API keys and
look interchangeable. They are not.

| Key | Format | Length | Works for Gemini |
|---|---|---|---|
| AI Studio / Gemini | `AQ.…` | ~53 | **yes** |
| Google Cloud / Firebase Web | `AIza…` | ~39 | only if unrestricted **and** the API is enabled |

```bash
cd backend && ./venv/Scripts/python.exe -c "from config import config; k=config.GEMINI_API_KEY; print(len(k), k[:4]+'...'+k[-4:])"
```

> If `GEMINI_API_KEY` matches `VITE_FIREBASE_API_KEY` in the frontend env, that
> is the bug. Get a real key at https://aistudio.google.com/app/apikey

### Step 2 — can the key reach the API at all?

```bash
curl -s "https://generativelanguage.googleapis.com/v1beta/models?key=$GEMINI_API_KEY" | head -c 400
```

| Response | Meaning | Fix |
|---|---|---|
| A JSON list of models | Key is valid | Go to step 3 |
| `403 API_KEY_SERVICE_BLOCKED` | The key has **API restrictions** excluding `generativelanguage.googleapis.com` | Use an AI Studio key, or lift the restriction in **Cloud Console → APIs & Services → Credentials** |
| `400 API_KEY_INVALID` | Wrong or truncated key | Re-copy it. Check for a trailing newline (`printf`, not `echo`) |

### Step 3 — does the model name still exist?

**A model appearing in `ListModels` does not mean you can call it.** Retired
models remain listed and fail only on `generateContent`. Probe properly:

```bash
curl -s -X POST \
  "https://generativelanguage.googleapis.com/v1beta/models/${GEMINI_MODEL}:generateContent?key=${GEMINI_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"contents":[{"parts":[{"text":"hi"}]}]}' | head -c 400
```

| Response | Meaning |
|---|---|
| `404 … no longer available to new users` | The model is retired. The message names its replacement |
| `429 RESOURCE_EXHAUSTED` | Model name is fine — this is **billing or quota** |
| A completion | Working |

### Step 4 — is there credit left, *in the right wallet*?

**This is the one that wastes the most time.** Google Cloud credit and the AI
Studio prepay wallet are separate balances. You can be looking at a Cloud
console showing ₹28,694 unused while the API insists your credits are
depleted — and both statements are correct, because they describe different
wallets.

| Symptom | Which wallet is empty |
|---|---|
| `429` naming **"prepayment credits"** and linking to `ai.studio` | the AI Studio wallet |
| `429` naming a quota or rate limit | per-project rate limits, not money |

Two ways out:

1. Fund the AI Studio wallet at https://ai.studio/projects, or
2. **Switch to Vertex AI**, which bills the Cloud project and therefore uses
   GCP credit. See §5.1 — it is three environment variables, one API enable and
   one IAM binding. No application code changes.


Billing docs: https://ai.google.dev/gemini-api/docs/billing#prepay

### Step 5 — deployed only

```bash
gcloud run services describe $SERVICE_NAME --region $REGION --format=json | grep -A3 GEMINI
```
```bash
gcloud secrets versions access latest --secret=gemini-api-key | wc -c
```

Check the secret is mounted, and that its length matches an AI Studio key.

If you are on Vertex, check the **runtime** service account has
`roles/aiplatform.user` — Cloud Run does not use the account you authenticate
with locally:

```bash
gcloud projects get-iam-policy $PROJECT_ID --flatten="bindings[].members"   --filter="bindings.members:$(gcloud run services describe $SERVICE_NAME --region $REGION --format='value(spec.template.spec.serviceAccountName)')"   --format="value(bindings.role)"
```

**Model names are baked into the image** unless you override them. `config.py`
supplies the defaults, so changing them locally has **no effect on the deployed
service until you redeploy** — or set them explicitly:

```bash
gcloud run services update $SERVICE_NAME --region $REGION \
  --update-env-vars "GEMINI_MODEL=gemini-3.5-flash-lite,GEMINI_REASONING_MODEL=gemini-3.5-flash"
```

### What the app does while Gemini is down

Nothing breaks. Extraction falls back to the deterministic parser reading the
real PDF bytes; reasoning and resolution fall back to templates over the
computed `MatchResult`; hypotheses fall back to a fixed catalogue. Every
response is labelled `source: "mock"`, and the UI says so rather than passing
deterministic output off as model output.

**Every number stays correct** — matching, financial impact, match score, the
evidence graph, the cross-case checks and all analytics never call a model.
