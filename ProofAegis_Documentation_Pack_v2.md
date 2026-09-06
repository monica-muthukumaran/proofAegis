# ProofAegis Documentation Pack — v2 (Strengthened for Build)

> ## ⚠️ Historical document — kept for its requirement IDs
>
> **This is the original planning pack the project was built from, not a
> description of what the code does today.** It is retained because roughly a
> dozen source files carry `FR-004`, `FR-006`, `FR-011` and similar comments
> that point at the requirement numbers below — deleting it would orphan every
> one of those references.
>
> It predates the cross-case investigation layer, the trust ledger, the fourth
> ADK agent, the eval harness and the current theme. Where it disagrees with
> the documents below, **the documents below are right.**
>
> | For | Read |
> |---|---|
> | What the backend actually does | [`ARCHITECTURE_BACKEND.md`](ARCHITECTURE_BACKEND.md) |
> | What the frontend actually does | [`ARCHITECTURE_FRONTEND.md`](ARCHITECTURE_FRONTEND.md) |
> | Google services, commands, links | [`GOOGLE_STACK.md`](GOOGLE_STACK.md) |
> | Deploying it | [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) |
> | Using it | [`USER_GUIDE.md`](USER_GUIDE.md) |
> | The argument for it | [`PITCH.md`](PITCH.md) |
> | Recording the demo | [`DEMO_GUIDE.md`](DEMO_GUIDE.md) |
> | Current limitations | [`README.md`](README.md) |

---


This is your original 4-document pack with the inconsistencies and scope risks fixed. Structure and most wording are preserved so it's a drop-in replacement — only the parts below actually needed to change.

## What changed and why

1. **Cut the "Control and Contract Agent."** No contract document exists anywhere in your 3 demo cases — tolerance is a fixed 5%/2%, not something that needs an LLM to interpret. This was a whole AI agent and a document type with no seeded data behind it. It's gone; tolerance is now a small config object.
2. **Moved the Evidence Graph Builder out of "AI components."** It assembles a graph from findings you've already computed deterministically — no LLM call needed, and you don't want the thing that's supposed to *prove* your evidence chain to be able to hallucinate it.
3. **Fixed FR-006 vs. the actual code.** `compare_quantity` never used the stated 2% tolerance — it just checked `invoice_quantity > received_quantity`. Now it does.
4. **Added the match-score formula.** It was a bare number (72, 78, 60) with no defined calculation anywhere in the pack.
5. **Made Case B's ₹50,400 traceable.** The Firestore seed has `"financial_impact": 50400` but Document 1 never states the ₹630 implied unit price it comes from. Added.
6. **Clarified FR-011.** Which of the 10 statuses are system-set vs. user-set was never specified — a real ambiguity for whoever builds the status selector.
7. **Fixed the architecture diagram.** It showed the PDF parser hanging off the Gemini API box, implying parsing happens *after* the Gemini call. It has to happen before — Gemini needs the extracted text as input.
8. **Dropped server-side filtering.** FR-001 implied Firestore compound queries for search/filter/sort over a 3-record demo dataset. That's a category of index errors you don't need to risk — fetch once, filter client-side.
9. **Gave the "AI failure → mock fallback" a real mechanism.** Previously just prose ("add retry, add mock fallback"). Now a concrete wrapper function every AI call site uses.
10. **Recomputed the 24-day plan against reality.** Folded two non-must-have screens (Documents, Vendors) into tabs instead of separate pages, saving ~1.5 days, and moved your first live Cloud Run + Firebase deploy from Day 22 to right after Day 13 — so deployment problems surface with over a week of runway instead of two days.

Everything else — the evidence graph, source citations, deterministic matching, mock mode, the "human controls every action" boundary, the scope-cutting discipline — was already right. Keep it exactly as it was.

---

# Document 1: Functional Requirements Document

ProofAegis — Invoice Exception Resolution Platform

## 1. Executive summary

ProofAegis helps Accounts Payable and Procurement teams investigate invoices that cannot be automatically approved.

When an invoice is blocked or rejected, ProofAegis:

- Ingests the invoice, purchase order, goods receipt (if one exists), and rejection notice.
- Extracts structured fields from each document.
- Performs two-way and three-way matching.
- Detects price, quantity, missing-document, vendor, tax, and duplicate exceptions.
- Builds an evidence graph connecting source documents, extracted values, business rules, and findings.
- Explains the discrepancy in plain language.
- Calculates the financial impact using deterministic code.
- Recommends the responsible team.
- Generates a source-cited resolution draft.
- Records the human-reviewed outcome in an audit trail.

### Product tagline

From invoice rejection to resolution — with proof, not guesswork.

### Product boundary

ProofAegis is an exception-resolution assistant, not:

- An ERP replacement.
- A payment-release system.
- A bank-account verification system.
- A legal or tax-advisory system.
- An autonomous fraud detector.
- A complete supplier lifecycle-management platform.

The system may recommend actions and generate drafts, but a human must control approval, payment hold, payment release, rejection, and vendor communication.

## 2. Problem statement

*(unchanged from original — this was already tight)*

Enterprise invoices often fail validation because information is spread across multiple documents and teams. Typical problems: invoice price differs from the PO; invoice quantity differs from the goods receipt; the PO or receipt is missing; vendor information doesn't match the approved record; tax or totals are inconsistent; an invoice may already have been submitted. No single person can quickly explain the exception, resolution discussions are scattered across email and systems, and audit evidence is hard to assemble. ProofAegis solves the investigation-and-resolution gap, not the initial rejection.

## 3. Target users

*(unchanged — Primary: AP analysts, Procurement, Finance controllers, Receiving/operations. Secondary: vendor managers, shared-service finance, internal audit, business-unit approvers.)*

### MVP persona

An AP analyst handling a rejected vendor invoice and needing to resolve it quickly with evidence.

## 4. Core workflow

### Hero workflow: price variance

1. User opens the Exception Queue.
2. User selects a blocked invoice.
3. User uploads or opens the vendor invoice, purchase order, and rejection notice. **The goods receipt is optional at this step** — its absence is itself the signal for a missing-goods-receipt exception (Case C), not an upload error.
4. ProofAegis classifies documents.
5. The system extracts key values.
6. The deterministic matching engine compares vendor, PO number, line items, quantity, unit price, tax, and total.
7. The system applies the configured tolerance (from `settings/tolerance_rules` in Firestore — see FR-006).
8. It detects a price variance.
9. It calculates the financial impact and a match score.
10. The evidence graph links PO price, invoice price, tolerance rule, variance, and rejection notice.
11. The system recommends Procurement as owner.
12. The Resolution Copilot drafts a vendor correction request.
13. The user reviews the evidence and draft.
14. The user marks the case as Awaiting vendor / Awaiting procurement / Approved with exception / Resolved.
15. ProofAegis saves the audit event.

## 5. Supported exception types

### MVP-supported

Price variance · Quantity variance · Missing goods receipt · Missing purchase order · Vendor mismatch · Tax or total mismatch · Potential duplicate invoice

### MVP priority

Implement first: **Price variance, Quantity variance, Missing goods receipt.** The other four are demo-scoped via seeded data or a simple rule after the hero flow works — do not build dedicated pipelines for them before September 5.

## 6. Functional requirements

**FR-001: Exception queue** — displays Exception ID, Invoice number, Vendor name, PO number, Exception type, Invoice amount, Status, Risk level, Match score, Assigned team, Created/Updated date. Users can search, filter (status/type/risk), sort (amount/date), and open an exception.

> **Implementation note:** with a demo dataset of 3–10 exceptions, do this entirely client-side against the single `GET /api/exceptions` response. Do not build Firestore compound-query filtering for this — it adds index-configuration risk for zero benefit at this data volume.

**FR-002: Document upload** — accepts PDF files for vendor invoice, purchase order, goods receipt, and rejection notice. Validates file type, enforces a size limit, shows upload/processing/failure/retry states. Stores files in Cloud Storage or uses seeded mock data.

> Service confirmation and vendor record are supported by the schema for future extension but are **not required** for the 3 MVP demo cases — don't spend build time generating synthetic PDFs for document types nothing in your pipeline actually exercises.

**FR-003: Document classification** — as before (Document ID, file name, type, processing status, confidence, source reference).

**FR-004: Field extraction** — as before (invoice/PO/receipt fields, unchanged).

**FR-005: Matching** — compares vendor, PO number, line items, quantity (vs. receipt and vs. PO), unit price, tax, total.

> **Match score formula (new — was previously undefined):**
> `match_score = round(100 × matched_count / evaluable_count)`
> where `evaluable_count` is the number of FR-005 comparisons that had both source values available (a comparison isn't penalized for a document that's legitimately missing — that's handled as its own exception type, not a low score), and `matched_count` is the number of those rated `matched` or `within_tolerance`.
> The seeded match scores (72, 78, 60) are placeholders — once `matching_service.py` computes this for real, reseed with the computed values instead of hand-picked ones.

**FR-006: Tolerance evaluation** — price tolerance 5%, quantity tolerance 2%. **Tolerance values are stored in Firestore (`settings/tolerance_rules`) so they're genuinely visible/configurable, not hardcoded** — this also gives the otherwise-vague Settings screen a real, minimal purpose: display these two numbers read-only.

```
absolute_variance = actual_value - expected_value
percentage_variance = absolute_variance / expected_value * 100
```

Classifications: Matched · Within tolerance · Outside tolerance · Missing · Unable to verify · Requires human review.

**FR-007: Exception classification** — unchanged (type, severity, description, source docs/fields, financial impact, recommended owner/action, confidence, human-review requirement).

**FR-008: Evidence graph** — unchanged node/relationship types.

**FR-009: Inline citations** — unchanged.

**FR-010: Resolution Copilot** — unchanged.

**FR-011: Status workflow**

> **Clarified (was ambiguous):**
> - **System-set** (pipeline sets these automatically; not user-editable): `received` → `processing` → `exception_detected` → `assigned`.
> - **User-set** (selectable manually once an exception exists): `awaiting_procurement`, `awaiting_receiving`, `awaiting_vendor`, `approved_with_exception`, `resolved`, `closed`.
> - Every transition — system or user — writes an audit event (FR-012).

**FR-012: Audit trail** — unchanged.

**FR-013: Mock mode** — unchanged (`VITE_USE_MOCK_DATA=true`).

**FR-014: Error handling** — unchanged.

## 7. Non-functional requirements

*(unchanged — performance, security, accessibility, reliability targets were all reasonable as written)*

## 8. MVP screens

- Dashboard · Exception Queue · Exception Details · Three-Way Match Workspace · Evidence Graph · Documents · Vendors · Resolution Drafts · Audit Log · Settings

### Must-have screens

For the September 5 submission:

- Dashboard
- Exception Queue
- Exception Details
- Evidence Graph
- Resolution Assistant

**Documents and Vendors are not separate screens for the MVP — fold them into tabs/sections within Exception Details.** Audit Log can be a simple timeline inside Exception Details rather than its own route. Settings is a one-screen read-only display of the two tolerance values.

## 9. MVP data cases

**Case A: Price variance**
Vendor: Chennai Industrial Supplies Pvt. Ltd. · PO: PO-2026-00421 · Invoice: INV-2026-1187
PO unit price: ₹2,400 · Invoice unit price: ₹2,650 · Tolerance: 5% · Actual variance: 10.42% · Quantity: 100
Financial impact: ₹25,000 (= ₹250 variance/unit × 100 units) · Owner: Procurement · Status: exception_detected

**Case B: Quantity variance**
Vendor: Southern Office Systems · PO: PO-2026-00516 · Invoice: INV-2026-2204
PO quantity: 500 · Received quantity: 420 · Invoiced quantity: 500 · Unreceived quantity: 80
**Implied unit price: ₹630** (₹315,000 invoice amount ÷ 500 units) · **Financial impact: ₹50,400** (= 80 unreceived units × ₹630)
Quantity variance vs. received: (500−420)/420 = 19.05%, outside the 2% tolerance → `outside_tolerance`
Owner: Receiving · Status: awaiting_receiving

**Case C: Missing goods receipt**
Vendor: BlueWave IT Services · PO: PO-2026-00602 · Invoice: INV-2026-3310
PO exists: Yes · Invoice exists: Yes · Goods receipt: Missing
**Financial impact: ₹180,000 (full invoice amount at risk pending confirmation — not a computed variance, the whole amount is blocked until receipt/service confirmation exists).** This is a different meaning of "financial impact" than Cases A/B — worth saying explicitly in the demo narration so a judge doesn't assume it's another price/quantity gap.
Owner: Requesting business unit · Status: awaiting_receiving

## 10. Success criteria

*(unchanged)*

## 11. Known limitations

*(unchanged — disclose in README and presentation)*

---

# Document 2: Complete Technical Setup Guide

ProofAegis — From Setup to Deployment

## 1–2. Prerequisites and project setup

*(unchanged — Node 18+, Python 3.10+, Git, gcloud CLI, Firebase CLI; `proofaegis-hackathon` project)*

## 3. Enable APIs

```
gcloud services enable \
  firestore.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  storage.googleapis.com \
  secretmanager.googleapis.com \
  logging.googleapis.com
```

Enable Vertex AI only if you actually use it. If you're calling the Gemini API through Google AI Studio (the `google-generativeai` SDK below), you don't need `aiplatform.googleapis.com` at all — skip it, one less thing to configure and bill for.

## 4. Billing and budget control

*(unchanged — set budget alerts at 25/50/75/90%, use mock mode during frontend dev, delete unused Cloud Run revisions, no real documents)*

## 5–6. Repository setup and environment variables

Same structure as before. `.env.example`:

```
GEMINI_API_KEY=replace-with-backend-secret
GOOGLE_CLOUD_PROJECT=proofaegis-hackathon
FIREBASE_STORAGE_BUCKET=replace-with-your-bucket
ALLOWED_ORIGIN=http://localhost:5173
VITE_API_BASE_URL=http://localhost:8080
VITE_USE_MOCK_DATA=true
```

Never commit `.env`.

## 7. Firestore setup

Collections (one addition — `settings`):

```
invoice_exceptions
documents
vendors
resolution_drafts
audit_events
settings          ← new: single doc "tolerance_rules"
```

`settings/tolerance_rules`:
```json
{
  "price_variance_percent": 5,
  "quantity_variance_percent": 2
}
```

This is what FR-006 and the Settings screen both read from — one source of truth instead of a number hardcoded in three places.

## 8–9. Storage setup and synthetic PDF structure

*(unchanged — only build PDFs for the 4 document types your 3 cases actually use: purchase order, vendor invoice, goods receipt note, rejection notice. Skip service-confirmation and vendor-record PDFs entirely for the MVP.)*

```
data/invoice_exceptions/
├── price_variance_001/
│   ├── purchase_order_001.pdf
│   ├── vendor_invoice_001.pdf
│   ├── goods_receipt_note_001.pdf
│   └── rejection_notice_001.pdf
├── quantity_variance_001/
│   ├── purchase_order_002.pdf
│   ├── vendor_invoice_002.pdf
│   ├── goods_receipt_note_002.pdf
│   └── rejection_notice_002.pdf
└── missing_receipt_001/
    ├── purchase_order_003.pdf
    ├── vendor_invoice_003.pdf
    └── rejection_notice_003.pdf   (no goods receipt — that's the point of this case)
```

Every PDF: `Synthetic demo data — not for financial processing.`

## 10. Firestore seeding

`scripts/seed_firestore.py` — same three records as before, plus the tolerance config doc. Key fix: **Case B now carries the implied unit price so the financial-impact number is traceable**, and a comment flags the match-score placeholders.

```python
import os
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore


def initialize_firebase():
    if firebase_admin._apps:
        return
    service_account_path = os.environ.get(
        "GOOGLE_APPLICATION_CREDENTIALS", "serviceAccountKey.json"
    )
    cred = credentials.Certificate(service_account_path)
    firebase_admin.initialize_app(cred)


def main():
    initialize_firebase()
    db = firestore.client()
    now = datetime.now(timezone.utc)

    db.collection("settings").document("tolerance_rules").set({
        "price_variance_percent": 5,
        "quantity_variance_percent": 2,
    })

    records = [
        {
            "exception_id": "EXC-2026-0001",
            "invoice_id": "INV-2026-1187",
            "vendor_id": "VEN-0042",
            "vendor_name": "Chennai Industrial Supplies Pvt. Ltd.",
            "purchase_order_id": "PO-2026-00421",
            "business_unit": "Operations",
            "currency": "INR",
            "invoice_amount": 265000,
            "po_amount": 240000,
            "status": "exception_detected",
            "exception_type": "price_variance",
            "risk_level": "high",
            "match_score": 72,  # placeholder — recompute once matching_service.py is live
            "tolerance_percentage": 5,
            "actual_variance_percentage": 10.42,
            "financial_impact": 25000,
            "assigned_team": "Procurement",
            "documents": [
                {"type": "purchase_order", "file_name": "purchase_order_001.pdf",
                 "storage_path": "invoice-exceptions/EXC-2026-0001/purchase_order_001.pdf"},
                {"type": "vendor_invoice", "file_name": "vendor_invoice_001.pdf",
                 "storage_path": "invoice-exceptions/EXC-2026-0001/vendor_invoice_001.pdf"},
                {"type": "goods_receipt", "file_name": "goods_receipt_note_001.pdf",
                 "storage_path": "invoice-exceptions/EXC-2026-0001/goods_receipt_note_001.pdf"},
            ],
            "findings": [{
                "finding_id": "FIND-001",
                "type": "price_variance",
                "description": "Invoice unit price exceeds the purchase-order unit price.",
                "po_unit_price": 2400,
                "invoice_unit_price": 2650,
                "variance_per_unit": 250,
                "quantity": 100,
                "financial_impact": 25000,
                "source_documents": [
                    {"file": "purchase_order_001.pdf", "page": 1, "label": "Line item 2", "value": "₹2,400 per unit"},
                    {"file": "vendor_invoice_001.pdf", "page": 1, "label": "Line item 2", "value": "₹2,650 per unit"},
                ],
                "confidence": 0.98,
            }],
            "recommended_action": "Request a vendor credit note or procurement approval.",
            "created_at": now, "updated_at": now,
        },
        {
            "exception_id": "EXC-2026-0002",
            "invoice_id": "INV-2026-2204",
            "vendor_id": "VEN-0081",
            "vendor_name": "Southern Office Systems",
            "purchase_order_id": "PO-2026-00516",
            "business_unit": "Administration",
            "currency": "INR",
            "invoice_amount": 315000,
            "po_amount": 315000,
            "status": "awaiting_receiving",
            "exception_type": "quantity_variance",
            "risk_level": "medium",
            "match_score": 78,  # placeholder
            "po_quantity": 500,
            "received_quantity": 420,
            "invoiced_quantity": 500,
            "implied_unit_price": 630,
            "financial_impact": 50400,  # 80 unreceived units × ₹630
            "assigned_team": "Receiving",
            "documents": [
                {"type": "purchase_order", "file_name": "purchase_order_002.pdf",
                 "storage_path": "invoice-exceptions/EXC-2026-0002/purchase_order_002.pdf"},
                {"type": "vendor_invoice", "file_name": "vendor_invoice_002.pdf",
                 "storage_path": "invoice-exceptions/EXC-2026-0002/vendor_invoice_002.pdf"},
                {"type": "goods_receipt", "file_name": "goods_receipt_note_002.pdf",
                 "storage_path": "invoice-exceptions/EXC-2026-0002/goods_receipt_note_002.pdf"},
            ],
            "findings": [{
                "finding_id": "FIND-002",
                "type": "quantity_variance",
                "description": "Invoice quantity exceeds the quantity recorded as received.",
                "po_quantity": 500, "received_quantity": 420, "invoice_quantity": 500,
                "unreceived_quantity": 80,
                "variance_percentage": 19.05,
                "confidence": 0.97,
            }],
            "recommended_action": "Request receiving confirmation or a corrected invoice.",
            "created_at": now, "updated_at": now,
        },
        {
            "exception_id": "EXC-2026-0003",
            "invoice_id": "INV-2026-3310",
            "vendor_id": "VEN-0104",
            "vendor_name": "BlueWave IT Services",
            "purchase_order_id": "PO-2026-00602",
            "business_unit": "Technology",
            "currency": "INR",
            "invoice_amount": 180000,
            "po_amount": 180000,
            "status": "awaiting_receiving",
            "exception_type": "missing_goods_receipt",
            "risk_level": "medium",
            "match_score": 60,  # placeholder
            "financial_impact": 180000,  # full invoice amount at risk, not a computed variance
            "assigned_team": "Technology Operations",
            "documents": [
                {"type": "purchase_order", "file_name": "purchase_order_003.pdf",
                 "storage_path": "invoice-exceptions/EXC-2026-0003/purchase_order_003.pdf"},
                {"type": "vendor_invoice", "file_name": "vendor_invoice_003.pdf",
                 "storage_path": "invoice-exceptions/EXC-2026-0003/vendor_invoice_003.pdf"},
            ],
            "findings": [{
                "finding_id": "FIND-003",
                "type": "missing_goods_receipt",
                "description": "No goods receipt or service confirmation was found for the invoice.",
                "source_documents": [
                    {"file": "vendor_invoice_003.pdf", "page": 1, "label": "PO reference", "value": "PO-2026-00602"}
                ],
                "confidence": 0.95,
            }],
            "recommended_action": "Request service confirmation from the business owner.",
            "created_at": now, "updated_at": now,
        },
    ]

    for record in records:
        db.collection("invoice_exceptions").document(record["exception_id"]).set(record)
        print(f"Seeded {record['exception_id']}")


if __name__ == "__main__":
    main()
```

## 11. Frontend setup

```
cd frontend
npm create vite@latest . -- --template react
npm install
npm install react-router-dom reactflow firebase lucide-react recharts
npm install clsx tailwind-merge
```

Routes (trimmed to match §8's must-have screens):

```
/
/exceptions
/exceptions/:exceptionId    (tabs: Overview · Match · Evidence Graph · Resolution · Documents · Audit)
/settings
```

`Documents` and `Vendors` are tabs inside `/exceptions/:exceptionId`, not top-level routes — one less set of pages to build, route, and style.

`frontend/.env.local`:
```
VITE_API_BASE_URL=http://localhost:8080
VITE_USE_MOCK_DATA=true
```

## 12–13. Backend setup and architecture

`backend/requirements.txt` — unchanged:
```
Flask==3.1.0
flask-cors==5.0.0
gunicorn==23.0.0
firebase-admin==6.6.0
google-generativeai==0.8.3
python-dotenv==1.0.1
pydantic==2.10.6
PyMuPDF==1.25.3
```

**Backend module layout (revised — one fewer agent, clearer AI/deterministic split):**

```
backend/
├── main.py
├── agents/
│   ├── document_agent.py       # Gemini: classify + extract fields
│   ├── exception_agent.py      # Gemini: severity, description, owner, action, confidence
│   └── resolution_agent.py     # Gemini: drafts resolution text
├── services/
│   ├── firestore_service.py
│   ├── storage_service.py
│   ├── ai_service.py           # shared Gemini client + timeout/mock-fallback wrapper
│   ├── matching_service.py     # deterministic: orchestrates matching.py, computes match_score
│   ├── graph_service.py        # deterministic: assembles evidence-graph nodes/edges
│   └── audit_service.py
├── config/
│   └── rules.py                # fallback constants if the Firestore settings doc is unreachable
├── schemas/
│   ├── document.py
│   ├── exception.py
│   └── resolution.py
└── utils/
    ├── normalization.py
    ├── matching.py              # pure functions
    └── validation.py
```

## 14. Backend API

Routes unchanged. `main.py` now has working (not empty-placeholder) read endpoints, since these are mechanical and worth having correct from day one:

```python
import os
from datetime import datetime, timezone
from flask import Flask, jsonify, request
from flask_cors import CORS
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)
allowed_origin = os.environ.get("ALLOWED_ORIGIN", "http://localhost:5173")
CORS(app, origins=[allowed_origin])

if not firebase_admin._apps:
    cred = credentials.Certificate(
        os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "serviceAccountKey.json")
    )
    firebase_admin.initialize_app(cred)
db = firestore.client()


@app.get("/health")
def health():
    return jsonify({"status": "ok", "service": "proofaegis-backend"})


@app.get("/api/exceptions")
def list_exceptions():
    docs = db.collection("invoice_exceptions").stream()
    items = [d.to_dict() for d in docs]
    return jsonify({"items": items, "total": len(items)})


@app.get("/api/exceptions/<exception_id>")
def get_exception(exception_id):
    doc = db.collection("invoice_exceptions").document(exception_id).get()
    if not doc.exists:
        return jsonify({"error": "not found"}), 404
    return jsonify(doc.to_dict())


@app.post("/api/exceptions/<exception_id>/investigate")
def investigate_exception(exception_id):
    payload = request.get_json(silent=True) or {}
    # Wire this to agents/document_agent.py + services/matching_service.py
    # + services/graph_service.py as each is built (Days 8-10 of the plan).
    return jsonify({
        "exception_id": exception_id,
        "status": "exception_detected",
        "documents": payload.get("documents", []),
        "findings": [],
        "graph": {"nodes": [], "edges": []},
        "resolution": None,
        "requires_human_review": True,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


@app.post("/api/exceptions/<exception_id>/resolution-draft")
def generate_resolution_draft(exception_id):
    return jsonify({
        "exception_id": exception_id,
        "draft_type": "vendor_correction_request",
        "content": "This is a synthetic resolution draft. Review before sending.",
        "source_references": [],
        "requires_human_review": True,
    })


@app.patch("/api/exceptions/<exception_id>/status")
def update_status(exception_id):
    payload = request.get_json(silent=True) or {}
    new_status = payload.get("status")
    if not new_status:
        return jsonify({"error": "status is required"}), 400
    return jsonify({"exception_id": exception_id, "status": new_status, "updated": True})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app.run(host="0.0.0.0", port=port)
```

## 15. Deterministic matching

`backend/utils/matching.py` — **`compare_quantity` now actually applies tolerance instead of a bare inequality check:**

```python
def percentage_variance(expected, actual):
    if expected == 0:
        return None
    return ((actual - expected) / expected) * 100


def compare_price(po_price, invoice_price, tolerance_percent):
    variance = percentage_variance(po_price, invoice_price)
    if variance is None:
        return {"status": "unable_to_verify", "variance_percentage": None}
    status = "within_tolerance" if abs(variance) <= tolerance_percent else "outside_tolerance"
    return {
        "status": status,
        "expected": po_price,
        "actual": invoice_price,
        "variance": invoice_price - po_price,
        "variance_percentage": variance,
        "tolerance_percentage": tolerance_percent,
    }


def compare_quantity(po_quantity, received_quantity, invoice_quantity, tolerance_percent):
    if po_quantity is None or received_quantity is None:
        return {"status": "missing"}
    variance = percentage_variance(received_quantity, invoice_quantity)
    if variance is None:
        status = "unable_to_verify"
    elif abs(variance) <= tolerance_percent:
        status = "matched"
    else:
        status = "outside_tolerance"
    return {
        "status": status,
        "po_quantity": po_quantity,
        "received_quantity": received_quantity,
        "invoice_quantity": invoice_quantity,
        "unreceived_quantity": max(invoice_quantity - received_quantity, 0),
        "variance_percentage": variance,
        "tolerance_percentage": tolerance_percent,
    }


def compute_match_score(comparisons):
    """comparisons: list of the dicts above (only ones that were evaluable)."""
    evaluable = [c for c in comparisons if c["status"] not in ("missing", "unable_to_verify")]
    if not evaluable:
        return 0
    matched = [c for c in evaluable if c["status"] in ("matched", "within_tolerance")]
    return round(100 * len(matched) / len(evaluable))
```

`services/ai_service.py` — **new: the concrete mock-fallback mechanism the original plan only described in prose:**

```python
import google.generativeai as genai

GEMINI_TIMEOUT_SECONDS = 10


def call_gemini_with_fallback(prompt: str, mock_response, mode: str = "live"):
    """Every AI call site passes its own known-good seeded response as mock_response.
    A live-demo Gemini hiccup silently degrades to that instead of crashing on stage."""
    if mode == "mock":
        return mock_response
    try:
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            prompt, request_options={"timeout": GEMINI_TIMEOUT_SECONDS}
        )
        return response.text
    except Exception:
        return mock_response
```

## 16. Deployment

*(unchanged commands)*

```
cd backend
gcloud run deploy proofaegis-backend \
  --source backend --platform managed --region asia-south1 \
  --allow-unauthenticated \
  --set-env-vars ALLOWED_ORIGIN=https://your-hosting-domain

cd frontend
npm run build
firebase deploy --only hosting
```

Use authentication for any non-demo deployment.

## 17. Required test checklist

*(unchanged — functional and technical checklists both still apply as written)*

---

# Document 3: Technical Architecture

ProofAegis — Architecture Overview

## 1. Architecture goals

*(unchanged)*

## 2. High-level architecture

**Corrected — PDF parsing now happens before the Gemini call, not after it, matching the actual data flow:**

```
┌──────────────────────────┐
│          User            │
│        Browser           │
└────────────┬─────────────┘
             │
             ▼
┌──────────────────────────┐
│ React Frontend           │
│ Firebase Hosting         │
│                          │
│ Dashboard                │
│ Exception Queue          │
│ Match Workspace          │
│ Evidence Graph           │
│ Resolution Assistant     │
└────────────┬─────────────┘
             │ REST
             ▼
┌──────────────────────────────────────┐
│ Flask Backend — Cloud Run             │
│                                        │
│ API Validation · Workflow Orchestration│
│ Matching Service (deterministic)      │
│ Graph Service (deterministic)         │
│ Firestore Services · Storage Services │
└───┬─────────┬─────────┬──────────────┘
    │         │         │
    ▼         ▼         ▼
┌─────────┐ ┌────────────┐ ┌───────────────┐
│PyMuPDF  │→│ Gemini API │ │ Firestore     │
│PDF text │ │ Extraction │ │ Exceptions    │
│extraction│ │ Reasoning  │ │ Findings      │
└─────────┘ │ Drafting   │ │ Graphs        │
            └────────────┘ │ Audit events  │
                            │ Settings      │
                            └───────┬───────┘
                                    ▼
                            ┌───────────────┐
                            │ Cloud Storage │
                            │ Synthetic PDF │
                            └───────────────┘
```

PDF text is extracted first (PyMuPDF); that text is what gets sent to Gemini for classification/extraction. Gemini never sees a raw PDF binary in this design.

## 3. Processing pipeline

*(unchanged — the numbered 1–15 sequence was already correctly ordered: store → classify → extract → normalize → match → tolerance → exception classify → financial impact → evidence graph → resolution draft → save → human review → audit)*

## 4. Responsibilities by layer

*(unchanged, one word trimmed: under "AI layer → Use AI for," drop "Contract and PO interpretation" → "PO interpretation," since no contract documents exist in scope)*

**Frontend** — navigation, upload, dashboard, exception queue, match comparison, graph visualization, citations, draft editing, status changes, audit display, mock fallback. Must not store Gemini keys, perform trusted financial calculations, or assume AI output is correct.

**Backend** — request validation, file handling, AI orchestration, deterministic calculations, Firestore/Storage access, audit events, CORS, error handling.

**AI layer** — use AI for: document classification, field extraction, PO interpretation, explanation, resolution drafting. Do not use AI alone for: arithmetic, tolerance checks, payment release, vendor bank changes, final fraud determination.

**Firestore** — exception metadata, documents, findings, evidence graph, resolution drafts, status, audit events, tolerance settings.

**Cloud Storage** — synthetic PDFs, optional generated reports/exported packets.

## 5. Backend processing components

**Retitled from "AI component design"** — three of the original six items never actually call an LLM; labeling them all "AI components" understated how much of this system is deliberately deterministic, which is the stronger, more defensible story for a judge asking "how do I know the AI isn't making up the numbers?"

**AI-backed (calls Gemini):**

**Component 1 — Document Intelligence Agent**
Input: `{ pdf_text, document_metadata }`
Output:
```json
{
  "document_type": "vendor_invoice",
  "fields": {},
  "source_references": [],
  "confidence": 0.97,
  "warnings": []
}
```

**Component 2 — Exception Reasoning Agent** *(merged: this replaces the old separate "Exception Agent" — same role, just fed by the deterministic Matching Service below instead of by its own contract-parsing step)*
Input: `{ matching_results, document_references, rejection_notice_text }`
Output:
```json
{
  "exception_type": "price_variance",
  "severity": "high",
  "description": "",
  "financial_impact": 25000,
  "recommended_owner": "Procurement",
  "recommended_action": "",
  "confidence": 0.98,
  "requires_human_review": true
}
```

**Component 3 — Resolution Copilot**
Input: `{ exception, financial_impact, source_references, recommended_action }`
Output:
```json
{
  "draft_type": "vendor_correction_request",
  "content": "",
  "source_references": [],
  "requires_human_review": true
}
```

**Deterministic (no LLM call):**

**Matching Service** — Input: `{ invoice_fields, po_fields, receipt_fields, tolerance_rules }` (tolerance rules read from `settings/tolerance_rules`, not parsed from a document). Output: `{ comparisons: [], match_score, exceptions: [] }`. Implemented by `utils/matching.py` (Document 2 §15).

**Evidence Graph Builder** — Input: `{ documents, fields, tolerance_rules, comparisons, exceptions, actions }`. Output: `{ nodes: [], edges: [] }`. Pure data assembly from values already computed above — this is why it doesn't need AI, and why it shouldn't have any: it's the part a judge will use to verify everything else, so it needs to be exactly reproducible, not generated.

## 6. Evidence graph schema

*(unchanged — node/edge JSON shapes and the recommended graph flow: PO document → PO unit price → compared with → Invoice unit price → exceeds → Tolerance rule → creates → Price variance → causes → Financial impact → routes to → Procurement → generates → Vendor correction request)*

## 7. Firestore schema

*(unchanged collections, plus the new `settings/tolerance_rules` doc from Document 2 §7)*

## 8. API contract

*(unchanged — routes and request/response shapes as originally specified)*

## 9. Frontend component structure

**Trimmed to match the collapsed routes (§11 of Document 2) — `documents/` and part of `exceptions/` merge into tabs:**

```
src/
├── components/
│   ├── layout/
│   │   ├── AppShell.jsx
│   │   ├── Sidebar.jsx
│   │   └── Topbar.jsx
│   ├── dashboard/
│   │   ├── MetricCard.jsx
│   │   ├── ActivityTimeline.jsx
│   │   └── ExceptionSummaryChart.jsx
│   ├── exceptions/
│   │   ├── ExceptionTable.jsx        # client-side search/filter/sort
│   │   ├── ExceptionSummary.jsx
│   │   ├── MatchWorkspace.jsx
│   │   ├── ExceptionStatus.jsx
│   │   ├── DocumentsTab.jsx          # was a standalone page; now a tab
│   │   └── AuditTab.jsx              # was a standalone page; now a tab
│   ├── graph/
│   │   ├── EvidenceGraph.jsx
│   │   ├── GraphLegend.jsx
│   │   └── EvidenceDetailsDrawer.jsx
│   ├── resolutions/
│   │   ├── ResolutionAssistant.jsx
│   │   ├── DraftEditor.jsx
│   │   └── SourceCitation.jsx
│   └── ui/
│       ├── Button.jsx
│       ├── Badge.jsx
│       ├── Modal.jsx
│       ├── Drawer.jsx
│       ├── Skeleton.jsx
│       └── EmptyState.jsx
├── pages/
├── services/
├── hooks/
├── data/
└── types/
```

## 10. Responsible AI design

*(unchanged — this section's philosophy was already right; §5 above just makes the architecture actually follow it, since the old Evidence Graph Builder being labeled "AI" contradicted "Code should do... graph.")*

---

# Document 4: Implementation Plan and Demo Plan

ProofAegis — Build Plan to September 5, 2026

The original plan had 24 sequential workdays. Against a roughly 3-week window that's tight even before accounting for a day job — so every day below is tagged **[CORE]** (protect at all costs) or **[STRETCH]** (cut first if you're behind). Two non-must-have screens got folded into tabs, and your first live deployment moved from Day 22 to right after Day 13.

### Critical strategy

*(unchanged, still correct)* Build in this order: one working price-variance case → evidence graph → resolution draft → quantity-variance case → missing-receipt case → dashboard/polish → deployment/backup.

Do not remove: source citations, evidence graph, deterministic match calculation, resolution draft, human-review status, mock fallback.

### Phase 1 — Foundation (protect fully — everything downstream depends on this)

**Day 1 [CORE] — Repo and environment.** Confirm GitHub repo, Cloud project, Firebase project, Firestore db, Storage. Add `.gitignore`, `.env.example`, frontend/backend folders, README.
*Deliverable: repository runs locally with skeletons.*

**Day 2 [CORE] — Firestore and seed data.** Verify project/Firestore. Create collections **including `settings`**. Write and run the seed script (Document 2 §10) — this now also seeds `settings/tolerance_rules`.
*Deliverable: one exception plus the tolerance config visible in Firestore.*

**Day 3 [CORE] — Synthetic PDFs.** Build PDFs for **all three cases now** (not just price-variance) — you'll need them for Days 9, 14, and 15, and generating them once in a batch is faster than context-switching back later.
*Deliverable: three complete synthetic cases exist.*

**Day 4 [CORE] — Frontend shell.** React deps, routes (the trimmed set from Document 2 §11), sidebar/topbar, theme, dashboard skeleton, mock data adapter working end-to-end against static JSON — before any backend exists.
*Deliverable: frontend shell and routes work in mock mode.*

### Phase 2 — Hero workflow (this is the whole submission; nothing here is optional)

**Day 5 [CORE] — Exception queue.** Table, client-side search/filter/sort/risk badges (per the FR-001 note above — no server-side query complexity).
*Deliverable: judge can browse seeded exceptions.*

**Day 6 [CORE] — Exception details.** Summary, vendor/invoice/PO/amount/status/reason/impact/owner, document list.
*Deliverable: judge can open one complete case.*

**Day 7 [CORE] — Match workspace.** Three-column PO/Receipt/Invoice comparison, mismatch highlighting, tolerance display.
*Deliverable: price mismatch is visually obvious.*

**Day 8 [CORE] — Deterministic matching backend.** Implement `matching.py` (Document 2 §15) — price comparison, quantity comparison *with tolerance applied*, match-score formula, unit tests against all three cases.
*Deliverable: the system calculates all three hero cases correctly without AI.*

**Day 9 [CORE] — Document extraction.** PyMuPDF text extraction → `document_agent.py` (Gemini) via the `call_gemini_with_fallback` wrapper. Confidence values, source references.
*Deliverable: at least one real PDF path produces structured fields, with a working mock fallback.*

**Day 10 [CORE] — Evidence graph data.** `graph_service.py` — deterministic node/edge assembly from findings/comparisons already computed. Return via API.
*Deliverable: backend returns a complete evidence graph for the hero case.*

**Day 11 [CORE] — Evidence graph UI.** Render (React Flow), zoom, fit view, legend, node selection, details drawer, citation display, text fallback.
*Deliverable: judge can click from the mismatch to the exact supporting documents.*

**Day 12 [CORE] — Resolution Copilot.** `resolution_agent.py` (Gemini, with mock fallback), citations, edit/copy controls, human-review warning.
*Deliverable: a complete source-cited resolution draft appears.*

**Day 13 [CORE — CHECKPOINT] — Status/audit + first live deploy.** Status selector, assignment, resolution note, audit event write, timeline. **Then deploy exactly this hero path to Cloud Run + Firebase Hosting.**
*Deliverable: a public URL shows the full price-variance case working live — not just on localhost. This is the highest-leverage checkpoint in the plan: any Cloud Run, Firestore permissions, CORS, or secrets problem surfaces now, with over a week of runway, instead of on Day 22 with two days left.*

### Phase 3 — Breadth (cut here first if Day 13 ran long)

**Day 14 [STRETCH] — Quantity-variance case.** Reuses everything from Days 5–13; should be fast since it's a second data path through already-built machinery.

**Day 15 [STRETCH] — Missing-receipt case.** Same reuse logic; add the missing-document UI state.

**Day 16 [STRETCH] — Documents/Audit tabs.** Fold document table and audit timeline into Exception Details tabs (per Document 3 §9) — not standalone pages, since neither is a must-have screen.

*If you only get through Day 13 before time runs out, you still have a complete, judge-ready submission per Document 1 §10's success criteria — just with one exception case instead of three.*

### Phase 4 — Quality and submission (protect the last stretch no matter what got cut above)

**Day 17 [CORE] — Dashboard.** A handful of KPI cards (open exceptions, value on hold, average match score, cases awaiting vendor) plus one simple exception-type chart. Only what's genuinely computable from the seeded data.

**Day 18 [CORE] — Responsible-AI and error states.** "Human review required" banners, confidence labels, AI-failure state, retry, mock-mode indicator, synthetic-data banner. Remove any leftover fraud-detection language.

**Day 19 [CORE] — Hardening and responsive pass.** Schema validation, restricted CORS, no debug output/secrets, keyboard focus, accessible labels, test at desktop/tablet/mobile.

**Day 20 [CORE] — Re-deploy and submission materials.** Final Cloud Run + Firebase deploy, full end-to-end pass (open dashboard → case → documents → match → graph → citations → resolution → status → audit → refresh → force an API failure → confirm mock fallback). Record the 3-minute demo video, backup video, screenshots. Finish README, architecture diagram, limitations section.

### Final buffer

Whatever days remain before September 5: fix whatever the end-to-end pass caught, rehearse the pitch, re-verify no secrets are committed, re-check the deployed URL cold in an incognito window the morning of submission.

### Final demo script

*(unchanged — the 0:00–3:00 script from the original plan still matches this architecture exactly; no changes needed. One optional addition if time allows: at 1:20–1:55, mention that the 5% tolerance shown is read from a configurable Firestore document, not hardcoded — a small, free signal of "production-grade," not "hackathon demo.")*

### Submission README summary

*(unchanged, one line added under Stack)*

```
## Stack
- React and Vite
- Firebase Hosting
- Flask
- Cloud Run
- Firestore (including configurable tolerance rules)
- Cloud Storage
- Gemini API
- React Flow or equivalent graph library

## Important scope note
This is a synthetic-data MVP. It does not release payments, modify vendor
bank details, make final accounting decisions, or replace an ERP.

## Responsible AI
AI classifies documents, extracts fields, and drafts communications.
All arithmetic, tolerance checks, and match scoring are deterministic
code, not model output. Humans control every payment and resolution
decision.
```

### Final build recommendation

*(unchanged, still the right call)* Don't try to finish a full enterprise platform by September 5. Finish this exact product: one excellent invoice-exception workflow, three realistic cases if time allows, a working evidence graph, source citations, deterministic matching, a resolution draft, and a reliable deployed demo.
