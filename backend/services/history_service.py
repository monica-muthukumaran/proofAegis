"""
history_service.py — the checks a single case cannot perform on itself.

Everything in matching_service.py compares documents that are already in one
case. The most valuable controls in accounts payable are invisible from
there, because they are about what came BEFORE:

  * a duplicate invoice — the same bill submitted twice, which is the single
    most common way money leaks out of an AP function;
  * cumulative over-billing — four invoices that each pass on their own and
    together exceed the order they are billed against;
  * changed payment details — the same vendor, a different bank account,
    which is what payment-diversion fraud looks like from the inside;
  * price drift — a unit price climbing a few percent a month, inside
    tolerance every month and materially above the agreed rate by the fourth;
  * and the counterweight to the first one: recurring billing, so a monthly
    retainer is not reported as a duplicate every month forever.

All of them need one query across every case in the workspace, which is why
they live here rather than in the matcher.

Everything in this module is deterministic. It reads stored extractions and
compares them; no model is consulted, and no number is produced that is not
arithmetic over values read out of a document.

BOUNDARY — payment details. Detecting that a vendor's bank account CHANGED is
exception detection and belongs here. Asserting that the new account is
legitimate would be bank-account verification, which this product explicitly
is not (see the README's "what it is not"). This module raises the question;
a human answers it.
"""
from __future__ import annotations

import re
import statistics
from datetime import datetime, timezone
from typing import Optional

# Two invoices this far apart in value are not the same invoice re-submitted.
_AMOUNT_EPSILON = 0.01
# How close two same-vendor, same-amount invoices must be in time before an
# absent/altered invoice number is treated as a likely re-submission rather
# than as two genuine bills that happen to match.
_NEAR_DUPLICATE_WINDOW_DAYS = 90

# --- Recurring-billing suppression ----------------------------------------
# "Same vendor, same amount, within 90 days" is the rule that finds a genuine
# re-submission. It is also the rule that fires on every rent payment, every
# retainer, every AMC and every subscription in the ledger — an AP clerk sees
# a monthly invoice flagged as a duplicate and stops trusting the tool, and
# duplicate_invoice outranks every other finding, so the false positive is
# loud rather than quiet.
#
# What separates the two is CADENCE. A duplicate is one extra copy of a bill
# that happened once. A retainer is the same amount arriving on a regular
# beat, and the beat itself is the evidence: three or more invoices whose
# gaps cluster tightly around a common period is a billing schedule, not a
# vendor submitting the same invoice three times by accident.
#
# So the check is not "suppress this" — nothing is discarded. The finding is
# re-labelled as `recurring_suspected` and dropped down the severity order,
# which keeps it visible and reviewable while it stops outranking the real
# findings on the same case.
_MIN_RECURRENCE_OCCURRENCES = 3      # this invoice plus two priors
# Coefficient of variation of the intervals: standard deviation over mean. A
# monthly retainer billed on the 1st has gaps of 28-31 days (CV ~0.04); three
# accidental re-submissions have no such regularity. 0.25 allows for invoices
# raised a week late without admitting genuinely irregular billing.
_MAX_INTERVAL_CV = 0.25
# Gaps outside this range are not a billing schedule anyone runs. Below the
# floor, "regular" is indistinguishable from a burst of re-submissions.
_MIN_MEAN_INTERVAL_DAYS = 20
_MAX_MEAN_INTERVAL_DAYS = 400

# Named cadences, for the sentence a reviewer reads. The tolerance on each is
# what a real billing date drifts by when the 1st falls on a weekend.
_KNOWN_CADENCES = (
    ("monthly", 30.4, 6.0),
    ("quarterly", 91.3, 12.0),
    ("half-yearly", 182.6, 18.0),
    ("annual", 365.25, 25.0),
)

# --- Vendor price drift ----------------------------------------------------
# The same insight as cumulative over-billing, applied to price instead of
# volume: an invoice creeping 3% above its order every month is inside a 5%
# tolerance every single month, and materially above the agreed rate by the
# fourth. Each case passes; the trend does not. Only the vendor's history can
# see it, which is why it lives here and not in the matcher.
_MIN_DRIFT_POINTS = 4          # four months before a line is worth fitting
_MIN_DRIFT_TOTAL_PERCENT = 4.0  # cumulative rise that makes it worth reporting
_MIN_DRIFT_PER_MONTH = 0.5      # a flat rate wobbling by rounding is not drift


def normalize_key(value) -> str:
    """Case, spacing and punctuation removed. Used for invoice numbers and PO
    references, which are written inconsistently by the systems that produce
    them but carry no words to canonicalize."""
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def vendor_id_key(value) -> str:
    """The identity key for a COMPANY NAME, shared with the matcher.

    These checks and matching_service used to fold vendor names differently —
    the matcher canonicalized "Pvt. Ltd." against "Private Limited" and this
    module did not. The consequence was not cosmetic: an invoice that named
    its vendor slightly differently from the one before it failed to match its
    own duplicate, so the duplicate went unreported and the case fell through
    to whatever the next check happened to find. The eval harness caught it as
    EVAL-07234, a duplicate reported as cumulative over-billing.

    There is now one rule, defined once, imported here.
    """
    from services.matching_service import vendor_key

    return vendor_key(value)


def _amount(extraction: dict) -> Optional[float]:
    value = extraction.get("total_amount")
    return None if value is None else float(value)


def _parse_date(value) -> Optional[datetime]:
    """Best-effort date parse across the formats these documents use.

    Returns None rather than a guess: an unparseable date must not silently
    become "today" and make two unrelated invoices look days apart.
    """
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%b-%y", "%d-%b-%Y", "%d/%m/%Y", "%d/%m/%y",
                "%d.%m.%Y", "%d-%m-%Y", "%Y/%m/%d", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Recurring billing — the reason "same vendor, same amount" is not enough
# ---------------------------------------------------------------------------
def _describe_cadence(mean_days: float) -> Optional[str]:
    """The everyday name for an interval, or None when it has no common name."""
    for name, period, tolerance in _KNOWN_CADENCES:
        if abs(mean_days - period) <= tolerance:
            return name
    return None


def detect_recurring_pattern(this_date: Optional[datetime],
                             prior_dates: list[Optional[datetime]]) -> Optional[dict]:
    """
    Whether a set of same-vendor, same-amount invoice dates forms a schedule.

    Returns None — meaning "no evidence of a schedule, treat as before" —
    whenever the dates cannot support the claim: too few of them, unparseable
    dates, gaps too irregular, or a mean interval no billing cycle uses. That
    default matters. A missing date must never cause a genuine duplicate to be
    demoted, so the burden of proof sits entirely on the recurring side.
    """
    dates = sorted(d for d in ([this_date] + list(prior_dates)) if d is not None)
    if len(dates) < _MIN_RECURRENCE_OCCURRENCES:
        return None

    intervals = [(later - earlier).days for earlier, later in zip(dates, dates[1:])]
    intervals = [gap for gap in intervals if gap > 0]
    if len(intervals) < _MIN_RECURRENCE_OCCURRENCES - 1:
        return None

    mean_interval = statistics.fmean(intervals)
    if not (_MIN_MEAN_INTERVAL_DAYS <= mean_interval <= _MAX_MEAN_INTERVAL_DAYS):
        return None

    # One interval gives a standard deviation of zero by definition, which
    # would make any two-gap sequence look perfectly regular. Requiring three
    # occurrences above means there are at least two gaps here.
    deviation = statistics.pstdev(intervals)
    cv = deviation / mean_interval if mean_interval else 1.0
    if cv > _MAX_INTERVAL_CV:
        return None

    cadence = _describe_cadence(mean_interval)
    return {
        "occurrences": len(dates),
        "mean_interval_days": round(mean_interval, 1),
        "interval_variation": round(cv, 3),
        "cadence": cadence,
        "first_seen": dates[0].date().isoformat(),
        "last_seen": dates[-1].date().isoformat(),
    }


# ---------------------------------------------------------------------------
# Duplicate invoices
# ---------------------------------------------------------------------------
def find_duplicate_invoices(invoice: dict, prior_invoices: list[dict]) -> list[dict]:
    """
    Earlier invoices that look like this one already submitted.

    Three tiers, because a duplicate does not always announce itself and
    because the obvious rule for the second tier is also the rule that fires
    on every retainer in the ledger:

      exact       same vendor and same invoice number. Near-certain, and the
                  only tier that needs no amount agreement — a re-issued
                  invoice under the same number for a different amount is
                  still the same invoice.
      near        same vendor and same amount, no matching number, within
                  90 days. This is how a duplicate arrives when a vendor
                  re-submits under a fresh number, and it is why matching on
                  invoice number alone is not enough.
      recurring   the same vendor and amount arriving on a regular beat —
                  three or more of them at a consistent interval. Rent, an
                  AMC, a retainer, a subscription. Reported, because a
                  duplicate can hide inside a recurring series, but at lower
                  severity and no longer outranking the rest of the case.

    Returns one entry per prior invoice matched, strongest first, each naming
    the document and case it was found in so a reviewer can open it.
    """
    extraction = invoice.get("extraction") or {}
    vendor = vendor_id_key(extraction.get("vendor_name"))
    number = normalize_key(extraction.get("invoice_number"))
    amount = _amount(extraction)
    date = _parse_date(extraction.get("invoice_date"))

    # An unidentifiable vendor cannot be matched against anything without
    # producing noise, so no claim is made.
    if not vendor or vendor == normalize_key("UNKNOWN"):
        return []

    exact, near = [], []
    # Dates of every prior invoice from this vendor for this exact amount.
    # The cadence test needs the whole series, not just the pairs that landed
    # inside the near-duplicate window.
    same_amount_dates: list[Optional[datetime]] = []
    for prior in prior_invoices:
        prior_extraction = prior.get("extraction") or {}
        if vendor_id_key(prior_extraction.get("vendor_name")) != vendor:
            continue

        prior_number = normalize_key(prior_extraction.get("invoice_number"))
        prior_amount = _amount(prior_extraction)

        if number and prior_number and number == prior_number:
            exact.append({
                "confidence": "exact",
                "reason": (
                    f"Invoice {extraction.get('invoice_number')} from "
                    f"{extraction.get('vendor_name')} was already recorded."
                ),
                "document_id": prior.get("document_id"),
                "exception_id": prior.get("exception_id"),
                "invoice_number": prior_extraction.get("invoice_number"),
                "amount": prior_amount,
            })
            continue

        if amount is None or prior_amount is None:
            continue
        if abs(amount - prior_amount) > _AMOUNT_EPSILON:
            continue

        prior_date = _parse_date(prior_extraction.get("invoice_date"))
        # Every same-vendor, same-amount invoice is kept for the cadence test
        # below, including ones outside the 90-day window — a monthly series
        # is only visible across several months, so the window that decides
        # whether a PAIR is suspicious would hide the pattern that proves it
        # is not.
        same_amount_dates.append(prior_date)

        # Same vendor and same amount but a DIFFERENT stated number is only
        # suspicious when the two are close in time; a monthly retainer bills
        # the same amount every month and is not a duplicate.
        if number and prior_number and number != prior_number:
            if date and prior_date:
                if abs((date - prior_date).days) > _NEAR_DUPLICATE_WINDOW_DAYS:
                    continue
        near.append({
            "confidence": "near",
            "reason": (
                f"{extraction.get('vendor_name')} already billed "
                f"{prior_amount:,.2f} on invoice {prior_extraction.get('invoice_number') or 'an earlier document'}."
            ),
            "document_id": prior.get("document_id"),
            "exception_id": prior.get("exception_id"),
            "invoice_number": prior_extraction.get("invoice_number"),
            "amount": prior_amount,
        })

    # An EXACT match is never demoted. The same vendor billing the same
    # invoice number twice is not a billing schedule under any reading, and a
    # fraudster who re-sends a rent invoice would otherwise be handed the
    # suppression as cover.
    if not exact and near:
        pattern = detect_recurring_pattern(date, same_amount_dates)
        if pattern is not None:
            return [_as_recurring(entry, pattern, extraction) for entry in near]

    return exact + near


def _as_recurring(entry: dict, pattern: dict, extraction: dict) -> dict:
    """Re-labels a near-duplicate as a recognised billing schedule.

    The entry keeps its document and case references: the point is that a
    reviewer can still open every invoice in the series and check it, not that
    the series is waved through.
    """
    cadence = pattern.get("cadence")
    beat = (f"on a {cadence} cycle" if cadence
            else f"about every {pattern['mean_interval_days']:.0f} days")
    return dict(
        entry,
        confidence="recurring",
        pattern=pattern,
        reason=(
            f"{extraction.get('vendor_name')} has billed this same amount "
            f"{pattern['occurrences']} times {beat} since {pattern['first_seen']}. "
            f"That is a billing schedule rather than a re-submission — but a duplicate "
            f"can hide inside one, so confirm this month's invoice is not a second copy."
        ),
    )


# ---------------------------------------------------------------------------
# Cumulative billing against one purchase order
# ---------------------------------------------------------------------------
def cumulative_billing(po_number, po_total, this_invoice: dict,
                       prior_invoices: list[dict]) -> Optional[dict]:
    """
    Everything billed against one purchase order, including this invoice.

    A vendor may legitimately bill an order in instalments. Each instalment
    passes every check in matching_service.py, because each is compared with
    the order in isolation — so ₹40,000 and ₹30,000 against a ₹53,000 order
    are individually fine and jointly ₹17,000 too much. Only the running
    total can see it.

    Returns None when there is no order value to measure against; otherwise a
    record of what has been billed, what remains, and whether the order is
    over-billed.
    """
    if not po_number or po_total in (None, 0):
        return None

    target = normalize_key(po_number)
    this_extraction = this_invoice.get("extraction") or {}
    this_amount = _amount(this_extraction) or 0.0

    prior_billed = []
    for prior in prior_invoices:
        prior_extraction = prior.get("extraction") or {}
        if normalize_key(prior_extraction.get("po_number")) != target:
            continue
        amount = _amount(prior_extraction)
        if amount is None:
            continue
        prior_billed.append({
            "document_id": prior.get("document_id"),
            "exception_id": prior.get("exception_id"),
            "invoice_number": prior_extraction.get("invoice_number"),
            "amount": amount,
        })

    previously = round(sum(entry["amount"] for entry in prior_billed), 2)
    total_billed = round(previously + this_amount, 2)
    order_value = float(po_total)
    remaining = round(order_value - total_billed, 2)

    return {
        "po_number": po_number,
        "order_value": order_value,
        "previously_billed": previously,
        "this_invoice": round(this_amount, 2),
        "total_billed": total_billed,
        "remaining": remaining,
        "over_billed_by": round(-remaining, 2) if remaining < 0 else 0.0,
        "is_over_billed": remaining < -_AMOUNT_EPSILON,
        "prior_invoices": prior_billed,
        "invoice_count": len(prior_billed) + 1,
    }


# ---------------------------------------------------------------------------
# Changed payment details
# ---------------------------------------------------------------------------
def find_payment_detail_changes(invoice: dict, prior_invoices: list[dict]) -> list[dict]:
    """
    The same vendor, previously paid to a different account.

    This is what payment-diversion fraud looks like from the inside: a
    genuine-looking invoice from a known supplier whose bank details have
    quietly changed. It is also what a legitimate bank change looks like,
    which is exactly why this reports rather than concludes.

    Only the MOST RECENT prior invoice carrying details is compared, so a
    vendor that changed banks once does not generate a finding on every
    invoice thereafter.
    """
    extraction = invoice.get("extraction") or {}
    vendor = vendor_id_key(extraction.get("vendor_name"))
    if not vendor:
        return []

    current = {field: extraction.get(field)
               for field in ("bank_account_number", "bank_ifsc", "bank_name")
               if extraction.get(field)}
    if not current:
        return []

    candidates = []
    for prior in prior_invoices:
        prior_extraction = prior.get("extraction") or {}
        if vendor_id_key(prior_extraction.get("vendor_name")) != vendor:
            continue
        if not any(prior_extraction.get(field) for field in current):
            continue
        candidates.append(prior)
    if not candidates:
        return []

    latest = max(candidates, key=lambda d: d.get("uploaded_at", ""))
    latest_extraction = latest.get("extraction") or {}

    changes = []
    for field, value in current.items():
        previous = latest_extraction.get(field)
        if not previous:
            continue
        if normalize_key(previous) == normalize_key(value):
            continue
        changes.append({
            "field": field,
            "previous_value": previous,
            "current_value": value,
            "previous_document_id": latest.get("document_id"),
            "previous_exception_id": latest.get("exception_id"),
            "detail": (
                f"{extraction.get('vendor_name')} was previously paid to "
                f"{field.replace('bank_', '').replace('_', ' ')} {previous}; this invoice "
                f"states {value}. Confirm the change with the vendor through a channel "
                f"you already trust — not a phone number or address taken from this invoice."
            ),
        })
    return changes


# ---------------------------------------------------------------------------
# Vendor price drift
# ---------------------------------------------------------------------------
def _unit_price_of(extraction: dict) -> Optional[float]:
    """The invoice's unit price, from the scalar field or a single line.

    A multi-line invoice has no one unit price, and averaging its lines would
    invent a number that appears on no document. Those are skipped: drift is
    reported only where there is a real per-unit figure to trend.
    """
    price = extraction.get("unit_price")
    if price is not None:
        return float(price)
    lines = extraction.get("line_items") or []
    if len(lines) == 1 and (lines[0] or {}).get("unit_price") is not None:
        return float(lines[0]["unit_price"])
    return None


def detect_price_drift(invoice: dict, prior_invoices: list[dict],
                       tolerance_percent: float) -> Optional[dict]:
    """
    A unit price climbing steadily across a vendor's invoices.

    This is cumulative over-billing applied to rate rather than volume. Every
    month's invoice sits inside the price tolerance when measured against its
    own order, so every month clears; the fourth invoice is materially above
    the rate that was agreed, and nothing in a per-invoice check ever says so.

    The trend is an ordinary least-squares fit over (months elapsed, unit
    price) — plain arithmetic, no model. It is reported only when the fit
    rises consistently AND the cumulative rise has cleared the tolerance the
    workspace applies to a single invoice, so a rate wobbling by rounding
    never produces a finding.

    Returns None when there is nothing to fit or the trend is flat.
    """
    extraction = invoice.get("extraction") or {}
    vendor = vendor_id_key(extraction.get("vendor_name"))
    description = _line_description(extraction)
    if not vendor:
        return None

    points: list[tuple[datetime, float, dict]] = []
    for record in list(prior_invoices) + [invoice]:
        record_extraction = record.get("extraction") or {}
        if vendor_id_key(record_extraction.get("vendor_name")) != vendor:
            continue
        # Different goods drift for different reasons. Comparing the price of
        # bearings against the price of freight would produce a "trend" that
        # is really a change of product.
        if description and _line_description(record_extraction) != description:
            continue
        price = _unit_price_of(record_extraction)
        date = _parse_date(record_extraction.get("invoice_date"))
        if price is None or price <= 0 or date is None:
            continue
        points.append((date, price, record))

    points.sort(key=lambda p: p[0])
    if len(points) < _MIN_DRIFT_POINTS:
        return None

    baseline_date = points[0][0]
    months = [(date - baseline_date).days / 30.44 for date, _, _ in points]
    prices = [price for _, price, _ in points]
    span_months = months[-1]
    if span_months <= 0:
        return None

    mean_month = statistics.fmean(months)
    mean_price = statistics.fmean(prices)
    variance = sum((m - mean_month) ** 2 for m in months)
    if variance == 0:
        return None
    slope = sum((m - mean_month) * (p - mean_price) for m, p in zip(months, prices)) / variance
    if slope <= 0:
        return None

    baseline_price = prices[0]
    per_month_percent = slope / baseline_price * 100
    total_percent = (prices[-1] - baseline_price) / baseline_price * 100

    if per_month_percent < _MIN_DRIFT_PER_MONTH:
        return None
    if total_percent < max(_MIN_DRIFT_TOTAL_PERCENT, float(tolerance_percent)):
        return None
    # Every step must be a rise or a hold. A rate that went up and came back
    # down is a renegotiation, not a drift.
    steps = list(zip(prices, prices[1:]))
    if any(later < earlier - _AMOUNT_EPSILON for earlier, later in steps):
        return None

    # And the rise has to be DISTRIBUTED. "Never decreases" is satisfied by
    # four identical invoices followed by one 40% higher, and calling that a
    # trend both misnames it and hides which invoice to act on — it is a price
    # variance on the last one, which the matcher already reports precisely
    # and with the right amount attached.
    #
    # Drift means most months moved. Requiring a majority of the steps to be
    # genuine rises separates a creeping rate from a single jump without
    # needing a goodness-of-fit statistic nobody reading this file would be
    # able to check by eye.
    rising_steps = sum(1 for earlier, later in steps if later > earlier + _AMOUNT_EPSILON)
    if rising_steps * 2 <= len(steps):
        return None

    return {
        "vendor_name": extraction.get("vendor_name"),
        "description": description,
        "invoice_count": len(points),
        "span_months": round(span_months, 1),
        "first_price": round(baseline_price, 2),
        "latest_price": round(prices[-1], 2),
        "increase_percent": round(total_percent, 2),
        "per_month_percent": round(per_month_percent, 2),
        "tolerance_percent": float(tolerance_percent),
        "history": [
            {
                "invoice_number": (record.get("extraction") or {}).get("invoice_number"),
                "exception_id": record.get("exception_id"),
                "document_id": record.get("document_id"),
                "invoice_date": (record.get("extraction") or {}).get("invoice_date"),
                "unit_price": round(price, 2),
            }
            for date, price, record in points
        ],
        "detail": (
            f"{extraction.get('vendor_name')} has raised the unit price on "
            f"{description or 'this item'} from {baseline_price:,.2f} to {prices[-1]:,.2f} "
            f"across {len(points)} invoices over {span_months:.0f} months — "
            f"{total_percent:.1f}% in total, about {per_month_percent:.1f}% a month. "
            f"Each individual rise stayed inside the {float(tolerance_percent):g}% tolerance, "
            f"so every one of those invoices cleared on its own."
        ),
    }


def _line_description(extraction: dict) -> Optional[str]:
    """The normalized item description, when the document has exactly one."""
    described = extraction.get("line_item_description")
    if not described:
        lines = extraction.get("line_items") or []
        described = (lines[0] or {}).get("description") if len(lines) == 1 else None
    return normalize_key(described) or None
