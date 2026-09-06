"""
The two checks added because a duplicate rule that fires on rent is worse
than no duplicate rule, and because a rate that creeps 3% a month clears
every single-invoice check ever written.

RECURRING SUPPRESSION exists for the question an AP reviewer asks within ten
seconds of seeing this product: "does that fire on my monthly retainer?" The
answer has to be no, and it has to be no for a reason stronger than a window —
"same vendor, same amount, within 90 days" describes rent as accurately as it
describes a re-submission. The reason is CADENCE, and these tests pin down
both directions of it: a regular series is demoted, and an irregular one is
still a duplicate.

PRICE DRIFT is cumulative over-billing applied to rate rather than volume. Its
whole claim is that every invoice in the series passed on its own, so the test
that matters most is the negative one: a single high invoice among flat ones
is a price variance on that invoice and must NOT be reported as a trend.
"""
from datetime import datetime, timedelta, timezone

from services import history_service as H
from services.matching_service import evaluate_exception

TOLERANCE = {"price_variance_percent": 5, "quantity_variance_percent": 2}
BASE = datetime(2026, 8, 15, tzinfo=timezone.utc)


def invoice(document_id, *, number, vendor, amount, date, po=None,
            unit_price=None, description=None, exception_id="EXC-OLD"):
    return {
        "document_id": document_id,
        "exception_id": exception_id,
        "document_type": "vendor_invoice",
        "processing_state": "completed",
        "uploaded_at": f"{date}T00:00:00Z",
        "extraction": {
            "invoice_number": number,
            "vendor_name": vendor,
            "total_amount": amount,
            "po_number": po,
            "invoice_date": date,
            "unit_price": unit_price,
            "line_item_description": description,
        },
    }


def monthly_series(count, *, vendor="Meridian Facility Care", amount=88400.0,
                   jitter=(0, 0, 0, 0, 0, 0)):
    """`count` invoices, one a month, most recent last."""
    out = []
    for step in range(count, 0, -1):
        day = BASE - timedelta(days=step * 30 + jitter[step % len(jitter)])
        out.append(invoice(f"D{step}", number=f"MFC-{step:03d}", vendor=vendor,
                           amount=amount, date=day.date().isoformat()))
    return out


# ---------------------------------------------------------------------------
# Recurring billing
# ---------------------------------------------------------------------------
def test_a_monthly_retainer_is_reported_as_recurring_not_duplicate():
    prior = monthly_series(4)
    current = invoice("NOW", number="MFC-005", vendor="Meridian Facility Care",
                      amount=88400.0, date=BASE.date().isoformat())

    found = H.find_duplicate_invoices(current, prior)

    assert found, "the series must still be reported, just not as a duplicate"
    assert {entry["confidence"] for entry in found} == {"recurring"}
    assert found[0]["pattern"]["cadence"] == "monthly"


def test_a_few_days_of_jitter_does_not_break_the_cadence():
    """Real invoices are not raised by a metronome. A check that only tolerates
    exact 30-day gaps would be useless on real data."""
    prior = monthly_series(4, jitter=(0, 3, -2, 1, -3, 2))
    current = invoice("NOW", number="MFC-005", vendor="Meridian Facility Care",
                      amount=88400.0, date=BASE.date().isoformat())

    found = H.find_duplicate_invoices(current, prior)

    assert {entry["confidence"] for entry in found} == {"recurring"}


def test_two_invoices_days_apart_are_still_a_near_duplicate():
    """The suppression must not swallow the case it was built around. Two
    occurrences cannot establish a cadence, so nothing is demoted."""
    prior = [invoice("D1", number="MFC-001", vendor="Meridian Facility Care",
                     amount=88400.0, date="2026-08-09")]
    current = invoice("NOW", number="MFC-002", vendor="Meridian Facility Care",
                      amount=88400.0, date="2026-08-15")

    found = H.find_duplicate_invoices(current, prior)

    assert [entry["confidence"] for entry in found] == ["near"]


def test_an_exact_duplicate_inside_a_recurring_series_is_still_exact():
    """The demotion is keyed on confidence, and an exact match is never
    demoted — otherwise a fraudster who re-sends a rent invoice would be
    handed the suppression as cover."""
    prior = monthly_series(4) + [
        invoice("DUP", number="MFC-005", vendor="Meridian Facility Care",
                amount=88400.0, date=BASE.date().isoformat()),
    ]
    current = invoice("NOW", number="MFC-005", vendor="Meridian Facility Care",
                      amount=88400.0, date=BASE.date().isoformat())

    found = H.find_duplicate_invoices(current, prior)

    assert found[0]["confidence"] == "exact"


def test_an_unparseable_date_never_demotes_a_duplicate():
    """The burden of proof sits entirely on the recurring side: if the dates
    cannot establish a cadence, the finding stands as it was."""
    prior = [
        invoice("D1", number="MFC-001", vendor="Meridian", amount=88400.0, date=None),
        invoice("D2", number="MFC-002", vendor="Meridian", amount=88400.0, date=None),
        invoice("D3", number="MFC-003", vendor="Meridian", amount=88400.0, date=None),
    ]
    current = invoice("NOW", number="MFC-004", vendor="Meridian",
                      amount=88400.0, date=None)

    found = H.find_duplicate_invoices(current, prior)

    assert found, "with no dates there is no window to exclude on either"
    assert all(entry["confidence"] == "near" for entry in found)


def test_recurring_books_no_money_and_low_risk():
    """A portfolio that counted every month's rent as value-at-risk would
    report a headline figure nobody could act on."""
    result = evaluate_exception({
        "vendor_name": "Meridian", "po_vendor_name": "Meridian",
        "po_number": "PO-1", "invoice_po_number": "PO-1",
        "po_unit_price": 100.0, "invoice_unit_price": 100.0,
        "po_quantity": 884, "received_quantity": 884, "invoice_quantity": 884,
        "invoice_amount": 88400.0, "invoice_total": 88400.0, "po_total": 88400.0,
        "duplicate_of": [{
            "confidence": "recurring",
            "reason": "billed monthly",
            "pattern": {"occurrences": 5, "cadence": "monthly", "mean_interval_days": 30.2},
        }],
    }, TOLERANCE)

    assert result.exception_type.value == "recurring_suspected"
    assert result.financial_impact == 0.0
    assert result.risk_level == "low"
    assert result.cross_case is True


# ---------------------------------------------------------------------------
# Price drift
# ---------------------------------------------------------------------------
def rising_series(prices, *, vendor="Trident Electricals", description="LED luminaires"):
    out = []
    for index, price in enumerate(prices):
        day = BASE - timedelta(days=(len(prices) - index) * 30)
        out.append(invoice(f"D{index}", number=f"TE-{index:03d}", vendor=vendor,
                           amount=price * 10, date=day.date().isoformat(),
                           unit_price=price, description=description))
    return out


def test_a_rate_climbing_every_month_is_reported_as_drift():
    prior = rising_series([1000.0, 1030.0, 1061.0, 1093.0])
    current = invoice("NOW", number="TE-005", vendor="Trident Electricals",
                      amount=11260.0, date=BASE.date().isoformat(),
                      unit_price=1126.0, description="LED luminaires")

    drift = H.detect_price_drift(current, prior, tolerance_percent=5)

    assert drift is not None
    assert drift["first_price"] == 1000.0
    assert drift["latest_price"] == 1126.0
    # Each month's step is ~3%, inside the 5% tolerance — which is the finding.
    assert 2.5 < drift["per_month_percent"] < 3.5
    assert drift["increase_percent"] > 5


def test_a_flat_rate_is_not_drift():
    prior = rising_series([1000.0, 1000.0, 1000.0, 1000.0])
    current = invoice("NOW", number="TE-005", vendor="Trident Electricals",
                      amount=10000.0, date=BASE.date().isoformat(),
                      unit_price=1000.0, description="LED luminaires")

    assert H.detect_price_drift(current, prior, tolerance_percent=5) is None


def test_one_high_invoice_among_flat_ones_is_not_drift():
    """This is the negative that matters. A single overcharge is a price
    variance on THAT invoice, which the matcher describes precisely; calling
    it a trend would both misname it and hide which invoice to act on."""
    prior = rising_series([1000.0, 1000.0, 1000.0, 1000.0])
    current = invoice("NOW", number="TE-005", vendor="Trident Electricals",
                      amount=14000.0, date=BASE.date().isoformat(),
                      unit_price=1400.0, description="LED luminaires")

    assert H.detect_price_drift(current, prior, tolerance_percent=5) is None


def test_drift_needs_the_same_item():
    """Bearings and freight drift for different reasons. Comparing across them
    produces a trend that is really a change of product."""
    prior = rising_series([1000.0, 1030.0, 1061.0, 1093.0], description="Freight")
    current = invoice("NOW", number="TE-005", vendor="Trident Electricals",
                      amount=11260.0, date=BASE.date().isoformat(),
                      unit_price=1126.0, description="LED luminaires")

    assert H.detect_price_drift(current, prior, tolerance_percent=5) is None


def test_drift_needs_more_than_three_points():
    prior = rising_series([1000.0, 1060.0])
    current = invoice("NOW", number="TE-003", vendor="Trident Electricals",
                      amount=11240.0, date=BASE.date().isoformat(),
                      unit_price=1124.0, description="LED luminaires")

    assert H.detect_price_drift(current, prior, tolerance_percent=5) is None
