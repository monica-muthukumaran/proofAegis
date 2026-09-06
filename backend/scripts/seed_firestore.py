"""
scripts/seed_firestore.py — Document 2 §10.

Writes the exact same case data used by the in-memory mock datastore (single
source of truth: mock_data/seed_cases.json) into a real Firestore project,
so switching USE_MOCK_DATA off doesn't change what the demo shows.

Usage:
    export GOOGLE_APPLICATION_CREDENTIALS=serviceAccountKey.json
    python scripts/seed_firestore.py
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

import firebase_admin
from firebase_admin import credentials, firestore
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SEED_PATH = os.path.join(os.path.dirname(__file__), "..", "mock_data", "seed_cases.json")
PORTFOLIO_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "generated", "portfolio.json")

# Firestore caps a batch at 500 writes.
BATCH_SIZE = 400
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# The API loads this automatically through config.py, but this standalone
# script does not import config. Load the same backend/.env file explicitly.
load_dotenv(os.path.join(BACKEND_DIR, ".env"))


def initialize_firebase():
    if firebase_admin._apps:
        return
    service_account_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
    service_account_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

    if service_account_json:
        try:
            service_account = json.loads(service_account_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON in backend/.env is not valid JSON.") from exc
        cred = credentials.Certificate(service_account)
    elif service_account_path:
        if not os.path.isfile(service_account_path):
            raise RuntimeError(
                "GOOGLE_APPLICATION_CREDENTIALS points to a file that does not exist: "
                f"{service_account_path}"
            )
        cred = credentials.Certificate(service_account_path)
    else:
        raise RuntimeError(
            "No Firebase credentials found. Set GOOGLE_APPLICATION_CREDENTIALS to the absolute path "
            "of your downloaded service-account JSON file, or set FIREBASE_SERVICE_ACCOUNT_JSON in backend/.env."
        )
    firebase_admin.initialize_app(cred)


def seed_portfolio(db) -> int:
    """Writes the bulk synthetic portfolio from scripts/generate_synthetic_data.py.

    Without this, a live deployment has the three hero cases and nothing else,
    so every analytics screen is empty — the exception RATE has no denominator
    and the vendor risk chart has no population. Batched because writing 400+
    documents one at a time is slow and needlessly expensive.
    """
    if not os.path.isfile(PORTFOLIO_PATH):
        print(f"\nNo portfolio found at {PORTFOLIO_PATH}")
        print("Generate one first:  python scripts/generate_synthetic_data.py")
        return 0

    with open(PORTFOLIO_PATH, encoding="utf-8") as f:
        cases = json.load(f).get("cases", [])

    written = 0
    for start in range(0, len(cases), BATCH_SIZE):
        chunk = cases[start:start + BATCH_SIZE]
        batch = db.batch()
        for case in chunk:
            ref = db.collection("invoice_exceptions").document(case["exception_id"])
            batch.set(ref, case)
        batch.commit()
        written += len(chunk)
        print(f"  Seeded {written}/{len(cases)} portfolio records")
    return written


def main():
    parser = argparse.ArgumentParser(description="Seed Firestore for ProofAegis.")
    parser.add_argument(
        "--portfolio", action="store_true",
        help="Also seed the bulk synthetic portfolio (needed for the analytics screens).",
    )
    parser.add_argument(
        "--portfolio-only", action="store_true",
        help="Seed ONLY the portfolio, leaving the three hero cases untouched.",
    )
    args = parser.parse_args()

    initialize_firebase()
    db = firestore.client()
    now = datetime.now(timezone.utc)

    if args.portfolio_only:
        count = seed_portfolio(db)
        print(f"\nSeeding complete: {count} portfolio records.")
        return

    with open(SEED_PATH) as f:
        seed = json.load(f)

    db.collection("settings").document("tolerance_rules").set(seed["tolerance_rules"])
    print("Seeded settings/tolerance_rules:", seed["tolerance_rules"])

    for case in seed["cases"]:
        record = {k: v for k, v in case.items() if k != "documents"}
        record["created_at"] = now.isoformat()
        record["updated_at"] = now.isoformat()
        # match_score / risk_level are placeholders here — matching_service.py
        # computes them for real at request time; this field is informational only.
        db.collection("invoice_exceptions").document(case["exception_id"]).set(record)
        print(f"Seeded invoice_exceptions/{case['exception_id']}")

        for doc in case["documents"]:
            doc_record = dict(doc)
            doc_record["exception_id"] = case["exception_id"]
            db.collection("documents").document(doc["document_id"]).set(doc_record)
        print(f"  + {len(case['documents'])} document records")

    total = len(seed["cases"])
    if args.portfolio:
        total += seed_portfolio(db)

    print(f"\nSeeding complete: {total} cases.")
    if not args.portfolio:
        print("The analytics screens need volume — rerun with --portfolio to add the")
        print("synthetic portfolio, or they will be empty in this environment.")


if __name__ == "__main__":
    main()
