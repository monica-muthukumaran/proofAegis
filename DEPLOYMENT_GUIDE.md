# Deployment Guide

Getting ProofAegis running — first on your own machine, then on the internet.

**This guide assumes nothing.** Every command is written out. Every value you
have to invent is marked. If a step can fail, the failure is listed underneath
it with the fix.

Read Part 1 even if you only care about Part 2 — deploying something you have
never run locally is how you end up debugging two problems at once.

---

## Contents

**Part 1 — On your machine**
1. [What you need installed](#1-what-you-need-installed)
2. [Get the code running](#2-get-the-code-running)
3. [Check it works](#3-check-it-works)

**Part 2 — On the internet**
4. [What you are about to build](#4-what-you-are-about-to-build)
5. [Create the Google Cloud project](#5-create-the-google-cloud-project)
6. [Turn on the services](#6-turn-on-the-services)
7. [Create the database](#7-create-the-database)
8. [Create the file bucket](#8-create-the-file-bucket)
9. [Turn on sign-in](#9-turn-on-sign-in)
10. [Store the Gemini key safely](#10-store-the-gemini-key-safely)
11. [Create the robot account](#11-create-the-robot-account)
12. [Deploy the backend](#12-deploy-the-backend)
13. [Put data in the database](#13-put-data-in-the-database)
14. [Deploy the frontend](#14-deploy-the-frontend)
15. [Connect the two](#15-connect-the-two)
16. [Check everything works](#16-check-everything-works)

**Part 3 — Living with it**
17. [Updating after a change](#17-updating-after-a-change)
18. [Watching for problems](#18-watching-for-problems)
19. [Not getting a surprise bill](#19-not-getting-a-surprise-bill)
20. [When something breaks](#20-when-something-breaks)
21. [Taking it all down](#21-taking-it-all-down)

---

# Part 1 — On your machine

## 1. What you need installed

Four things. Check each one before moving on.

### Python 3.12 or newer

```bash
python --version
```

If that fails or shows 3.11 or lower: https://www.python.org/downloads/

> **Windows:** tick **"Add Python to PATH"** during install. Almost every
> "python is not recognized" problem is this checkbox.

### Node.js 20 or newer

```bash
node --version
```

If that fails: https://nodejs.org/ — take the LTS version.

### Git

```bash
git --version
```

If that fails: https://git-scm.com/downloads

### A terminal

- **Windows** — Git Bash (comes with Git) or PowerShell
- **macOS** — Terminal
- **Linux** — you already have one

> Commands below are written for Git Bash / macOS / Linux. Where PowerShell
> differs, the PowerShell version is given too.

---

## 2. Get the code running

### 2.1 Open a terminal in the project folder

```bash
cd path/to/ProofAegis
```

Replace `path/to` with wherever you put it. On Windows you can type `cd `, then
drag the folder onto the terminal window.

### 2.2 Set up the backend

**Create a virtual environment.** This is a private box for this project's
Python packages, so they never clash with anything else on your computer.

```bash
cd backend
```
```bash
python -m venv venv
```

**Turn it on:**

macOS / Linux / Git Bash:
```bash
source venv/Scripts/activate
```

PowerShell:
```powershell
.\venv\Scripts\Activate.ps1
```

> On macOS/Linux the path is `venv/bin/activate`, not `venv/Scripts/activate`.

You will see `(venv)` at the start of your prompt. That means it worked.

**Install the packages:**

```bash
pip install -r requirements.txt
```

Takes a minute or two.

### 2.3 Start the backend

```bash
python app.py
```

You should see:

```
 * Running on http://0.0.0.0:8080
```

**Leave this window open.** The backend is now running. Everything else happens
in a *second* terminal window.

> **Nothing to configure yet.** With no cloud credentials the app automatically
> uses an in-memory database and stores files on disk. It is fully working.

### 2.4 Set up the frontend

Open a **new** terminal window, in the project folder.

```bash
cd proofaegis-frontend
```
```bash
npm install
```
```bash
npm run dev
```

You should see:

```
  ➜  Local:   http://localhost:5173/
```

### 2.5 Open it

Go to **http://localhost:5173**

Sign in with:

```
judge@demo.proofaegis.local
demo-only
```

Or click **Start guided tour** — no login needed.

**That is it. It is running.**

---

## 3. Check it works

### The tests

In the backend terminal (stop the server with `Ctrl+C` first):

```bash
python -m pytest -q
```

Expect: **185 passed**

### The evals

These produce the accuracy figures the Analytics screen shows.

```bash
python -m eval.run_eval --count 320 --json data/generated/eval_report.json
```
```bash
python -m eval.extraction_eval --json data/generated/extraction_report.json
```

### Fresh sample data

```bash
python scripts/generate_synthetic_data.py --count 320
```
```bash
python scripts/generate_synthetic_pdfs.py
```

The PDFs land in `backend/data/synthetic_cases/` — drag them into the app to
watch the whole pipeline run.

Restart the backend when you are done:

```bash
python app.py
```

---

### Part 1 troubleshooting

| Problem | Fix |
|---|---|
| `python is not recognized` | Python is not on PATH. Reinstall with "Add to PATH" ticked |
| `pip is not recognized` | Use `python -m pip install -r requirements.txt` |
| `Port 8080 is already in use` | Something else is using it. `npx kill-port 8080`, or change the port: `PORT=8081 python app.py` |
| `Port 5173 is already in use` | `npx kill-port 5173` |
| `cannot be loaded because running scripts is disabled` (PowerShell) | Run `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` then activate again |
| `ModuleNotFoundError` | The virtual environment is not active. Look for `(venv)` in your prompt |
| Frontend loads, but "Cannot reach the API" | The backend terminal is not running. Check window one |

---

# Part 2 — On the internet

## 4. What you are about to build

Two pieces, and one clever join between them.

```
        Anyone with the link
                 │
                 ▼
      Firebase Hosting          ← your website, on Google's CDN
                 │
                 │  anything starting with /api goes to ↓
                 ▼
         Cloud Run              ← your Python backend, in a container
                 │
    ┌────────────┼────────────┬──────────────┐
    ▼            ▼            ▼              ▼
 Firestore  Cloud Storage  Firebase Auth  Gemini
 (database)   (the PDFs)    (sign-in)     (the AI)
```

**The clever join:** Firebase Hosting forwards `/api/**` to Cloud Run, so the
browser thinks the API is part of the website. Same origin, so no CORS
problems, no API URL to configure.

**Time:** 45–60 minutes the first time.
**Cost:** ₹0 for a demo. Everything sits in free tiers except a few pennies of
image storage. Full breakdown in [`GOOGLE_STACK.md` §15](GOOGLE_STACK.md).

### Before you start

You need a Google account and a **credit card on file**. Google requires one
even for free-tier usage. You will not be charged at demo volume, and §19 shows
how to set a hard alert.

---

## 5. Create the Google Cloud project

### 5.1 Install the Google Cloud CLI

https://cloud.google.com/sdk/docs/install

Windows direct download:
https://dl.google.com/dl/cloudsdk/channels/rapid/GoogleCloudSDKInstaller.exe

Verify — **close and reopen your terminal first**:

```bash
gcloud version
```

### 5.2 Log in

```bash
gcloud auth login
```

A browser opens. Sign in, allow access.

```bash
gcloud auth application-default login
```

Yes, both. The first logs in the tool; the second creates credentials your code
can use.

### 5.3 Set your variables

**Every command from here uses these.** If you close your terminal, run this
block again.

Pick a project ID: lowercase, numbers and hyphens, **globally unique across all
of Google Cloud**. If `proofaegis` is taken, try `proofaegis-yourname`.

macOS / Linux / Git Bash:
```bash
export PROJECT_ID="proofaegis"
export REGION="asia-south1"
export SERVICE_NAME="proofaegis-api"
export BUCKET="${PROJECT_ID}.firebasestorage.app"
export HOSTING_URL="https://${PROJECT_ID}.web.app"
```

PowerShell:
```powershell
$env:PROJECT_ID   = "proofaegis"
$env:REGION       = "asia-south1"
$env:SERVICE_NAME = "proofaegis-api"
$env:BUCKET       = "$($env:PROJECT_ID).firebasestorage.app"
$env:HOSTING_URL  = "https://$($env:PROJECT_ID).web.app"
```

> **`asia-south1` is Mumbai.** Change it if your users are elsewhere —
> `europe-west1`, `us-central1`. Pick once: **the database region cannot be
> changed later.**

### 5.4 Create it

```bash
gcloud projects create $PROJECT_ID --name="ProofAegis"
```
```bash
gcloud config set project $PROJECT_ID
```

> `Requested entity already exists` → that ID is taken. Pick another and redo
> §5.3.

### 5.5 Attach billing

```bash
gcloud billing accounts list
```

Copy the `ACCOUNT_ID` (looks like `01AB23-CD45EF-6789GH`):

```bash
gcloud billing projects link $PROJECT_ID --billing-account=PASTE_IT_HERE
```

> No billing account? Create one at
> https://console.cloud.google.com/billing — free tier still applies.

### 5.6 Add Firebase to the project

Go to https://console.firebase.google.com/ → **Add project** → choose the
project you just created → continue. Google Analytics is optional; skip it.

---

## 6. Turn on the services

Nine APIs, one command:

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

Takes a minute. Verify:

```bash
gcloud services list --enabled
```

---

## 7. Create the database

**The region is permanent.** Get it right.

```bash
gcloud firestore databases create --location=$REGION --type=firestore-native
```

### The one index you need

The cross-case check — the whole differentiator — searches documents across
cases, and Firestore needs an index for that:

```bash
gcloud firestore indexes composite create \
  --collection-group=documents \
  --field-config=field-path=document_type,order=ascending \
  --field-config=field-path=processing_state,order=ascending
```

Takes a few minutes to build. Check:

```bash
gcloud firestore indexes composite list
```

> Skip it and nothing breaks immediately — Firestore prints a one-click
> creation link the first time the query runs. But do it now.

---

## 8. Create the file bucket

Where uploaded PDFs live.

```bash
gcloud storage buckets create gs://$BUCKET \
  --location=$REGION \
  --uniform-bucket-level-access \
  --public-access-prevention
```

> `--public-access-prevention` means **nobody can reach an invoice by guessing
> a URL**. Files are served through the API, which checks who is asking.

Verify:

```bash
gcloud storage ls
```

---

## 9. Turn on sign-in

This one is in the web console — there is no command for it.

1. https://console.firebase.google.com/ → your project
2. **Build → Authentication → Get started**
3. **Sign-in method** tab → **Email/Password** → **Enable** → **Save**

### Allow your website to sign people in

Still in Authentication → **Settings** → **Authorized domains** → **Add
domain**:

```
proofaegis.web.app
proofaegis.firebaseapp.com
```

(Substitute your project ID.) `localhost` is usually there already — leave it.

### Get the web config

**Project settings** (gear icon) → scroll to **Your apps** → **Web** (`</>`) →
register the app → copy the `firebaseConfig` block. **Keep it open**, you need
it in §14.

### Create a demo user

**Authentication → Users → Add user.** Any email and password. This is what you
sign in with.

---

## 10. Store the Gemini key safely

### 10.1 Get a key

https://aistudio.google.com/app/apikey → **Create API key** → copy it.

### 10.2 Put it in Secret Manager

Never paste a key into a config file or a deploy command.

```bash
printf 'PASTE_YOUR_KEY_HERE' | gcloud secrets create gemini-api-key \
  --data-file=- --replication-policy=automatic
```

> **Use `printf`, not `echo`.** `echo` adds an invisible newline to the end,
> and a key with a trailing newline produces a confusing 401 later.

PowerShell:
```powershell
"PASTE_YOUR_KEY_HERE" | Out-File -Encoding ascii -NoNewline key.txt
gcloud secrets create gemini-api-key --data-file=key.txt --replication-policy=automatic
Remove-Item key.txt
```

Verify:

```bash
gcloud secrets list
```

> **No key?** Skip this section and drop `--set-secrets` from §12. Everything
> still works — the app reads documents with its own parser and labels the
> output as deterministic.

---

## 11. Create the robot account

Your backend is not a person, so it needs its own identity with exactly the
permissions it needs and nothing more.

```bash
gcloud iam service-accounts create proofaegis-api \
  --display-name="ProofAegis API runtime"
```
```bash
export SA="proofaegis-api@${PROJECT_ID}.iam.gserviceaccount.com"
```

PowerShell:
```powershell
$env:SA = "proofaegis-api@$($env:PROJECT_ID).iam.gserviceaccount.com"
```

Grant four permissions, one command each:

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

| Permission | Lets the backend |
|---|---|
| `datastore.user` | read and write the database |
| `storage.objectAdmin` | read and write uploaded PDFs |
| `secretmanager.secretAccessor` | read the Gemini key |
| `firebaseauth.viewer` | check that a signed-in user is really signed in |

---

## 12. Deploy the backend

The big one. Google builds a container from `backend/Dockerfile` and runs it.

```bash
cd backend
```

```bash
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

If asked to enable an API or create a repository, say **yes**. First deploy
takes 3–5 minutes.

### What those settings mean

| Setting | Meaning |
|---|---|
| `--allow-unauthenticated` | Anyone can *reach* the URL. Sign-in is checked **inside** the app — a browser has no Google identity, so this has to be open |
| `--min-instances 0` | Scales to zero. **You pay nothing when nobody is using it.** Costs a few seconds of cold start on the first request |
| `--max-instances 3` | A hard ceiling, so a traffic spike cannot produce a large bill |
| `USE_MOCK_DATA=false` | Use the real database |
| `AUTH_REQUIRED=true` | Reject requests without a valid sign-in |

### Get your API URL

```bash
gcloud run services describe $SERVICE_NAME --region $REGION --format='value(status.url)'
```

Test it:

```bash
curl -s "$(gcloud run services describe $SERVICE_NAME --region $REGION --format='value(status.url)')/api/health"
```

Expect:

```json
{"auth_required":true,"mock_mode":false,"status":"ok"}
```

> `"mock_mode":true` means it cannot see the database. Check the service
> account was passed with `--service-account`.

---

## 13. Put data in the database

Your database is empty. Fill it with the demo cases.

### 13.1 Create a key file (temporarily)

```bash
gcloud iam service-accounts keys create key.json --iam-account=$SA
```

> **This file is a password.** Do not commit it. You delete it in 13.4.

### 13.2 Seed

macOS / Linux / Git Bash:
```bash
export GOOGLE_APPLICATION_CREDENTIALS=./key.json
export GOOGLE_CLOUD_PROJECT=$PROJECT_ID
python scripts/seed_firestore.py
```

PowerShell:
```powershell
$env:GOOGLE_APPLICATION_CREDENTIALS = ".\key.json"
$env:GOOGLE_CLOUD_PROJECT = $env:PROJECT_ID
python scripts\seed_firestore.py
```

This writes the three hero cases and the 320-case portfolio.

### 13.3 Lock the database

The API is the only thing that should ever write here. Create
`firestore.rules` in the project root:

```
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} { allow read, write: if false; }
  }
}
```

```bash
npx firebase deploy --only firestore:rules --project $PROJECT_ID
```

> This blocks *browsers*, not your backend. The backend authenticates as the
> service account and bypasses these rules by design.

### 13.4 Delete the key file

```bash
rm key.json
```

PowerShell:
```powershell
Remove-Item key.json
```

**Do not skip this.**

---

## 13A. BigQuery and MCP Toolbox

Both are optional. The app runs fully without them — `ANALYTICS_ENGINE`
defaults to `firestore` and the portfolio agent reports "not configured"
rather than answering. Set them up when you want the analytics served by
BigQuery and the agent able to query it.

### 13A.1 Why this exists

Not because the analytics screen is slow. Every cross-case check — duplicate,
cumulative over-billing, changed bank details, price drift, cadence — answers
a question about ONE invoice by reading the vendor's WHOLE history, and
Firestore serves that with an unfiltered collection stream. At 320 cases that
is free; at real volume it is a full-collection scan per invoice, of exactly
the feature that makes this product different. See the module docstring in
`backend/services/bigquery_executor.py`.

### 13A.2 Enable the API and create the table

```bash
gcloud services enable bigquery.googleapis.com --project=$PROJECT_ID
```

```bash
cd backend && python -m scripts.load_bigquery --create
```

This creates the dataset in `BIGQUERY_LOCATION` (default `asia-south1`, same
region as everything else) and a table partitioned on `DATE(created_at)` and
clustered on `vendor_id, exception_type`. Both matter: the partition prunes
the date window every query carries, and the cluster serves the per-vendor
history read.

### 13A.3 Load the cases

```bash
cd backend && python -m scripts.load_bigquery --from-firestore
```

Or from a generated portfolio file:

```bash
cd backend && python -m scripts.load_bigquery --from-file data/generated/portfolio.json
```

Both **truncate before loading**. A portfolio file is a whole population, and
appending it twice would double every count on every analytics screen.

Check it:

```bash
cd backend && python -m scripts.load_bigquery --verify
```

### 13A.4 Grant the service account access

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID   --member="serviceAccount:$SA" --role="roles/bigquery.dataViewer"
```

```bash
gcloud projects add-iam-policy-binding $PROJECT_ID   --member="serviceAccount:$SA" --role="roles/bigquery.jobUser"
```

`dataViewer` reads the table; `jobUser` runs the query. Read-only on purpose —
nothing in the serving path writes to BigQuery, only `load_bigquery.py` does,
and you run that yourself.

### 13A.5 Switch the engine on

```bash
gcloud run services update proofaegis-api --region=asia-south1   --update-env-vars "ANALYTICS_ENGINE=bigquery"
```

`GET /api/settings` now reports `analytics_engine: bigquery` and the table it
is reading. If it still says `firestore`, the variable did not reach the
revision — check `gcloud run services describe`.

> **Rolling back is one command.** Set `ANALYTICS_ENGINE=firestore` and the
> Python path serves the same numbers. `tests/test_bigquery_parity.py` is what
> makes that claim safe rather than hopeful.

### 13A.6 MCP Toolbox

`backend/mcp/tools.yaml` exposes the five analytics as parameterised BigQuery
tools. There is deliberately no tool that accepts SQL: the agent picks a
question and a window and cannot compose an aggregation.

Install the Toolbox server and run it against the manifest:

```bash
toolbox --tools-file backend/mcp/tools.yaml --port 5000
```

It substitutes `${GOOGLE_CLOUD_PROJECT}`, `${BIGQUERY_DATASET}` and
`${BIGQUERY_TABLE}` from the environment, so export those first. Nothing in
that file is a secret and no key is stored in it.

Point the backend at it:

```bash
gcloud run services update proofaegis-api --region=asia-south1   --update-env-vars "MCP_TOOLBOX_URL=https://your-toolbox-host"
```

Then `POST /api/analytics/ask` with `{"question": "Which vendors should I
audit this quarter?"}`. The response carries `tools_called` — an answer with
an empty list is prose, not data, and the UI labels it as such.

If the Toolbox is unreachable the agent is **not** run against a substitute.
It returns `available: false` with no answer field. An agent that answers a
portfolio question from memory with its tools down produces confident text
with nothing behind it, which is the failure this product argues against.

### 13A.7 Cost

The table is a few hundred rows and every query is partition-pruned to a
bounded window, so this sits inside the BigQuery free tier (1 TB of query
processing per month).

`--verify` measures that rather than claiming it: it dry-runs the whole table
and a 30-day window and prints the bytes each would process. If the two
numbers are equal the partition is not pruning, and it says so. A dry run is
billed at nothing, so this is safe to run before switching production over.

---

## 14. Deploy the frontend

```bash
cd ../proofaegis-frontend
```

### 14.1 Production config

Create `.env.production` and paste the values from §9:

```bash
VITE_USE_MOCK_DATA=false
VITE_API_BASE_URL=
VITE_FIREBASE_API_KEY=paste-from-firebase-console
VITE_FIREBASE_AUTH_DOMAIN=proofaegis.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=proofaegis
VITE_FIREBASE_STORAGE_BUCKET=proofaegis.firebasestorage.app
VITE_FIREBASE_MESSAGING_SENDER_ID=paste-from-firebase-console
VITE_FIREBASE_APP_ID=paste-from-firebase-console
```

> **`VITE_API_BASE_URL` stays empty.** That is not a mistake. Hosting forwards
> `/api` to Cloud Run, so the frontend just asks its own address.
>
> **`VITE_USE_MOCK_DATA=false`** matters: `true` builds a bundle that shows
> sample data instead of your real backend.

### 14.2 Point at your project

Edit `.firebaserc`:

```json
{ "projects": { "default": "proofaegis" } }
```

And in `firebase.json`, confirm these match your setup:

```json
"hosting": {
  "site": "proofaegis",
  ...
  "rewrites": [
    { "source": "/api/**", "run": { "serviceId": "proofaegis-api", "region": "asia-south1", "pinTag": true } },
    { "source": "**", "destination": "/index.html" }
  ]
}
```

`serviceId` must equal your `$SERVICE_NAME`, `region` your `$REGION`, `site`
your project ID.

### 14.3 Build and deploy

```bash
npm install
```
```bash
npm run build
```
```bash
npx firebase login
```
```bash
npx firebase deploy --only hosting --project $PROJECT_ID
```

You get:

```
Hosting URL: https://proofaegis.web.app
```

**That is your live app.**

---

## 15. Connect the two

The backend needs to trust requests from your new website.

```bash
gcloud run services update $SERVICE_NAME --region $REGION \
  --update-env-vars "ALLOWED_ORIGINS=https://${PROJECT_ID}.web.app"
```

> If you set `$HOSTING_URL` in §5.3 and it matches, this was already correct
> from §12. Running it again is harmless.

---

## 16. Check everything works

Go through all six.

### 16.1 The website loads
Open `https://proofaegis.web.app`.

### 16.2 The API answers
```bash
curl -s https://proofaegis.web.app/api/health
```
Expect `{"auth_required":true,"mock_mode":false,"status":"ok"}`.

> This URL goes through Hosting. If it works, the rewrite is correct.

### 16.3 Sign-in works
Use the user from §9. You should land on the Dashboard.

### 16.4 Data is there
Open **Exceptions**. You should see cases including `EXC-2026-0001`.

### 16.5 Upload works
**New case from PDFs** → upload from `backend/data/synthetic_cases/price_variance_001/`
→ the case should analyse and show a price variance.

### 16.6 Analytics works
Open **Analytics**. You should see the cross-case panel with a figure.

> *"No eval run has been recorded"* is expected — that panel reads a local
> file. Run the evals and redeploy the backend if you want it live.

**All six pass? You are deployed.**

---

# Part 3 — Living with it

## 17. Updating after a change

### Backend — use the script

```bash
cd backend && ./deploy.sh
```

`backend/deploy.sh` carries the whole configuration: eleven environment
variables, the secret mount, the runtime service account, and the Vertex
settings. Typed by hand that command is wrong often enough to matter, and the
worst mistake is silent — a missing `GOOGLE_GENAI_USE_VERTEXAI` does not
error, it points every AI call at the empty AI Studio wallet and the app
degrades to its deterministic fallback while looking perfectly healthy.

| Flag | Does |
|---|---|
| *(none)* | preflight, deploy, verify |
| `--dry-run` | print every command, run none |
| `--setup` | also enable APIs and grant IAM (first run on a new project) |
| `--skip-verify` | don't poll `/api/health` |

Override anything from the environment: `REGION=us-central1 ./deploy.sh`.

> ### The trap this script exists to catch
>
> `firebase.json` sets `"pinTag": true` on the `/api/**` rewrite. That pins
> Firebase Hosting to whichever Cloud Run revision existed **when Hosting was
> last deployed** — so deploying the backend changes nothing for real users
> until you redeploy Hosting too.
>
> It fails silently. Both URLs return 200, both say `"status":"ok"`, and they
> diverge only on routes that did not exist in the pinned revision:
>
> ```
> direct to Cloud Run  /api/analytics/accuracy  ->  401  (route exists)
> via Firebase Hosting /api/analytics/accuracy  ->  404  (old revision)
> ```
>
> `/api/health` now reports the running revision, and the script compares what
> Cloud Run serves against what the CDN serves and warns when they differ.
>
> **Either always redeploy Hosting after the backend, or set `pinTag: false`**
> so the rewrite always follows the latest revision. Pinning is a legitimate
> choice — it guarantees a frontend only ever talks to the backend revision it
> was tested against — but it is a choice, and it has to be a deliberate one.

Settings are declarative: the script uses `--set-env-vars`, which replaces the
whole set, so what is deployed is exactly what is in the script. A merge would
let a variable somebody set by hand months ago survive invisibly.

### Frontend
```bash
cd proofaegis-frontend && npm run deploy
```

### Test a change without breaking the live site
```bash
cd proofaegis-frontend && npm run deploy:preview
```
Gives a temporary URL. Production is untouched.

### Undo a bad backend deploy
```bash
gcloud run revisions list --service $SERVICE_NAME --region $REGION
```
```bash
gcloud run services update-traffic $SERVICE_NAME --region $REGION \
  --to-revisions REVISION_NAME=100
```

---

## 18. Watching for problems

Live logs:
```bash
gcloud run services logs tail $SERVICE_NAME --region $REGION
```

Errors in the last hour:
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND severity>=ERROR' --freshness=1h --limit 50
```

Every time the code overruled the AI:
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND textPayload:"trust_override"' --limit 50
```

Every time Gemini was unreachable:
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND textPayload:"ai_call_failed"' --limit 50
```

---

## 19. Not getting a surprise bill

**Do this now, not after.**

```bash
gcloud billing budgets create \
  --billing-account=YOUR_BILLING_ACCOUNT_ID \
  --display-name="ProofAegis monthly" \
  --budget-amount=10USD \
  --threshold-rule=percent=50 \
  --threshold-rule=percent=90 \
  --threshold-rule=percent=100
```

Email at 50%, 90% and 100% of $10.

Three protections are already in place:

- `--max-instances 3` caps how much can run at once
- `--min-instances 0` means zero cost while idle
- AI outputs are cached, so re-opening a case costs nothing

Check current spend:
https://console.cloud.google.com/billing

---

## 20. When something breaks

| Symptom | Cause | Fix |
|---|---|---|
| Website loads, everything says "cannot reach API" | Rewrite misconfigured | Check `serviceId` and `region` in `firebase.json` match your service |
| `/api/health` says `"mock_mode":true` | Backend cannot see the database | Redeploy with `--service-account $SA` |
| Sign-in: "unauthorized domain" | Domain not allow-listed | Firebase Console → Authentication → Settings → Authorized domains |
| Sign-in silently does nothing | Wrong or missing Firebase config | Recheck `.env.production`, rebuild, redeploy |
| First request takes 5–10 seconds | Cold start (scale to zero) | Normal. Hit `/api/health` to warm it, or set `--min-instances 1` (costs money) |
| Upload fails with 401 | `AUTH_REQUIRED=true` and no valid token | Sign in. If testing with curl, send a real ID token |
| Uploads fail with a permissions error | Missing storage role | Re-run the `storage.objectAdmin` binding from §11 |
| Cross-case findings missing | Index not built | `gcloud firestore indexes composite list` — wait for `READY` |
| AI features say "model unavailable" | Key missing, or quota | `gcloud secrets versions access latest --secret=gemini-api-key`. Everything else keeps working |
| Deploy: "permission denied" | APIs not enabled or billing unlinked | Redo §5.5 and §6 |
| Deploy: "image not found" | Cloud Build failed | Read the build log link in the error |
| Exceptions list is empty | Database not seeded | Redo §13 |

### The two commands that answer most questions

```bash
gcloud run services describe $SERVICE_NAME --region $REGION
```
```bash
gcloud run services logs tail $SERVICE_NAME --region $REGION
```

---

## 21. Taking it all down

### Just stop the backend running (keeps everything else)
```bash
gcloud run services delete $SERVICE_NAME --region $REGION
```

### Remove the website
```bash
npx firebase hosting:disable --project $PROJECT_ID
```

### Delete everything, permanently
```bash
gcloud projects delete $PROJECT_ID
```

> This removes the database, the files, the users and the service. **There is
> no undo.** Google waits 30 days before it is irreversible.

---

## Quick reference

```bash
# Local
cd backend && python app.py
cd proofaegis-frontend && npm run dev

# Test
cd backend && python -m pytest -q
cd backend && python -m eval.run_eval --count 320 --json data/generated/eval_report.json

# Deploy
cd backend && gcloud run deploy $SERVICE_NAME --source . --region $REGION
cd proofaegis-frontend && npm run deploy

# Inspect
gcloud run services logs tail $SERVICE_NAME --region $REGION
gcloud run services describe $SERVICE_NAME --region $REGION
```

---

## See also

- [`GOOGLE_STACK.md`](GOOGLE_STACK.md) — every Google service, explained
- [`ARCHITECTURE_BACKEND.md`](ARCHITECTURE_BACKEND.md) — configuration reference
- [`USER_GUIDE.md`](USER_GUIDE.md) — using it once it runs
