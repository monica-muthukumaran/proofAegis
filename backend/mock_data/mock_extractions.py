"""
mock_extractions.py — hand-written mock AI outputs for the 3 seeded cases.

These are what call_gemini_with_fallback returns when USE_MOCK_DATA is set,
or when a live Gemini/ADK call fails. They exist so the hero workflow is
100% demoable with zero API keys, and so unit tests can validate the whole
pipeline without network access.
"""
from __future__ import annotations

from schemas import (
    Citation,
    ExceptionReasoning,
    ExceptionType,
    ExtractionConfidence,
    GoodsReceiptExtraction,
    InvoiceExtraction,
    PurchaseOrderExtraction,
    RejectionNoticeExtraction,
    ResolutionDraft,
    Severity,
)

# --- Case A: EXC-2026-0001 — price variance ---

def mock_invoice_0001() -> InvoiceExtraction:
    return InvoiceExtraction(
        invoice_number="INV-2026-1187", vendor_name="Chennai Industrial Supplies Pvt. Ltd.",
        po_number="PO-2026-00421", invoice_date="2026-07-02",
        line_item_description="Industrial bearings, grade B", quantity=100, unit_price=2650,
        tax_amount=0, total_amount=265000,
        field_confidences=[ExtractionConfidence(field_name="unit_price", confidence=0.98)],
    )


def mock_po_0001() -> PurchaseOrderExtraction:
    return PurchaseOrderExtraction(
        po_number="PO-2026-00421", vendor_name="Chennai Industrial Supplies Pvt. Ltd.",
        line_item_description="Industrial bearings, grade B", quantity=100, unit_price=2400,
        total_amount=240000,
        field_confidences=[ExtractionConfidence(field_name="unit_price", confidence=0.99)],
    )


def mock_receipt_0001() -> GoodsReceiptExtraction:
    return GoodsReceiptExtraction(receipt_number="GRN-0001", po_number="PO-2026-00421",
                                   received_quantity=100, receipt_date="2026-07-05")


def mock_rejection_0001() -> RejectionNoticeExtraction:
    return RejectionNoticeExtraction(invoice_number="INV-2026-1187",
                                      rejection_reason="Unit price exceeds PO price beyond tolerance",
                                      rejected_date="2026-07-06")


def mock_resolution_0001() -> ResolutionDraft:
    return ResolutionDraft(
        subject="Price variance on INV-2026-1187 — request for correction",
        body=(
            "Hello,\n\nInvoice INV-2026-1187 against PO-2026-00421 was received at a unit price of "
            "INR 2,650, against the PO unit price of INR 2,400 — a variance of 10.42%, outside our "
            "5% tolerance. For 100 units, this represents a financial impact of INR 25,000.\n\n"
            "Could you confirm whether this reflects a pricing update we don't have on file, or issue "
            "a corrected invoice at the PO price? Happy to discuss.\n\nThanks,\nAccounts Payable"
        ),
        citations=[
            Citation(claim="Invoice unit price INR 2,650", source_document_id="DOC-0001-INV", source_field="unit_price"),
            Citation(claim="PO unit price INR 2,400", source_document_id="DOC-0001-PO", source_field="unit_price"),
        ],
        recommended_owner="Procurement",
    )


def mock_reasoning_0001() -> ExceptionReasoning:
    """Case A's reasoning, carrying a DELIBERATELY WRONG financial impact.

    31,200 is not a typo and it is not a number any document supports. It is
    an injected fault, and it is here because a guardrail nobody watches fire
    is indistinguishable from a guardrail that does not exist. The correct
    figure is 100 units x the 250 variance = 25,000, and matching_service.py
    computes exactly that; this value is what the reasoning layer *claims*,
    so the override runs for real on the hero case rather than being asserted
    in a slide.

    Everything downstream treats it honestly. services/trust_ledger.py
    records it as `kind="fault_injection"` and keeps it out of every statistic
    about what a model actually did — see FAULT_INJECTED_CASES below — and the
    UI labels it as an injected fault rather than passing it off as a real
    Gemini response. What the demo demonstrates is the mechanism, and the
    mechanism is genuine: nothing in the pipeline knows this number is wrong,
    and the deterministic value wins anyway.
    """
    return ExceptionReasoning(
        exception_type=ExceptionType.PRICE_VARIANCE,
        severity=Severity.HIGH,
        description=(
            "This invoice bills 100 units at INR 2,650 each, but the purchase order set the price "
            "at INR 2,400 — a 10.42% overcharge, above the 5% tolerance we allow automatically."
        ),
        financial_impact=31200,
        recommended_owner="Procurement",
        recommended_action="Request a corrected invoice from the vendor at the PO unit price, or obtain written confirmation of a price update.",
        confidence=0.95,
    )


# --- Case B: EXC-2026-0002 — quantity variance ---

def mock_invoice_0002() -> InvoiceExtraction:
    return InvoiceExtraction(
        invoice_number="INV-2026-2204", vendor_name="Southern Office Systems", po_number="PO-2026-00516",
        invoice_date="2026-07-10", line_item_description="Office desk units", quantity=500, unit_price=630,
        tax_amount=0, total_amount=315000,
        field_confidences=[ExtractionConfidence(field_name="quantity", confidence=0.97)],
    )


def mock_po_0002() -> PurchaseOrderExtraction:
    return PurchaseOrderExtraction(
        po_number="PO-2026-00516", vendor_name="Southern Office Systems",
        line_item_description="Office desk units", quantity=500, unit_price=630, total_amount=315000,
        field_confidences=[ExtractionConfidence(field_name="quantity", confidence=0.98)],
    )


def mock_receipt_0002() -> GoodsReceiptExtraction:
    return GoodsReceiptExtraction(receipt_number="GRN-0002", po_number="PO-2026-00516",
                                   received_quantity=420, receipt_date="2026-07-12")


def mock_rejection_0002() -> RejectionNoticeExtraction:
    return RejectionNoticeExtraction(invoice_number="INV-2026-2204",
                                      rejection_reason="Invoiced quantity exceeds received quantity beyond tolerance",
                                      rejected_date="2026-07-13")


def mock_resolution_0002() -> ResolutionDraft:
    return ResolutionDraft(
        subject="Quantity variance on INV-2026-2204 — 80 units unreceived",
        body=(
            "Hello,\n\nInvoice INV-2026-2204 bills 500 units against PO-2026-00516, but the goods "
            "receipt on file shows only 420 units received — a variance of 19.05%, outside our 2% "
            "tolerance. At the implied unit price of INR 630, this represents INR 50,400 at risk "
            "pending confirmation.\n\nCould Receiving confirm whether the remaining 80 units are in "
            "transit, or whether the invoice should be revised?\n\nThanks,\nAccounts Payable"
        ),
        citations=[
            Citation(claim="Invoiced quantity 500 units", source_document_id="DOC-0002-INV", source_field="quantity"),
            Citation(claim="Received quantity 420 units", source_document_id="DOC-0002-GRN", source_field="received_quantity"),
        ],
        recommended_owner="Receiving",
    )


def mock_reasoning_0002() -> ExceptionReasoning:
    return ExceptionReasoning(
        exception_type=ExceptionType.QUANTITY_VARIANCE,
        severity=Severity.MEDIUM,
        description=(
            "500 units were invoiced, but the goods receipt shows only 420 units actually arrived — "
            "a 19.05% shortfall, well above the 2% tolerance. INR 50,400 of unreceived goods is at risk."
        ),
        financial_impact=50400,
        recommended_owner="Receiving",
        recommended_action="Ask Receiving to confirm whether the remaining 80 units are still in transit before releasing payment for the full invoice.",
        confidence=0.93,
    )


# --- Case C: EXC-2026-0003 — missing goods receipt ---

def mock_invoice_0003() -> InvoiceExtraction:
    return InvoiceExtraction(
        invoice_number="INV-2026-3310", vendor_name="BlueWave IT Services", po_number="PO-2026-00602",
        invoice_date="2026-07-15", line_item_description="Managed IT support — July", quantity=1,
        unit_price=180000, tax_amount=0, total_amount=180000,
        field_confidences=[ExtractionConfidence(field_name="total_amount", confidence=0.97)],
    )


def mock_po_0003() -> PurchaseOrderExtraction:
    return PurchaseOrderExtraction(
        po_number="PO-2026-00602", vendor_name="BlueWave IT Services",
        line_item_description="Managed IT support — July", quantity=1, unit_price=180000, total_amount=180000,
        field_confidences=[ExtractionConfidence(field_name="total_amount", confidence=0.98)],
    )


def mock_rejection_0003() -> RejectionNoticeExtraction:
    return RejectionNoticeExtraction(invoice_number="INV-2026-3310",
                                      rejection_reason="No goods receipt / service confirmation on file",
                                      rejected_date="2026-07-16")


def mock_resolution_0003() -> ResolutionDraft:
    return ResolutionDraft(
        subject="Missing goods receipt for INV-2026-3310 — confirmation needed",
        body=(
            "Hello,\n\nInvoice INV-2026-3310 against PO-2026-00602 has no goods receipt or service "
            "confirmation on file. The full invoice amount of INR 180,000 is on hold pending "
            "confirmation.\n\nCould the requesting business unit confirm delivery/completion of the "
            "service so we can proceed?\n\nThanks,\nAccounts Payable"
        ),
        citations=[
            Citation(claim="Invoice total INR 180,000", source_document_id="DOC-0003-INV", source_field="total_amount"),
        ],
        recommended_owner="Requesting business unit",
    )


def mock_reasoning_0003() -> ExceptionReasoning:
    return ExceptionReasoning(
        exception_type=ExceptionType.MISSING_GOODS_RECEIPT,
        severity=Severity.HIGH,
        description=(
            "No goods receipt or service confirmation is on file for this invoice. The full "
            "INR 180,000 is unverified and should not be paid until delivery/completion is confirmed."
        ),
        financial_impact=180000,
        recommended_owner="Requesting business unit",
        recommended_action="Obtain a goods receipt or written service-completion confirmation from the requesting business unit before releasing payment.",
        confidence=0.90,
    )


DOCUMENT_MOCKS = {
    ("EXC-2026-0001", "vendor_invoice"): mock_invoice_0001,
    ("EXC-2026-0001", "purchase_order"): mock_po_0001,
    ("EXC-2026-0001", "goods_receipt_note"): mock_receipt_0001,
    ("EXC-2026-0001", "rejection_notice"): mock_rejection_0001,
    ("EXC-2026-0002", "vendor_invoice"): mock_invoice_0002,
    ("EXC-2026-0002", "purchase_order"): mock_po_0002,
    ("EXC-2026-0002", "goods_receipt_note"): mock_receipt_0002,
    ("EXC-2026-0002", "rejection_notice"): mock_rejection_0002,
    ("EXC-2026-0003", "vendor_invoice"): mock_invoice_0003,
    ("EXC-2026-0003", "purchase_order"): mock_po_0003,
    ("EXC-2026-0003", "rejection_notice"): mock_rejection_0003,
}

RESOLUTION_MOCKS = {
    "EXC-2026-0001": mock_resolution_0001,
    "EXC-2026-0002": mock_resolution_0002,
    "EXC-2026-0003": mock_resolution_0003,
}

REASONING_MOCKS = {
    "EXC-2026-0001": mock_reasoning_0001,
    "EXC-2026-0002": mock_reasoning_0002,
    "EXC-2026-0003": mock_reasoning_0003,
}

# Cases whose seeded reasoning states a financial impact that is knowingly
# wrong, so the deterministic override can be watched firing rather than
# described. Membership here is what makes the resulting TrustCheck honest:
# services/case_service.py marks it `fault_injection`, which keeps it out of
# every figure describing what a live model did, and the UI labels it as an
# injected fault rather than as a Gemini response.
#
# Only ever add a case here alongside a comment in its mock explaining what
# the correct value is and why it was corrupted.
FAULT_INJECTED_CASES = frozenset({"EXC-2026-0001"})
