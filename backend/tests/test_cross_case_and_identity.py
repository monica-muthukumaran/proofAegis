"""
The two things the eval harness found, and the number the product is selling.

VENDOR IDENTITY. The matcher compared vendor names as raw lowercased strings,
so an order raised on "Chennai Industrial Supplies Pvt. Ltd." against an
invoice from "M/s Chennai Industrial Supplies Private Limited" was reported as
a vendor mismatch. The eval measured it at 21 false positives out of 21
spelling variants — detection precision 1.00 -> 0.87 on that alone. These
tests pin both directions: variants fold, genuinely different companies do
not.

CROSS-CASE VALUE. The headline. It has one way of going quietly wrong — the
set of "cross-case" types drifting out of step with what the matcher actually
flags — so the set is declared once in schemas.py and asserted here against
both of its two other copies.
"""
from schemas import CROSS_CASE_TYPE_VALUES, ExceptionType
from services.analytics_service import cross_case_value
from services.matching_service import vendor_key


# ---------------------------------------------------------------------------
# Vendor identity
# ---------------------------------------------------------------------------
def test_legal_form_and_honorific_fold_to_one_identity():
    canonical = vendor_key("Chennai Industrial Supplies Pvt. Ltd.")
    for variant in (
        "M/s Chennai Industrial Supplies Private Limited",
        "CHENNAI INDUSTRIAL SUPPLIES PVT LTD",
        "Chennai Industrial Supplies Pvt. Ltd.,",
        "Messrs. Chennai Industrial Supplies Pvt Ltd",
    ):
        assert vendor_key(variant) == canonical, variant


def test_ampersand_and_the_word_and_are_the_same_company():
    assert vendor_key("Anand & Sons") == vendor_key("Anand and Sons")


def test_two_different_companies_stay_different():
    """The folding is narrow on purpose. Anything differing in an actual word
    must still compare as different, or a genuine vendor mismatch — the case
    this check exists for — would be folded away with the false ones."""
    assert vendor_key("Southern Office Systems") != vendor_key("Northern Office Systems")
    assert vendor_key("BlueWave IT Services") != vendor_key("BlueWave IT Solutions")
    assert vendor_key("Kaveri Packaging Co.") != vendor_key("Kaveri Logistics Co.")


def test_an_absent_name_is_never_a_match():
    """Two blanks are not the same vendor, and compare_exact must not treat
    them as one."""
    assert vendor_key(None) == ""
    assert vendor_key("   ") == ""


def test_a_spelling_variant_does_not_raise_a_vendor_mismatch():
    from services.matching_service import evaluate_exception

    result = evaluate_exception({
        "vendor_name": "M/s Chennai Industrial Supplies Private Limited",
        "po_vendor_name": "Chennai Industrial Supplies Pvt. Ltd.",
        "po_number": "PO-1", "invoice_po_number": "PO-1",
        "po_unit_price": 2400.0, "invoice_unit_price": 2400.0,
        "po_quantity": 100, "received_quantity": 100, "invoice_quantity": 100,
        "invoice_amount": 240000.0, "invoice_total": 240000.0, "po_total": 240000.0,
    }, {"price_variance_percent": 5, "quantity_variance_percent": 2})

    assert result.exception_type == ExceptionType.NO_EXCEPTION


def test_the_history_checks_use_the_same_identity_rule_as_the_matcher():
    """These two used to fold vendor names differently, so an invoice naming
    its vendor slightly differently from the one before it failed to match its
    own duplicate. One rule, defined once."""
    from services.history_service import vendor_id_key

    assert vendor_id_key("M/s Chennai Industrial Supplies Private Limited") == \
        vendor_key("Chennai Industrial Supplies Pvt. Ltd.")


# ---------------------------------------------------------------------------
# Cross-case value
# ---------------------------------------------------------------------------
def case(exception_id, exception_type, impact, *, match_score=70, status="assigned"):
    return {
        "exception_id": exception_id,
        "exception_type": exception_type,
        "financial_impact": impact,
        "match_score": match_score,
        "status": status,
        "vendor_name": "Vendor",
        "invoice_amount": impact,
        "created_at": "2026-08-01T00:00:00+00:00",
    }


def test_the_partition_splits_on_what_a_single_case_could_not_see():
    cases = [
        case("A", "price_variance", 25000.0),
        case("B", "quantity_variance", 50400.0),
        case("C", "duplicate_invoice", 97300.0, match_score=100),
        case("D", "po_over_billed", 17000.0, match_score=100),
        case("E", "no_exception", 0.0, match_score=100, status="cleared"),
    ]

    result = cross_case_value(cases, days=365)

    assert result["single_invoice"]["count"] == 2
    assert result["cross_case"]["count"] == 2
    assert result["cross_case"]["value"] == 114300.0
    assert result["exception_count"] == 4, "the clean invoice is a denominator, not an exception"


def test_cross_case_findings_on_a_clean_match_are_called_out_separately():
    """The point of the headline: these invoices passed every comparison their
    own documents supported. A per-invoice system would have paid them."""
    cases = [
        case("C", "duplicate_invoice", 97300.0, match_score=100),
        case("D", "vendor_price_drift", 12000.0, match_score=74),
    ]

    result = cross_case_value(cases, days=365)

    assert result["would_have_cleared"]["count"] == 1
    assert result["would_have_cleared"]["value"] == 97300.0


def test_an_empty_window_does_not_divide_by_zero():
    result = cross_case_value([], days=365)

    assert result["cross_case"]["share_of_exceptions"] == 0
    assert result["headline"].startswith("No cross-case findings")


def test_the_declared_cross_case_set_matches_the_matcher():
    """CROSS_CASE_TYPE_VALUES is what the analytics partition on. If a type is
    in the set but the matcher never marks it cross_case (or the reverse), the
    headline figure silently stops describing what the product does."""
    from services.matching_service import evaluate_exception

    base = {
        "vendor_name": "V", "po_vendor_name": "V",
        "po_number": "PO-1", "invoice_po_number": "PO-1",
        "po_unit_price": 100.0, "invoice_unit_price": 100.0,
        "po_quantity": 10, "received_quantity": 10, "invoice_quantity": 10,
        "invoice_amount": 1000.0, "invoice_total": 1000.0, "po_total": 1000.0,
    }

    produced = {
        "duplicate_invoice": dict(base, duplicate_of=[
            {"confidence": "exact", "reason": "seen before"}]),
        "payment_details_changed": dict(base, payment_detail_changes=[
            {"field": "bank_account_number", "detail": "changed"}]),
        "recurring_suspected": dict(base, duplicate_of=[
            {"confidence": "recurring", "reason": "monthly",
             "pattern": {"cadence": "monthly", "mean_interval_days": 30.0}}]),
        "vendor_price_drift": dict(base, price_drift={
            "first_price": 100.0, "latest_price": 130.0, "span_months": 4.0,
            "increase_percent": 30.0, "detail": "creeping"}),
        # Both sides must state tax for the running total to be comparable:
        # a tax-inclusive total measured against a tax-exclusive order value
        # reports over-billing that is really just the GST. The matcher
        # refuses to judge that case, correctly, so the fixture puts both
        # documents on the same basis rather than working around the guard.
        "po_over_billed": dict(base, tax_amount=180.0, po_tax_amount=180.0, po_billing={
            "po_number": "PO-1", "order_value": 1000.0, "total_billed": 1800.0,
            "previously_billed": 800.0, "this_invoice": 1000.0, "remaining": -800.0,
            "over_billed_by": 800.0, "is_over_billed": True,
            "prior_invoices": [], "invoice_count": 2}),
    }

    for expected_type, matching_input in produced.items():
        result = evaluate_exception(
            matching_input, {"price_variance_percent": 5, "quantity_variance_percent": 2})
        assert result.exception_type.value == expected_type, expected_type
        assert result.cross_case is True, expected_type
        assert expected_type in CROSS_CASE_TYPE_VALUES, expected_type

    assert set(produced) == set(CROSS_CASE_TYPE_VALUES), (
        "every declared cross-case type must be reachable and covered here")


def test_the_portfolio_generator_agrees_with_the_schema():
    """The generator restates the set because it runs standalone. This is the
    assertion that keeps the copy honest."""
    from scripts.generate_synthetic_data import CROSS_CASE_TYPES

    assert CROSS_CASE_TYPES == set(CROSS_CASE_TYPE_VALUES)
