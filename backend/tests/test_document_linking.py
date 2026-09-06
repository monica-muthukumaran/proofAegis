"""
Regression tests for the five gaps found when real vendor documents were run
through the pipeline for the first time.

The synthetic PDFs are single-line, label/value documents from one order, so
none of these failures could show up against them. Each test here encodes a
specific way real paperwork differs.
"""
import pytest

from services import ingestion_service as I
from services.matching_service import evaluate_exception
from schemas import MatchClassification

TOLERANCE = {"price_variance_percent": 5, "quantity_variance_percent": 2}


def document(document_id, document_type, extraction, uploaded_at):
    return {
        "document_id": document_id,
        "document_type": document_type,
        "processing_state": "completed",
        "extraction": extraction,
        "uploaded_at": uploaded_at,
    }


# --- Gap 1: the counterpart document is chosen by reference, not recency ----
def test_purchase_order_is_selected_by_the_invoices_po_number_not_upload_order():
    """The bug: upload an unrelated PO last and the invoice was matched
    against it, producing a confident 2270% price variance between a plumbing
    invoice and a lighting order."""
    documents = [
        document("DOC-PO-RIGHT", "purchase_order",
                 {"po_number": "PO/SRPL/26/19451", "vendor_name": "SIGMA", "total_amount": 62540.0},
                 "2026-08-31T00:01:00Z"),
        document("DOC-INV", "vendor_invoice",
                 {"invoice_number": "SES-26-030", "po_number": "PO/SRPL/26/19451",
                  "vendor_name": "SIGMA", "total_amount": 62540.0},
                 "2026-08-31T00:02:00Z"),
        # Uploaded LAST, belongs to a different order entirely.
        document("DOC-PO-WRONG", "purchase_order",
                 {"po_number": "PO/SMPL/26/19596", "vendor_name": "REFLECTIONS", "total_amount": 43808.0},
                 "2026-08-31T00:03:00Z"),
    ]
    matching_input, sources = I.build_matching_input(documents)

    assert sources["purchase_order"] == "DOC-PO-RIGHT"
    assert matching_input["po_number"] == "PO/SRPL/26/19451"
    assert sources["link_warnings"] == []


@pytest.mark.parametrize("po_number_on_order", [
    "PO-SRPL-26-19451",       # ERP export uses hyphens
    "po/srpl/26/19451",       # lower case
    "PO / SRPL / 26 / 19451",  # spaced out
])
def test_reference_matching_survives_separator_and_case_differences(po_number_on_order):
    documents = [
        document("DOC-PO", "purchase_order",
                 {"po_number": po_number_on_order, "vendor_name": "SIGMA", "total_amount": 100.0},
                 "2026-08-31T00:01:00Z"),
        document("DOC-INV", "vendor_invoice",
                 {"invoice_number": "INV-1", "po_number": "PO/SRPL/26/19451",
                  "vendor_name": "SIGMA", "total_amount": 100.0},
                 "2026-08-31T00:02:00Z"),
    ]
    _, sources = I.build_matching_input(documents)
    assert sources["purchase_order"] == "DOC-PO"
    assert sources["link_warnings"] == []


def test_falling_back_to_recency_is_reported_rather_than_hidden():
    """When nothing carries a matching reference the analysis still runs — but
    the reviewer is told the pairing is unverified."""
    documents = [
        document("DOC-INV", "vendor_invoice",
                 {"invoice_number": "INV-1", "po_number": "PO/SRPL/26/19451",
                  "vendor_name": "SIGMA", "total_amount": 100.0},
                 "2026-08-31T00:01:00Z"),
        document("DOC-PO", "purchase_order",
                 {"po_number": "PO/OTHER/99", "vendor_name": "OTHER", "total_amount": 100.0},
                 "2026-08-31T00:02:00Z"),
    ]
    _, sources = I.build_matching_input(documents)

    assert sources["purchase_order"] == "DOC-PO"
    warnings = sources["link_warnings"]
    assert len(warnings) == 1
    assert warnings[0]["code"] == "reference_mismatch"
    assert "PO/SRPL/26/19451" in warnings[0]["detail"]


def test_an_invoice_with_no_po_number_reports_an_unverified_link():
    documents = [
        document("DOC-INV", "vendor_invoice",
                 {"invoice_number": "INV-1", "vendor_name": "SIGMA", "total_amount": 100.0},
                 "2026-08-31T00:01:00Z"),
        document("DOC-PO", "purchase_order",
                 {"po_number": "PO/1", "vendor_name": "SIGMA", "total_amount": 100.0},
                 "2026-08-31T00:02:00Z"),
    ]
    _, sources = I.build_matching_input(documents)
    assert sources["link_warnings"][0]["code"] == "unverified_link"


# --- Gap 2: multi-line documents ------------------------------------------
def _multi_line_case(invoice_lines):
    return {
        "vendor_name": "SIGMA", "po_vendor_name": "SIGMA",
        "po_number": "PO/1", "invoice_po_number": "PO/1",
        "purchase_order_exists": True, "goods_receipt_exists": True,
        "received_quantity": None, "invoice_quantity": None,
        "invoice_unit_price": None, "po_unit_price": None,
        "invoice_amount": sum(line["amount"] for line in invoice_lines),
        "invoice_total": sum(line["amount"] for line in invoice_lines),
        "po_total": 53000.0,
        "po_line_items": [
            {"description": "Water tank", "quantity": 1, "unit_price": 16000, "amount": 16000},
            {"description": "Modular toilet", "quantity": 1, "unit_price": 22000, "amount": 22000},
            {"description": "EWC Toilet", "quantity": 1, "unit_price": 15000, "amount": 15000},
        ],
        "invoice_line_items": invoice_lines,
    }


def test_one_overcharged_line_is_caught_inside_an_otherwise_correct_order():
    """The case a single unit_price field cannot express: two lines billed
    correctly, the third overcharged."""
    case = _multi_line_case([
        {"description": "Water tank", "quantity": 1, "unit_price": 16000, "amount": 16000},
        {"description": "Modular toilet", "quantity": 1, "unit_price": 22000, "amount": 22000},
        {"description": "EWC Toilet", "quantity": 1, "unit_price": 20000, "amount": 20000},
    ])
    result = evaluate_exception(case, TOLERANCE)

    assert result.exception_type.value == "price_variance"
    assert result.financial_impact == 5000.0
    breached = [c for c in result.line_comparisons
                if c.classification == MatchClassification.OUTSIDE_TOLERANCE]
    assert len(breached) == 1
    assert breached[0].description == "EWC Toilet"


def test_a_line_billed_but_never_ordered_is_a_finding():
    case = _multi_line_case([
        {"description": "Water tank", "quantity": 1, "unit_price": 16000, "amount": 16000},
        {"description": "Modular toilet", "quantity": 1, "unit_price": 22000, "amount": 22000},
        {"description": "Extra scaffolding", "quantity": 1, "unit_price": 9000, "amount": 9000},
    ])
    result = evaluate_exception(case, TOLERANCE)

    assert result.exception_type.value == "price_variance"
    assert result.financial_impact == 9000.0
    billed_only = [c for c in result.line_comparisons if c.only_on == "invoice"]
    assert [c.description for c in billed_only] == ["Extra scaffolding"]


def test_matching_line_items_produce_no_exception():
    case = _multi_line_case([
        {"description": "Water tank", "quantity": 1, "unit_price": 16000, "amount": 16000},
        {"description": "Modular toilet", "quantity": 1, "unit_price": 22000, "amount": 22000},
        {"description": "EWC Toilet", "quantity": 1, "unit_price": 15000, "amount": 15000},
    ])
    result = evaluate_exception(case, TOLERANCE)

    assert result.exception_type.value == "no_exception"
    assert result.financial_impact == 0.0
    assert all(c.classification == MatchClassification.MATCHED for c in result.line_comparisons)


def test_line_descriptions_pair_despite_wording_differences():
    """A PO says "Water tank &Plumbing Pipeline work", the invoice says
    "Water tank &Plumbing Pipeline". Same line."""
    case = _multi_line_case([
        {"description": "Water tank", "quantity": 1, "unit_price": 16000, "amount": 16000},
        {"description": "Modular toilet reconditioning", "quantity": 1, "unit_price": 22000, "amount": 22000},
        {"description": "EWC Toilet", "quantity": 1, "unit_price": 15000, "amount": 15000},
    ])
    result = evaluate_exception(case, TOLERANCE)
    assert not [c for c in result.line_comparisons if c.only_on]


# --- Gap 3: progress ------------------------------------------------------
def test_progress_reports_the_document_currently_being_read():
    documents = [
        {"document_id": "D1", "file_name": "a.pdf", "processing_state": "completed",
         "uploaded_at": "1"},
        {"document_id": "D2", "file_name": "b.pdf", "processing_state": "processing",
         "document_type": "vendor_invoice", "uploaded_at": "2"},
        {"document_id": "D3", "file_name": "c.pdf", "processing_state": "queued", "uploaded_at": "3"},
    ]
    state = I.progress(documents)

    assert state["total"] == 3
    assert state["finished"] == 1
    assert state["percent"] == 33
    assert state["active_document"]["file_name"] == "b.pdf"
    assert [d["processing_state"] for d in state["documents"]] == ["completed", "processing", "queued"]


# --- Gap 4: quotations ----------------------------------------------------
def test_quotation_is_a_supported_document_type():
    assert "quotation" in I.SUPPORTED_TYPES


def test_a_quotation_does_not_become_the_purchase_order():
    """It is evidence, not a matching input — it must never be substituted for
    the order the invoice is checked against."""
    documents = [
        document("DOC-Q", "quotation",
                 {"quotation_number": "SES/1371/8", "vendor_name": "SIGMA", "total_amount": 53000.0},
                 "2026-08-31T00:01:00Z"),
        document("DOC-INV", "vendor_invoice",
                 {"invoice_number": "SES-26-030", "po_number": "PO/1",
                  "vendor_name": "SIGMA", "total_amount": 62540.0},
                 "2026-08-31T00:02:00Z"),
    ]
    matching_input, sources = I.build_matching_input(documents)

    assert sources["purchase_order"] is None
    assert matching_input["purchase_order_exists"] is False
