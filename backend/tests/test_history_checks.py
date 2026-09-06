"""
The checks that need more than one case: duplicates, cumulative billing and
changed payment details.

`duplicate_invoice` was declared in the ExceptionType enum, given an owner in
the synthetic generator and rendered as an 8% slice of the dashboard's chart
— and never produced by any code path. Uploading the same invoice twice
raised nothing. These tests exist so that cannot silently become true again.
"""
import pytest

from services import history_service as H
from services.matching_service import evaluate_exception

TOLERANCE = {"price_variance_percent": 5, "quantity_variance_percent": 2}


def invoice(document_id, *, number, vendor, amount, po=None, date=None,
            exception_id="EXC-OLD", uploaded_at="2026-08-01T00:00:00Z", **extra):
    extraction = {"invoice_number": number, "vendor_name": vendor,
                  "total_amount": amount, "po_number": po, "invoice_date": date}
    extraction.update(extra)
    return {
        "document_id": document_id,
        "exception_id": exception_id,
        "document_type": "vendor_invoice",
        "processing_state": "completed",
        "uploaded_at": uploaded_at,
        "extraction": extraction,
    }


# --- duplicates -----------------------------------------------------------
def test_the_same_invoice_number_from_the_same_vendor_is_an_exact_duplicate():
    current = invoice("D2", number="SES-26-030", vendor="SIGMA", amount=62540.0)
    prior = [invoice("D1", number="SES-26-030", vendor="SIGMA", amount=62540.0)]

    found = H.find_duplicate_invoices(current, prior)

    assert len(found) == 1
    assert found[0]["confidence"] == "exact"
    assert found[0]["document_id"] == "D1"


def test_a_re_issued_invoice_under_a_new_number_is_caught_by_amount_and_date():
    """Matching on invoice number alone misses the commonest duplicate."""
    current = invoice("D2", number="SES-26-031", vendor="SIGMA", amount=62540.0,
                      date="19-Aug-26")
    prior = [invoice("D1", number="SES-26-030", vendor="SIGMA", amount=62540.0,
                     date="12-Aug-26")]

    found = H.find_duplicate_invoices(current, prior)

    assert len(found) == 1
    assert found[0]["confidence"] == "near"


def test_a_monthly_retainer_is_not_a_duplicate():
    """Same vendor, same amount, different number, months apart — a recurring
    bill, not a re-submission."""
    current = invoice("D2", number="RET-09", vendor="SIGMA", amount=25000.0, date="01-Sep-26")
    prior = [invoice("D1", number="RET-01", vendor="SIGMA", amount=25000.0, date="01-Jan-26")]

    assert H.find_duplicate_invoices(current, prior) == []


def test_the_same_number_from_a_different_vendor_is_not_a_duplicate():
    current = invoice("D2", number="INV-001", vendor="SIGMA", amount=1000.0)
    prior = [invoice("D1", number="INV-001", vendor="REFLECTIONS", amount=1000.0)]

    assert H.find_duplicate_invoices(current, prior) == []


def test_an_unidentified_vendor_makes_no_duplicate_claim():
    """UNKNOWN would otherwise match every other unreadable invoice."""
    current = invoice("D2", number="X", vendor="UNKNOWN", amount=100.0)
    prior = [invoice("D1", number="Y", vendor="UNKNOWN", amount=100.0)]

    assert H.find_duplicate_invoices(current, prior) == []


def test_vendor_and_number_formatting_differences_do_not_hide_a_duplicate():
    current = invoice("D2", number="ses/26/030", vendor="Sigma Engineering Solutions.",
                      amount=62540.0)
    prior = [invoice("D1", number="SES-26-030", vendor="SIGMA ENGINEERING SOLUTIONS",
                     amount=62540.0)]

    assert H.find_duplicate_invoices(current, prior)[0]["confidence"] == "exact"


def test_a_duplicate_outranks_every_other_finding():
    """Paying twice is the wrong action regardless of what the variances say,
    so nothing else should be the headline."""
    case = {
        "vendor_name": "SIGMA", "po_vendor_name": "SIGMA",
        "po_number": "PO/1", "invoice_po_number": "PO/1",
        "purchase_order_exists": True, "goods_receipt_exists": False,
        "invoice_amount": 62540.0, "invoice_total": 62540.0, "po_total": 62540.0,
        "duplicate_of": [{"confidence": "exact", "reason": "Already recorded.",
                          "document_id": "D1", "exception_id": "EXC-OLD"}],
    }
    result = evaluate_exception(case, TOLERANCE)

    assert result.exception_type.value == "duplicate_invoice"
    assert result.financial_impact == 62540.0
    assert result.risk_level == "high"
    assert result.duplicate_of


# --- cumulative billing ---------------------------------------------------
def test_instalments_that_each_pass_can_together_exceed_the_order():
    current = invoice("D3", number="INV-3", vendor="SIGMA", amount=30000.0, po="PO/1")
    prior = [invoice("D1", number="INV-1", vendor="SIGMA", amount=40000.0, po="PO/1")]

    billing = H.cumulative_billing("PO/1", 53000.0, current, prior)

    assert billing["total_billed"] == 70000.0
    assert billing["is_over_billed"] is True
    assert billing["over_billed_by"] == 17000.0
    assert billing["invoice_count"] == 2


def test_billing_within_the_order_leaves_a_remaining_balance():
    current = invoice("D2", number="INV-2", vendor="SIGMA", amount=13000.0, po="PO/1")
    prior = [invoice("D1", number="INV-1", vendor="SIGMA", amount=40000.0, po="PO/1")]

    billing = H.cumulative_billing("PO/1", 53000.0, current, prior)

    assert billing["remaining"] == 0.0
    assert billing["is_over_billed"] is False


def test_invoices_against_other_orders_are_not_counted():
    current = invoice("D2", number="INV-2", vendor="SIGMA", amount=30000.0, po="PO/1")
    prior = [invoice("D1", number="INV-1", vendor="SIGMA", amount=40000.0, po="PO/2")]

    billing = H.cumulative_billing("PO/1", 53000.0, current, prior)

    assert billing["previously_billed"] == 0.0
    assert billing["invoice_count"] == 1


def test_over_billing_is_only_a_finding_when_several_invoices_are_involved():
    """One invoice above its order is a price variance — the existing
    comparisons describe it better than a running total does."""
    single = {
        "vendor_name": "SIGMA", "po_vendor_name": "SIGMA",
        "po_number": "PO/1", "invoice_po_number": "PO/1",
        "purchase_order_exists": True, "goods_receipt_exists": True,
        "received_quantity": None, "invoice_amount": 70000.0,
        # Both sides stated on the same (tax-exclusive) basis, so the running
        # total is comparable with the order value. Without that the check
        # correctly refuses to judge — see tax_basis in matching_service.
        "invoice_total": 70000.0, "invoice_subtotal": 70000.0,
        "po_total": 53000.0, "po_subtotal": 53000.0,
        "po_billing": {"po_number": "PO/1", "order_value": 53000.0, "total_billed": 70000.0,
                       "over_billed_by": 17000.0, "is_over_billed": True, "invoice_count": 1,
                       "previously_billed": 0.0, "this_invoice": 70000.0, "remaining": -17000.0,
                       "prior_invoices": []},
    }
    assert evaluate_exception(single, TOLERANCE).exception_type.value != "po_over_billed"

    several = dict(single)
    several["po_billing"] = dict(single["po_billing"], invoice_count=2)
    result = evaluate_exception(several, TOLERANCE)
    assert result.exception_type.value == "po_over_billed"
    assert result.financial_impact == 17000.0


# --- payment details ------------------------------------------------------
def test_a_changed_bank_account_for_a_known_vendor_is_reported():
    current = invoice("D2", number="INV-2", vendor="SIGMA", amount=1000.0,
                      bank_account_number="912837465500")
    prior = [invoice("D1", number="INV-1", vendor="SIGMA", amount=1000.0,
                     bank_account_number="500123456789")]

    changes = H.find_payment_detail_changes(current, prior)

    assert len(changes) == 1
    assert changes[0]["field"] == "bank_account_number"
    assert changes[0]["previous_value"] == "500123456789"
    # The advice must not send the reviewer back to the suspect document.
    assert "channel you already trust" in changes[0]["detail"]


def test_unchanged_bank_details_raise_nothing():
    current = invoice("D2", number="INV-2", vendor="SIGMA", amount=1000.0,
                      bank_account_number="500123456789")
    prior = [invoice("D1", number="INV-1", vendor="SIGMA", amount=1000.0,
                     bank_account_number="500123456789")]

    assert H.find_payment_detail_changes(current, prior) == []


def test_only_the_most_recent_prior_invoice_is_compared():
    """A vendor that legitimately changed banks once must not generate a
    finding on every invoice afterwards."""
    current = invoice("D3", number="INV-3", vendor="SIGMA", amount=1000.0,
                      bank_account_number="NEW999", uploaded_at="2026-08-03T00:00:00Z")
    prior = [
        invoice("D1", number="INV-1", vendor="SIGMA", amount=1000.0,
                bank_account_number="OLD111", uploaded_at="2026-08-01T00:00:00Z"),
        invoice("D2", number="INV-2", vendor="SIGMA", amount=1000.0,
                bank_account_number="NEW999", uploaded_at="2026-08-02T00:00:00Z"),
    ]

    assert H.find_payment_detail_changes(current, prior) == []


def test_a_first_invoice_from_a_new_vendor_raises_nothing():
    current = invoice("D1", number="INV-1", vendor="NEWCO", amount=1000.0,
                      bank_account_number="123456789")
    assert H.find_payment_detail_changes(current, []) == []


# --- invoice self-consistency and the quotation chain ---------------------
def test_an_invoice_that_does_not_add_up_against_itself_is_a_finding():
    case = {
        "vendor_name": "SIGMA", "po_vendor_name": "SIGMA",
        "po_number": "PO/1", "invoice_po_number": "PO/1",
        "purchase_order_exists": True, "goods_receipt_exists": True,
        "received_quantity": None,
        "invoice_subtotal": 53000.0, "tax_amount": 9540.0,
        # 53,000 + 9,540 = 62,540, not 72,540.
        "invoice_total": 72540.0, "invoice_amount": 72540.0,
    }
    result = evaluate_exception(case, TOLERANCE)

    assert result.exception_type.value == "tax_total_mismatch"
    assert result.financial_impact == 10000.0


def test_a_correct_invoice_passes_its_own_arithmetic():
    case = {
        "vendor_name": "SIGMA", "po_vendor_name": "SIGMA",
        "po_number": "PO/1", "invoice_po_number": "PO/1",
        "purchase_order_exists": True, "goods_receipt_exists": True,
        "received_quantity": None,
        "invoice_subtotal": 53000.0, "tax_amount": 9540.0,
        "invoice_total": 62540.0, "invoice_amount": 62540.0,
    }
    assert evaluate_exception(case, TOLERANCE).exception_type.value == "no_exception"


def test_an_order_raised_above_its_quotation_is_flagged():
    case = {
        "vendor_name": "SIGMA", "po_vendor_name": "SIGMA",
        "po_number": "PO/1", "invoice_po_number": "PO/1",
        "purchase_order_exists": True, "goods_receipt_exists": True,
        "received_quantity": None, "invoice_amount": 60000.0,
        "po_subtotal": 60000.0, "quotation_total": 53000.0,
    }
    result = evaluate_exception(case, TOLERANCE)
    quoted = [c for c in result.comparisons if c.field.value == "quoted_price"]

    assert quoted and quoted[0].classification.value == "outside_tolerance"
    assert quoted[0].expected_value == 53000.0


def test_a_gross_total_is_never_compared_against_a_net_one():
    """A PO quoted ex-GST against a tax-inclusive invoice is an 18% "breach"
    that describes the tax rate, not an overcharge."""
    case = {
        "vendor_name": "SIGMA", "po_vendor_name": "SIGMA",
        "po_number": "PO/1", "invoice_po_number": "PO/1",
        "purchase_order_exists": True, "goods_receipt_exists": True,
        "received_quantity": None,
        "invoice_subtotal": 53000.0, "po_subtotal": 53000.0,
        "tax_amount": 9540.0, "po_tax_amount": None,
        "invoice_total": 62540.0, "po_total": 53000.0, "invoice_amount": 62540.0,
    }
    result = evaluate_exception(case, TOLERANCE)
    total = next(c for c in result.comparisons if c.field.value == "total")

    assert total.classification.value == "unable_to_verify"
    assert result.exception_type.value == "no_exception"


# --- date parsing ---------------------------------------------------------
@pytest.mark.parametrize("value", ["2026-08-19", "19-Aug-26", "19/08/2026", "19.08.2026"])
def test_invoice_dates_parse_across_the_formats_these_documents_use(value):
    assert H._parse_date(value) is not None


def test_an_unreadable_date_is_none_rather_than_today():
    assert H._parse_date("sometime last Tuesday") is None


def test_a_running_total_is_not_judged_against_an_order_on_a_different_basis():
    """The same units rule as the total comparison.

    Tax-inclusive invoices measured against a tax-exclusive order value report
    over-billing that is really just the tax — which is exactly what the
    deterministic fallback produced before this guard, because it often
    recovers a gross invoice total and a net order total.
    """
    case = {
        "vendor_name": "SIGMA", "po_vendor_name": "SIGMA",
        "po_number": "PO/1", "invoice_po_number": "PO/1",
        "purchase_order_exists": True, "goods_receipt_exists": True,
        "received_quantity": None, "invoice_amount": 62540.0,
        # Gross invoice, net order: not comparable, and not a finding.
        "invoice_total": 62540.0, "tax_amount": 9540.0,
        "po_total": 53000.0, "po_subtotal": 53000.0,
        "po_billing": {"po_number": "PO/1", "order_value": 53000.0, "total_billed": 62540.0,
                       "over_billed_by": 9540.0, "is_over_billed": True, "invoice_count": 2,
                       "previously_billed": 0.0, "this_invoice": 62540.0, "remaining": -9540.0,
                       "prior_invoices": []},
    }
    result = evaluate_exception(case, TOLERANCE)

    assert result.exception_type.value != "po_over_billed"
    billed = next(c for c in result.comparisons if c.field.value == "po_billed_total")
    assert billed.classification.value == "unable_to_verify"
    assert billed.evaluable is False
