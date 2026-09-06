"""
Risk on an invoice whose only open item is confirmation of delivery.

The original branch returned the literal string "high" before looking at
anything else, so a fully-reconciled invoice showed "Match score 100%" beside
"Risk level high" with nothing on screen explaining how both could be true.
"""
import pytest

from services.matching_service import (
    classify_procurement_kind,
    evaluate_exception,
    risk_for_unconfirmed,
)
from schemas import Comparison, ComparisonField, MatchClassification

TOLERANCE = {"price_variance_percent": 5, "quantity_variance_percent": 2}


def _case(amount, line_items, **overrides):
    case = {
        "vendor_name": "SIGMA", "po_vendor_name": "SIGMA",
        "po_number": "PO/1", "invoice_po_number": "PO/1",
        "purchase_order_exists": True, "goods_receipt_exists": False,
        "received_quantity": None, "invoice_quantity": None,
        "invoice_unit_price": None, "po_unit_price": None,
        "invoice_amount": amount, "invoice_total": amount, "po_total": amount,
        "invoice_line_items": line_items, "po_line_items": line_items,
    }
    case.update(overrides)
    return case


SERVICE_LINES = [
    {"description": "Water tank & Plumbing Pipeline work", "quantity": 1,
     "unit_price": 16000, "amount": 16000, "hsn_sac": "995478"},
    {"description": "Modular toilet reconditioning", "quantity": 1,
     "unit_price": 22000, "amount": 22000, "hsn_sac": "995478"},
    {"description": "EWC Toilet", "quantity": 1,
     "unit_price": 15000, "amount": 15000, "hsn_sac": "996519"},
]

GOODS_LINES = [
    {"description": "Down Light 8W 6000K", "quantity": 55,
     "unit_price": 675, "amount": 37125, "hsn_sac": "940540"},
]


# --- goods vs services ----------------------------------------------------
def test_sac_codes_identify_a_services_order():
    """SAC codes begin with 99 — a fact printed on the invoice, not a guess."""
    assert classify_procurement_kind(SERVICE_LINES) == "services"


def test_hsn_codes_identify_a_goods_order():
    assert classify_procurement_kind(GOODS_LINES) == "goods"


def test_wording_is_used_when_no_code_is_present():
    lines = [{"description": "Providing and fixing water tank, all labour included"},
             {"description": "Modular toilet reconditioning work"}]
    assert classify_procurement_kind(lines) == "services"


def test_one_service_line_does_not_reclassify_a_hardware_order():
    lines = [
        {"description": "Down Light 8W", "hsn_sac": "940540"},
        {"description": "Ceiling fan", "hsn_sac": "941460"},
        {"description": "Installation charges"},
    ]
    assert classify_procurement_kind(lines) == "goods"


def test_no_line_items_defaults_to_goods():
    assert classify_procurement_kind([]) == "goods"


def test_a_services_case_awaits_service_confirmation_not_a_goods_receipt():
    result = evaluate_exception(_case(62540.0, SERVICE_LINES), TOLERANCE)

    assert result.procurement_kind == "services"
    assert result.awaiting_document == "service confirmation"
    assert "service confirmation" in result.financial_impact_basis
    # The classification itself is unchanged — analytics keep one bucket.
    assert result.exception_type.value == "missing_goods_receipt"


def test_a_goods_case_still_awaits_a_goods_receipt():
    result = evaluate_exception(_case(37125.0, GOODS_LINES), TOLERANCE)
    assert result.awaiting_document == "goods receipt"


# --- proportionate risk ---------------------------------------------------
def _breach():
    return Comparison(field=ComparisonField.UNIT_PRICE, expected_value=1, actual_value=2,
                      classification=MatchClassification.OUTSIDE_TOLERANCE, evaluable=True)


def _agreement():
    return Comparison(field=ComparisonField.TOTAL, expected_value=1, actual_value=1,
                      classification=MatchClassification.MATCHED, evaluable=True)


@pytest.mark.parametrize("amount,expected", [
    (5000.0, "low"),
    (30000.0, "medium"),
    (150000.0, "high"),
])
def test_risk_scales_with_the_amount_when_everything_else_agrees(amount, expected):
    assert risk_for_unconfirmed(amount, [_agreement()], 100000.0) == expected


def test_a_failed_comparison_is_high_risk_at_any_amount():
    """Unconfirmed AND disagreeing is the worst case, not a small one."""
    assert risk_for_unconfirmed(100.0, [_agreement(), _breach()], 100000.0) == "high"


def test_a_fully_matched_mid_value_invoice_is_no_longer_automatically_high():
    result = evaluate_exception(_case(62540.0, SERVICE_LINES), TOLERANCE)

    assert result.match_score == 100
    assert result.risk_level == "medium"
    assert result.financial_impact == 62540.0


def test_the_threshold_is_configurable_per_workspace():
    tolerance = dict(TOLERANCE, high_value_threshold=50000.0)
    result = evaluate_exception(_case(62540.0, SERVICE_LINES), tolerance)
    assert result.risk_level == "high"


# --- the explanation ------------------------------------------------------
def test_the_result_explains_what_is_settled_and_what_is_outstanding():
    result = evaluate_exception(_case(62540.0, SERVICE_LINES), TOLERANCE)

    assert result.outstanding
    assert "3 of 3 ordered lines" in result.outstanding
    assert "service confirmation" in result.outstanding
    assert "62,540" in result.outstanding
