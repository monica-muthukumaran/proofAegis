"""
The awkward inputs, and the two defaults that made a workflow impossible.

Every test here failed before the fix that accompanies it, and every one of
them passed straight through a 232-test suite beforehand — which is the point.
The cases are the ones no fixture happened to contain: a zero where a divisor
was expected, a fractional age between two labelled bands, and an approval
policy nobody had configured.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from flask import Flask, jsonify

from services import analytics_service, approval_service
from services.matching_service import evaluate_exception

TOLERANCE = {"price_variance_percent": 5, "quantity_variance_percent": 2}

BASE_CASE = {
    "vendor_name": "Acme Ltd", "po_vendor_name": "Acme Ltd",
    "po_number": "PO-1", "invoice_po_number": "PO-1",
    "purchase_order_exists": True, "goods_receipt_exists": True,
    "po_unit_price": 100.0, "invoice_unit_price": 100.0, "po_quantity": 10,
}


def case(**overrides) -> dict:
    return {**BASE_CASE, **overrides}


# --- a zero where a divisor was expected ----------------------------------
def test_an_invoice_billing_zero_units_does_not_crash_the_matcher():
    """The impact formula divided the invoice amount by the billed quantity.
    An invoice stating zero units raised ZeroDivisionError, which the route
    layer turned into a 500 for the whole case rather than a finding."""
    result = evaluate_exception(
        case(received_quantity=5, invoice_quantity=0, invoice_amount=0.0,
             invoice_total=0.0, po_total=500.0),
        TOLERANCE,
    )
    assert result.exception_type.value == "quantity_variance"
    assert result.financial_impact == 0.0


def test_an_invoice_below_its_goods_receipt_puts_no_money_at_risk():
    """Billing fewer units than were delivered produced a NEGATIVE impact, so
    one under-billed invoice cancelled out a genuine overcharge in every
    portfolio total that sums this field."""
    result = evaluate_exception(
        case(received_quantity=10, invoice_quantity=8, invoice_amount=800.0,
             invoice_total=800.0, po_total=1000.0),
        TOLERANCE,
    )
    assert result.exception_type.value == "quantity_variance"
    assert result.financial_impact == 0.0
    assert "below the goods receipt" in result.financial_impact_basis


def test_over_billing_still_carries_the_unreceived_units():
    """The guard above must not blunt the finding it sits next to."""
    result = evaluate_exception(
        case(received_quantity=8, invoice_quantity=10, invoice_amount=1000.0,
             invoice_total=1000.0, po_total=800.0),
        TOLERANCE,
    )
    assert result.exception_type.value == "quantity_variance"
    assert result.financial_impact == 200.0


def test_a_negative_quantity_never_becomes_a_negative_amount_at_risk():
    """_to_number accepts a leading minus, so a hyphen sitting beside a
    quantity on a real layout parses as one. Multiplying a positive per-unit
    variance by it produced a negative exposure that then SUBTRACTED from
    every portfolio total summing this field."""
    result = evaluate_exception(
        case(po_unit_price=100.0, invoice_unit_price=130.0, received_quantity=-5,
             invoice_quantity=-5, invoice_amount=650.0, invoice_total=650.0,
             po_total=500.0),
        TOLERANCE,
    )
    assert result.financial_impact >= 0


def test_a_negative_line_quantity_cannot_credit_away_another_lines_overcharge():
    result = evaluate_exception(
        case(po_unit_price=None, invoice_unit_price=None, received_quantity=None,
             invoice_quantity=None, invoice_amount=1000.0, invoice_total=1000.0,
             po_total=500.0,
             po_line_items=[{"description": "bolts", "unit_price": 10.0, "quantity": 5},
                            {"description": "nuts", "unit_price": 10.0, "quantity": 5}],
             invoice_line_items=[{"description": "bolts", "unit_price": 90.0, "quantity": -5},
                                 {"description": "nuts", "unit_price": 20.0, "quantity": 5}]),
        TOLERANCE,
    )
    assert result.financial_impact >= 0


def test_a_stored_billing_record_missing_its_order_value_is_not_a_500():
    """cumulative_billing never writes the key empty, but a case record from an
    older version can — and the over-billing branch formats it into two
    sentences, so a missing value raised TypeError out of an f-string."""
    result = evaluate_exception(
        case(received_quantity=5, invoice_quantity=5, invoice_amount=500.0,
             invoice_total=500.0, po_total=500.0,
             po_billing={"po_number": "PO-1", "order_value": None, "total_billed": 900.0,
                         "is_over_billed": True, "invoice_count": 2}),
        TOLERANCE,
    )
    assert result.exception_type.value


# --- a percentage measured against zero -----------------------------------
def test_a_zero_expected_value_reports_no_percentage_rather_than_infinity():
    """float("inf") classified correctly and then serialized as a bare
    `Infinity`, which is not valid JSON."""
    result = evaluate_exception(
        case(po_unit_price=0.0, invoice_unit_price=100.0, received_quantity=5,
             invoice_quantity=5, invoice_amount=500.0, invoice_total=500.0,
             po_total=0.0),
        TOLERANCE,
    )
    price = next(c for c in result.comparisons if c.field.value == "unit_price")
    assert price.classification.value == "outside_tolerance"
    assert price.percentage_variance is None
    assert price.absolute_variance == 100.0


def test_the_match_result_is_always_strictly_valid_json():
    """A non-finite float anywhere in the response failed the browser's parse
    of the WHOLE body, so one zero on a purchase order emptied the entire
    match workspace rather than one cell of it."""
    result = evaluate_exception(
        case(po_unit_price=0.0, invoice_unit_price=100.0, received_quantity=0,
             invoice_quantity=5, invoice_amount=500.0, invoice_total=500.0,
             po_total=0.0, invoice_subtotal=500.0, po_subtotal=0.0),
        TOLERANCE,
    )
    with Flask(__name__).test_request_context():
        body = jsonify(result.model_dump()).get_data(as_text=True)

    def reject(constant):
        raise AssertionError(f"non-finite value {constant} in the response body")

    json.loads(body, parse_constant=reject)


# --- an approval policy nobody configured ---------------------------------
def test_an_unconfigured_workspace_can_still_resolve_its_own_cases():
    """Segregation of duties defaulted to ON for a workspace with no policy,
    no roles and — in the demo and single-user cases — no second person. Every
    case is prepared by whoever is signed in, so `resolved`, `closed` and
    `approved_with_exception` answered 403 forever."""
    prepared_by_the_only_user = {"exception_id": "EXC-1", "created_by": "solo@example.com"}
    for status in ("resolved", "closed", "approved_with_exception"):
        approval_service.check_approval(
            status, actor="solo@example.com", actor_role=None,
            case=prepared_by_the_only_user,
            documents=[{"document_id": "D1", "uploaded_by": "solo@example.com"}],
            amount=250000.0, policy={},
        )


def test_configuring_any_policy_turns_segregation_of_duties_back_on():
    """The control is unchanged wherever a workspace has one: a policy that
    sets only approval bands still gets the second pair of eyes."""
    with pytest.raises(approval_service.ApprovalDenied) as raised:
        approval_service.check_approval(
            "approved_with_exception", actor="clerk@example.com", actor_role="controller",
            case={"exception_id": "EXC-1", "created_by": "clerk@example.com"},
            documents=[], amount=1000.0,
            policy={"limits": [{"role": "controller", "max_value": None}]},
        )
    assert raised.value.code == "segregation_of_duties"


# --- an age between two labelled bands ------------------------------------
def _open_case(age_days: float, index: int) -> dict:
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    return {
        "exception_id": f"EXC-{index}", "exception_type": "price_variance",
        "status": "assigned", "created_at": created.isoformat(),
        "financial_impact": 1000.0,
    }


@pytest.mark.parametrize("age", [3.5, 7.5, 14.5, 30.5])
def test_an_age_between_two_bands_still_lands_in_one(age):
    """The bands are labelled in whole days ("4-7 days") but were matched
    against a fractional age, so 3.5 days open matched none of them. Four days
    in every thirty-one fell into a gap."""
    report = analytics_service.ageing([_open_case(age, 0)], days=None)
    assert report["open_exceptions"] == 1
    assert sum(b["count"] for b in report["buckets"]) == 1


def test_the_ageing_buckets_account_for_every_open_case():
    ages = [0.4, 1.0, 3.5, 5.0, 7.5, 10.0, 14.5, 20.0, 30.5, 40.0]
    cases = [_open_case(age, i) for i, age in enumerate(ages)]
    report = analytics_service.ageing(cases, days=None)

    assert report["open_exceptions"] == len(ages)
    assert sum(b["count"] for b in report["buckets"]) == len(ages)
    assert sum(b["value_at_risk"] for b in report["buckets"]) == 1000.0 * len(ages)
