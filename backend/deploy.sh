#!/usr/bin/env bash
#
# deploy.sh — deploy the ProofAegis API to Cloud Run.
#
#   ./deploy.sh                 deploy with the settings below
#   ./deploy.sh --dry-run       print every command, run none of them
#   ./deploy.sh --setup         also enable APIs and grant IAM (first run)
#   ./deploy.sh --skip-verify   don't poll /api/health afterwards
#
# WHY A SCRIPT AND NOT A COMMAND IN A README
#
# The deploy command carries eleven environment variables, a secret mount and a
# service account. Typed by hand it is wrong about a third of the time, and the
# failure is silent: a missing GOOGLE_GENAI_USE_VERTEXAI does not error, it
# quietly routes every AI call at the AI Studio billing wallet instead of the
# Cloud project, and the app degrades to its deterministic fallback while
# looking completely healthy.
#
# Everything here is idempotent. Running it twice is how you redeploy.
#
# WHAT THIS DELIBERATELY DOES NOT DO
#
#   * It does not seed Firestore. That writes 300+ documents and needs a
#     temporary key file; it is a separate, occasional act. See
#     scripts/seed_firestore.py and DEPLOYMENT_GUIDE.md §13.
#   * It does not deploy the frontend. That is `npm run deploy` in
#     proofaegis-frontend, and coupling them means you cannot ship a backend
#     fix without also shipping whatever is half-finished in the UI.
#   * It does not run the tests. Do that yourself, before you get here.
set -euo pipefail

# NOTE for Git Bash on Windows: do NOT set MSYS_NO_PATHCONV or
# MSYS2_ARG_CONV_EXCL here. The instinct is right — MSYS does rewrite arguments
# that look like POSIX paths — but gcloud ships a wrapper that already handles
# it, and setting either variable makes every gcloud call in this script return
# an empty string instead of a value. Measured on 2026-09-04: with neither set,
# arguments like "roles/aiplatform.user" and "bindings[].members" pass through
# correctly; with MSYS_NO_PATHCONV=1, `gcloud config get-value account` returns
# nothing and preflight fails with a misleading "not logged in".

# ---------------------------------------------------------------------------
# Configuration — override any of these from the environment
# ---------------------------------------------------------------------------
PROJECT_ID="${PROJECT_ID:-proofaegis}"
REGION="${REGION:-asia-south1}"
SERVICE_NAME="${SERVICE_NAME:-proofaegis-api}"
RUNTIME_SA="${RUNTIME_SA:-proofaegis-runtime@${PROJECT_ID}.iam.gserviceaccount.com}"

BUCKET="${BUCKET:-${PROJECT_ID}.firebasestorage.app}"
HOSTING_URL="${HOSTING_URL:-https://${PROJECT_ID}.web.app}"
WORKSPACE_ID="${WORKSPACE_ID:-demo-workspace}"

# Gemini reaches the model through VERTEX, not the AI Studio Developer API.
# That is a billing decision: Vertex bills the Cloud project, the Developer API
# bills a separate AI Studio prepay wallet. Getting this wrong is the failure
# described at the top of this file.
#
# LOCATION=global is not a lazy default. Model availability is per region, and
# on 2026-09-04 asia-south1 served gemini-3.5-flash but 404'd
# gemini-3.5-flash-lite, which would have silently dropped every document
# extraction onto the deterministic parser. `global` serves both.
VERTEX_LOCATION="${VERTEX_LOCATION:-global}"
GEMINI_MODEL="${GEMINI_MODEL:-gemini-3.5-flash-lite}"
GEMINI_REASONING_MODEL="${GEMINI_REASONING_MODEL:-gemini-3.5-flash}"

# Still mounted even though Vertex authenticates with the service account.
# Flipping GOOGLE_GENAI_USE_VERTEXAI=false is then a one-variable rollback to
# the Developer API rather than a redeploy.
GEMINI_SECRET="${GEMINI_SECRET:-gemini-api-key}"

CPU="${CPU:-1}"
MEMORY="${MEMORY:-1Gi}"
TIMEOUT="${TIMEOUT:-120}"
MIN_INSTANCES="${MIN_INSTANCES:-0}"
MAX_INSTANCES="${MAX_INSTANCES:-3}"

# ---------------------------------------------------------------------------
DRY_RUN=false; DO_SETUP=false; VERIFY=true
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)     DRY_RUN=true ;;
    --setup)       DO_SETUP=true ;;
    --skip-verify) VERIFY=false ;;
    -h|--help)     sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
  shift
done

bold() { printf '\033[1m%s\033[0m\n' "$*"; }
info() { printf '  %s\n' "$*"; }
fail() { printf '\033[31mFAIL\033[0m  %s\n' "$*" >&2; exit 1; }

run() {
  if $DRY_RUN; then printf '  \033[2m$ %s\033[0m\n' "$*"; else "$@"; fi
}

# ---------------------------------------------------------------------------
# 1. Preflight — every one of these has bitten a real deploy
# ---------------------------------------------------------------------------
bold "1. Preflight"

command -v gcloud >/dev/null 2>&1 || fail "gcloud not found. https://cloud.google.com/sdk/docs/install"

[[ -f "$(dirname "$0")/Dockerfile" ]] || fail "Dockerfile not found — run this from backend/"
cd "$(dirname "$0")"

# No pipe here on purpose. `gcloud ... | head -1` fails under `set -o pipefail`
# when gcloud writes more than head reads and gets SIGPIPE — which is most of
# the time, and it fails the whole script before printing anything useful.
ACTIVE_ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
[[ -n "$ACTIVE_ACCOUNT" && "$ACTIVE_ACCOUNT" != "(unset)" ]]   || fail "not logged in. Run: gcloud auth login"
info "account   : $ACTIVE_ACCOUNT"
info "project   : $PROJECT_ID"
info "region    : $REGION"
info "service   : $SERVICE_NAME"
info "runtime SA: $RUNTIME_SA"

gcloud projects describe "$PROJECT_ID" --format='value(projectId)' >/dev/null 2>&1 \
  || fail "cannot see project '$PROJECT_ID'. Wrong account, or wrong PROJECT_ID."

# A secret reaching the build staging bucket is not undone by deleting it
# later. Refuse rather than warn.
for pattern in ".env" "serviceAccountKey.json"; do
  if [[ -f "$pattern" ]] && ! grep -qE "^${pattern//./\\.}$|^\.env\.\*$|^\.env$" .gcloudignore 2>/dev/null; then
    fail "$pattern exists but is not excluded by .gcloudignore — it would be uploaded to Cloud Build"
  fi
done
info "secrets   : .env and key files are excluded by .gcloudignore"

# The accuracy panel reads these two files off disk at runtime. If they are not
# in the image, GET /api/analytics/accuracy returns 404 and the Analytics
# screen shows an empty panel.
for report in data/generated/eval_report.json data/generated/extraction_report.json; do
  if [[ -f "$report" ]]; then
    info "eval report: $report ($(wc -c < "$report" 2>/dev/null || echo 0) bytes)"
  else
    printf '\033[33m  WARN\033[0m      %s missing — the Analytics accuracy panel will be empty.\n' "$report"
    printf '            Generate it: python -m eval.run_eval --count 320 --json %s\n' "$report"
  fi
done

# ---------------------------------------------------------------------------
# 2. One-time setup — safe to re-run, slow enough to skip by default
# ---------------------------------------------------------------------------
if $DO_SETUP; then
  bold "2. Setup (APIs + IAM)"
  run gcloud services enable \
    run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
    firestore.googleapis.com storage.googleapis.com secretmanager.googleapis.com \
    aiplatform.googleapis.com firebase.googleapis.com identitytoolkit.googleapis.com \
    --project="$PROJECT_ID"

  if ! gcloud iam service-accounts describe "$RUNTIME_SA" --project="$PROJECT_ID" >/dev/null 2>&1; then
    info "creating runtime service account"
    run gcloud iam service-accounts create "${RUNTIME_SA%%@*}" \
      --display-name="ProofAegis API runtime" --project="$PROJECT_ID"
  fi

  # aiplatform.user is the one people miss: Cloud Run runs as RUNTIME_SA, not
  # as the Firebase Admin SDK account used locally, so granting it locally does
  # nothing for the deployed service. Missing it gives
  # "403 Permission 'aiplatform.endpoints.predict' denied".
  for role in roles/datastore.user roles/storage.objectAdmin \
              roles/secretmanager.secretAccessor roles/firebaseauth.admin \
              roles/aiplatform.user; do
    info "grant $role"
    run gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="serviceAccount:${RUNTIME_SA}" --role="$role" \
      --condition=None --quiet >/dev/null
  done
  info "IAM changes take ~60s to propagate; a 403 immediately after this is usually just that"
else
  bold "2. Setup — skipped (pass --setup on a new project)"
fi

# ---------------------------------------------------------------------------
# 3. Deploy
# ---------------------------------------------------------------------------
bold "3. Deploy"

# ^@^ switches gcloud's list delimiter from comma to @, so a value may itself
# contain commas. ALLOWED_ORIGINS is comma-separated when there is more than
# one origin, and the default delimiter would split it into broken pairs.
ENV_VARS="^@^"
ENV_VARS+="USE_MOCK_DATA=false@"
ENV_VARS+="AUTH_REQUIRED=true@"
ENV_VARS+="GOOGLE_CLOUD_PROJECT=${PROJECT_ID}@"
ENV_VARS+="FIREBASE_STORAGE_BUCKET=${BUCKET}@"
ENV_VARS+="STORAGE_BUCKET=${BUCKET}@"
ENV_VARS+="STORAGE_BACKEND=auto@"
ENV_VARS+="ALLOWED_ORIGINS=${HOSTING_URL}@"
ENV_VARS+="DEFAULT_WORKSPACE_ID=${WORKSPACE_ID}@"
ENV_VARS+="GOOGLE_GENAI_USE_VERTEXAI=true@"
ENV_VARS+="GOOGLE_CLOUD_LOCATION=${VERTEX_LOCATION}@"
ENV_VARS+="GEMINI_MODEL=${GEMINI_MODEL}@"
ENV_VARS+="GEMINI_REASONING_MODEL=${GEMINI_REASONING_MODEL}"

# --set-env-vars, not --update-env-vars: this replaces the whole set, so the
# deployed configuration is exactly what is in this file. A merge would let a
# variable somebody set by hand months ago survive invisibly.
SECRET_ARGS=()
if gcloud secrets describe "$GEMINI_SECRET" --project="$PROJECT_ID" >/dev/null 2>&1; then
  SECRET_ARGS=(--set-secrets "GEMINI_API_KEY=${GEMINI_SECRET}:latest")
  info "secret    : ${GEMINI_SECRET}:latest -> GEMINI_API_KEY"
else
  info "secret    : '${GEMINI_SECRET}' not found — deploying without it (Vertex uses the service account)"
fi

info "backend   : Vertex AI (${VERTEX_LOCATION}) — bills the Cloud project, not the AI Studio wallet"
info "models    : ${GEMINI_MODEL} | ${GEMINI_REASONING_MODEL}"
echo

run gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --service-account "$RUNTIME_SA" \
  --allow-unauthenticated \
  --min-instances "$MIN_INSTANCES" \
  --max-instances "$MAX_INSTANCES" \
  --cpu "$CPU" \
  --memory "$MEMORY" \
  --timeout "$TIMEOUT" \
  --set-env-vars "$ENV_VARS" \
  "${SECRET_ARGS[@]}" \
  --quiet

# --allow-unauthenticated is correct and is not a hole. Cloud Run's IAM layer
# is not the auth boundary here; Firebase ID tokens verified inside Flask are.
# A browser has no Google IAM identity, so requiring IAM would block every real
# user while changing nothing about who can read a case.

# ---------------------------------------------------------------------------
# 4. Verify
# ---------------------------------------------------------------------------
if $DRY_RUN; then
  bold "Dry run complete — nothing was deployed."
  exit 0
fi

SERVICE_URL="$(gcloud run services describe "$SERVICE_NAME" --project "$PROJECT_ID" \
  --region "$REGION" --format='value(status.url)')"
REVISION="$(gcloud run services describe "$SERVICE_NAME" --project "$PROJECT_ID" \
  --region "$REGION" --format='value(status.latestReadyRevisionName)')"

if $VERIFY; then
  bold "4. Verify"
  # min-instances=0 means the first request pays a cold start. Retry rather
  # than reporting a slow wake-up as a failed deploy.
  HEALTH=""
  for attempt in 1 2 3 4 5; do
    HEALTH="$(curl -fsS --max-time 30 "${SERVICE_URL}/api/health" 2>/dev/null || true)"
    [[ -n "$HEALTH" ]] && break
    info "cold start, retry ${attempt}/5..."
    sleep 5
  done

  [[ -n "$HEALTH" ]] || fail "/api/health did not respond. gcloud run services logs tail $SERVICE_NAME --region $REGION"
  info "health    : $HEALTH"

  case "$HEALTH" in
    *'"mock_mode":true'*)
      printf '\033[33m  WARN\033[0m      mock_mode is true — the service cannot see Firestore.\n'
      printf '            Check the runtime service account has roles/datastore.user.\n' ;;
    *'"status":"ok"'*)
      info "status    : ok" ;;
  esac

  # THE CHECK THAT MATTERS, and the one nothing else catches.
  #
  # firebase.json sets "pinTag": true on the /api/** rewrite, which pins
  # Firebase Hosting to whichever Cloud Run revision existed when HOSTING was
  # last deployed. Deploying the backend then changes nothing for real users,
  # and the failure is completely silent: both URLs answer 200, both report
  # "status":"ok", and they differ only on routes that did not exist in the
  # pinned revision, which 404 through the CDN while working perfectly when
  # called directly.
  #
  # Comparing the revision each one reports turns that into a visible warning.
  CDN_HEALTH="$(curl -fsS --max-time 30 "${HOSTING_URL}/api/health" 2>/dev/null || true)"
  if [[ -n "$CDN_HEALTH" ]]; then
    LIVE_REV="$(printf '%s' "$HEALTH"     | sed -n 's/.*"revision":"\([^"]*\)".*/\1/p')"
    CDN_REV="$( printf '%s' "$CDN_HEALTH" | sed -n 's/.*"revision":"\([^"]*\)".*/\1/p')"
    if [[ -z "$CDN_REV" ]]; then
      printf '\033[33m  WARN\033[0m      the CDN serves a revision predating the revision marker\n'
      printf '            in /api/health. Firebase Hosting is pinned to an old one.\n'
      printf '            Fix: cd ../proofaegis-frontend && npm run deploy\n'
    elif [[ "$CDN_REV" != "$LIVE_REV" ]]; then
      printf '\033[33m  WARN\033[0m      Hosting is pinned to an older revision.\n'
      printf '            cloud run : %s\n' "$LIVE_REV"
      printf '            via CDN   : %s\n' "$CDN_REV"
      printf '            Users get the OLD backend until Hosting is redeployed:\n'
      printf '            cd ../proofaegis-frontend && npm run deploy\n'
    else
      info "CDN       : serving $CDN_REV (matches)"
    fi
  fi
fi

echo
bold "Deployed"
info "revision  : $REVISION"
info "service   : $SERVICE_URL"
info "via CDN   : ${HOSTING_URL}/api/health"
echo
info "Not done by this script:"
info "  frontend   cd ../proofaegis-frontend && npm run deploy"
info "  seed data  python scripts/seed_firestore.py   (see DEPLOYMENT_GUIDE.md §13)"
info "  rollback   gcloud run services update-traffic $SERVICE_NAME --region $REGION --to-revisions REV=100"
