"""
Central configuration. Every other module reads settings from here — nothing
reaches into os.environ directly outside this file, so there's exactly one
place to check when a deploy has the wrong value.
"""
import os
from dotenv import load_dotenv

load_dotenv()


def _bool_env(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


class Config:
    # --- Google Cloud / Gemini ---
    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "proofaegis-hackathon")
    FIREBASE_STORAGE_BUCKET = os.environ.get("FIREBASE_STORAGE_BUCKET", "")
    GOOGLE_APPLICATION_CREDENTIALS = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    # JSON content of a Firebase/Google service-account key. This is useful
    # on generic hosts such as Render where mounting a credential file is
    # inconvenient. Keep it in the host's secret store; never commit it.
    FIREBASE_SERVICE_ACCOUNT_JSON = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "")

    # --- CORS (FR non-functional: restricted CORS, not "*") ---
    # Comma-separated allow-list. Keep production origins explicit; never use
    # a wildcard when Firebase ID tokens are accepted by the API.
    ALLOWED_ORIGINS = tuple(
        origin.strip().rstrip("/")
        for origin in os.environ.get(
            "ALLOWED_ORIGINS",
            os.environ.get("ALLOWED_ORIGIN", "http://localhost:5173,http://127.0.0.1:5173"),
        ).split(",")
        if origin.strip()
    )

    # --- Mock mode ---
    # True whenever explicitly set, OR when there's no plausible way to reach
    # Firestore/Gemini (no credentials configured). This is what makes "mock
    # fallback" a real, always-on safety net rather than a manual toggle you
    # can forget to flip before a demo.
    # A generic host such as Render supplies the service account as encrypted
    # JSON rather than a credential-file path. Cloud Run instead exposes
    # Application Default Credentials through its attached service identity;
    # K_SERVICE is set by Cloud Run for every running revision.
    HAS_GOOGLE_CREDENTIALS = bool(
        GOOGLE_APPLICATION_CREDENTIALS
        or FIREBASE_SERVICE_ACCOUNT_JSON
        or os.environ.get("K_SERVICE")
    )
    USE_MOCK_DATA = _bool_env("USE_MOCK_DATA", True) or not HAS_GOOGLE_CREDENTIALS

    # --- Firebase Auth ---
    # False by default so the existing demo/mock-mode flow keeps working with
    # zero Firebase project setup. Requests are still verified best-effort
    # whenever a token IS sent (see auth.py's require_auth) — this flag only
    # controls whether a MISSING/invalid token blocks the request with 401.
    # Flip to true once real users are expected to be signed in.
    AUTH_REQUIRED = _bool_env("AUTH_REQUIRED", False)

    # --- Model selection ---
    # The "-latest" aliases float onto whatever the newest model is, which in
    # practice means the busiest endpoint: gemini-flash-latest was measured at
    # 75s (and 503 UNAVAILABLE) for a 427-character extraction that a pinned
    # flash-lite answers identically in 1.4s. Extraction is a structured,
    # low-judgement task, so it gets the fast model; severity reasoning and
    # resolution drafting are language tasks and get the stronger one.
    #
    # PINNED, and pinned to a CURRENT generation. The 2.5 pair that sat here
    # returns 404 "no longer available to new users" on every call — and it
    # fails in a way that is easy to misread, because ListModels still lists
    # those names. Only generateContent rejects them. If you are changing
    # these, probe the model with a real generateContent call rather than
    # trusting a model list.
    GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
    GEMINI_REASONING_MODEL = os.environ.get("GEMINI_REASONING_MODEL", "gemini-3.5-flash")

    # --- Analytics engine ---
    # "firestore" aggregates in Python over a full collection read; that is
    # correct at a few hundred cases and is what the test suite runs.
    # "bigquery" pushes the same aggregations down as SQL — see
    # services/bigquery_executor.py for why the cross-case layer is the
    # reason this exists rather than the analytics screen.
    #
    # Defaults to firestore so a checkout with no GCP credentials still runs
    # every test and every route offline.
    ANALYTICS_ENGINE = os.environ.get("ANALYTICS_ENGINE", "firestore").strip().lower()
    BIGQUERY_DATASET = os.environ.get("BIGQUERY_DATASET", "proofaegis_analytics")
    BIGQUERY_TABLE = os.environ.get("BIGQUERY_TABLE", "cases")
    # asia-south1 like everything else, so an analytics query never crosses a
    # region boundary to read its own data.
    BIGQUERY_LOCATION = os.environ.get("BIGQUERY_LOCATION", "asia-south1")

    # --- OCR for scanned documents ---
    # Needs the Tesseract binary on PATH (and TESSDATA_PREFIX pointing at its
    # language data). Off by default: a server without Tesseract should say so
    # rather than fail every scanned upload with a confusing error.
    OCR_ENABLED = _bool_env("OCR_ENABLED", False)
    OCR_DPI = int(os.environ.get("OCR_DPI", "300"))

    # --- Email intake (services/email_intake.py) ---
    # Off unless explicitly enabled AND fully configured. The allow-list is
    # not optional in spirit: an empty one processes nothing, because an inbox
    # that accepts documents from anyone is an open door into an approval
    # queue.
    EMAIL_INTAKE_ENABLED = _bool_env("EMAIL_INTAKE_ENABLED", False)
    EMAIL_INTAKE_HOST = os.environ.get("EMAIL_INTAKE_HOST", "")
    EMAIL_INTAKE_PORT = int(os.environ.get("EMAIL_INTAKE_PORT", "993"))
    EMAIL_INTAKE_USER = os.environ.get("EMAIL_INTAKE_USER", "")
    EMAIL_INTAKE_PASSWORD = os.environ.get("EMAIL_INTAKE_PASSWORD", "")
    EMAIL_INTAKE_FOLDER = os.environ.get("EMAIL_INTAKE_FOLDER", "INBOX")
    EMAIL_INTAKE_BATCH_SIZE = int(os.environ.get("EMAIL_INTAKE_BATCH_SIZE", "20"))
    EMAIL_INTAKE_ALLOWED_SENDERS = tuple(
        entry.strip().lower()
        for entry in os.environ.get("EMAIL_INTAKE_ALLOWED_SENDERS", "").split(",")
        if entry.strip()
    )

    # --- AI resilience (FR-014) ---
    AI_CALL_TIMEOUT_SECONDS = float(os.environ.get("AI_CALL_TIMEOUT_SECONDS", "20"))
    AI_CALL_MAX_RETRIES = int(os.environ.get("AI_CALL_MAX_RETRIES", "1"))

    # --- Guardrail demonstration ---
    # Corrupts the reasoning layer's STATED financial impact on the cases
    # listed in mock_data/mock_extractions.py:FAULT_INJECTED_CASES, so the
    # deterministic override can be watched firing instead of described.
    #
    # On by default, and that is a deliberate choice about which failure is
    # worse. With it off, the guardrail only ever fires if a live model
    # happens to get the arithmetic wrong during the two minutes someone is
    # watching — which is to say it is never seen, and an unobservable safety
    # net is worth very little. With it on, the mechanism is demonstrable at
    # any moment.
    #
    # The honesty cost is paid in full elsewhere: every check produced this way
    # is stamped kind="fault_injection" by services/trust_ledger.py, excluded
    # from every statistic describing what a model actually did, and labelled
    # in the UI as an injected fault rather than presented as model output. It
    # changes nothing about how the override behaves — the same code path runs
    # on a real disagreement.
    DEMO_FAULT_INJECTION = _bool_env("DEMO_FAULT_INJECTION", True)

    # --- Tolerance fallback (real source of truth is Firestore settings/tolerance_rules) ---
    DEFAULT_PRICE_TOLERANCE_PERCENT = float(os.environ.get("DEFAULT_PRICE_TOLERANCE_PERCENT", "5"))
    DEFAULT_QUANTITY_TOLERANCE_PERCENT = float(os.environ.get("DEFAULT_QUANTITY_TOLERANCE_PERCENT", "2"))

    # --- Upload limits (FR-002) ---
    # There is deliberately NO cap on how many documents a case may hold: a
    # real AP investigation accumulates evidence over days (a corrected
    # invoice, a late goods receipt, a second PO revision). The limits below
    # are per-file only.
    MAX_UPLOAD_SIZE_MB = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "15"))
    MAX_FILES_PER_REQUEST = int(os.environ.get("MAX_FILES_PER_REQUEST", "20"))
    ALLOWED_UPLOAD_EXTENSIONS = {"pdf"}

    # --- Cloud Storage (P0 ingestion) ---
    # Bucket for uploaded case documents. Accepts either "gs://name" or a bare
    # bucket name; normalized below. Falls back to FIREBASE_STORAGE_BUCKET so
    # a single Firebase project needs only one value configured.
    _RAW_BUCKET = os.environ.get("STORAGE_BUCKET", "") or FIREBASE_STORAGE_BUCKET
    STORAGE_BUCKET = _RAW_BUCKET.replace("gs://", "").strip("/")
    # Where uploads go when no bucket/credentials are available: an on-disk
    # mirror of the exact same object paths, so local development and the
    # test suite exercise the real ingestion code end to end with zero cloud
    # calls and zero cost.
    LOCAL_STORAGE_DIR = os.environ.get(
        "LOCAL_STORAGE_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".local_storage")
    )
    SIGNED_URL_TTL_MINUTES = int(os.environ.get("SIGNED_URL_TTL_MINUTES", "15"))
    # "auto" (default) uses GCS when a bucket and credentials are both
    # present, otherwise local. "local" forces the on-disk backend — which is
    # what the test suite sets, so a developer machine holding real
    # credentials can never have a test run reach into a live bucket.
    STORAGE_BACKEND = os.environ.get("STORAGE_BACKEND", "auto").strip().lower()

    # --- Deployment identity ---
    # Cloud Run sets K_REVISION on every running revision. Exposing it through
    # /api/health is what lets a deploy tell whether Firebase Hosting's rewrite
    # is still pinned to an OLDER revision — a mismatch that is otherwise
    # completely silent, because both endpoints answer 200 and only differ on
    # routes that did not exist yet.
    REVISION = os.environ.get("K_REVISION", "")

    # --- Workspace (P2 scaffolding, enforced from P0 so storage paths are
    # right from the first byte written rather than retrofitted later) ---
    DEFAULT_WORKSPACE_ID = os.environ.get("DEFAULT_WORKSPACE_ID", "demo-workspace")


config = Config()
