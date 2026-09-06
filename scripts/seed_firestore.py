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