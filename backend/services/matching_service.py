"""
matching_service.py — FR-005 (matching), FR-006 (tolerance evaluation),
FR-007 (exception classification).

Everything here is plain arithmetic and comparisons. No Gemini call, no ADK
agent, nothing that could hallucinate a number that ends up in a financial
document. This is deliberate per Document 1's product boundary: "Calculates
the financial impact using deterministic code."

Formulas (from FR-006 / FR-005, verbatim):

    absolute_variance   = actual_value - expected_value
    percentage_variance = absolute_variance / expected_value * 100
    match_score = round(100 * matched_count / evaluable_count)

`evaluable_count` only counts comparisons where both source values existed —
a comparison is never penalized because a document is legitimately missing
(that's its own exception type, e.g. missing_goods_receipt).
"""
from __future__ import annotations

import re
from typing import Optional

from schemas import (
    Comparison,
    ComparisonField,
    ExceptionType,
    LineComparison,
    MatchClassification,
    MatchResult,
)
from services import coherence_service

# Comparisons that read a field off ONE document and a field off ANOTHER.
# When the documents turn out to describe different transactions these are the
# rows whose numbers are meaningless, so they are demoted rather than reported
# as variances — see _demote_cross_document_comparisons.
_CROSS_DOCUMENT_FIELDS = {
    # Vendor and PO number are on this list, and they are the two that look
    # like they should not be. Both are genuine facts about the pair of
    # documents, and both stay VISIBLE — demotion keeps the values and
    # withdraws only the verdict. But once the documents are known to describe
    # different orders, "the vendor matched" means the wrong purchase order
    # happened to come from the same supplier, and counting that as agreement
    # produced a 100% match score on a case whose headline was that nothing
    # could be compared. With them demoted nothing is evaluable and the score
    # is 0 — the same answer MISSING_PURCHASE_ORDER already gives for the same
    # reason, an invoice with no valid counterpart to check against.
    ComparisonField.VENDOR,
    ComparisonField.PO_NUMBER,
    ComparisonField.UNIT_PRICE,
    ComparisonField.QUANTITY,
    ComparisonField.LINE_ITEMS,
    ComparisonField.SUBTOTAL,
    ComparisonField.TAX,
    ComparisonField.TOTAL,
    ComparisonField.QUOTED_PRICE,
    ComparisonField.PO_BILLED_TOTAL,
}

# Above this invoice value an unconfirmed delivery is high risk on size alone.
# Overridable per workspace through the tolerance record's
# `high_value_threshold`, so it is a policy setting rather than a constant
# buried in the matcher.
DEFAULT_HIGH_VALUE_THRESHOLD = 100000.0

MATCHED_CLASSIFICATIONS = {
    MatchClassification.MATCHED,
    MatchClassification.WITHIN_TOLERANCE,
}


def compute_variance(actual: float, expected: float) -> tuple[float, Optional[float]]:
    """Returns (absolute_variance, percentage_variance) per FR-006's formula.

    A percentage against a zero expected value is not a number, and it is
    reported as absent rather than as a sentinel. It used to be float("inf"),
    which classified correctly and then serialized into the API response as a
    bare `Infinity` — not valid JSON. The browser's parse of the WHOLE match
    result failed on it, so a single zero on a purchase order emptied the
    entire match workspace rather than one cell of it.

    The absolute variance carries the meaning instead, exactly as
    trust_ledger.compare already does for a difference measured against zero.
    """
    absolute_variance = actual - expected
    if expected == 0:
        return absolute_variance, (0.0 if absolute_variance == 0 else None)
    return absolute_variance, (absolute_variance / expected) * 100


def classify_by_tolerance(percentage_variance: Optional[float],
                          tolerance_percent: float) -> MatchClassification:
    # An absent percentage means the expected value was zero and the actual
    # was not. There is no tolerance band around zero, so any difference from
    # it is outside tolerance.
    if percentage_variance is None:
        return MatchClassification.OUTSIDE_TOLERANCE
    if abs(percentage_variance) == 0:
        return MatchClassification.MATCHED
    if abs(percentage_variance) <= tolerance_percent:
        return MatchClassification.WITHIN_TOLERANCE
    return MatchClassification.OUTSIDE_TOLERANCE


# --- Vendor identity ------------------------------------------------------
# One company, written by two systems. The purchase order says "Chennai
# Industrial Supplies Pvt. Ltd."; the invoice its billing software generates
# says "M/s Chennai Industrial Supplies Private Limited". These are the same
# supplier, and a comparison that lowercases and nothing else calls it a
# vendor mismatch — the single most common reason a real three-way match
# fails for no good reason.
#
# The eval harness measured it: 21 of 21 spelling-variant fixtures were
# reported as vendor_mismatch, which took detection precision from 1.00 to
# 0.87 on its own. See eval/run_eval.py.
#
# What is folded away is deliberately narrow — legal form, honorific, and
# punctuation. Two suppliers whose names differ ONLY by whether one is a
# "Limited" and the other a "Ltd." are the same supplier; anything that
# differs in an actual word still compares as different, so a genuine
# mismatch is still caught. The eval's vendor_mismatch fixtures, which swap in
# an entirely different company, continue to be reported.
_LEGAL_FORMS = {
    "private": "pvt", "limited": "ltd", "company": "co", "corporation": "corp",
    "incorporated": "inc", "and": "&",
}
# Written before the name rather than part of it. Common on Indian invoices.
_NAME_PREFIXES = ("m/s", "m/s.", "messrs", "messrs.")


def vendor_key(value) -> str:
    """A comparable identity for a company name.

    Returns "" for an absent name, which callers must treat as unknown rather
    than as a match — two blanks are not the same vendor.
    """
    text = str(value or "").strip().lower()
    if not text:
        return ""
    for prefix in _NAME_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
            break
    words = [_LEGAL_FORMS.get(word, word) for word in re.split(r"[^a-z0-9&]+", text) if word]
    return "".join(words)


def compare_exact(field: ComparisonField, actual, expected) -> Comparison:
    """For fields with no tolerance concept — vendor name, PO number, tax match.

    Vendor names are compared on `vendor_key` rather than raw text; everything
    else is compared literally after trimming and case folding.
    """
    if actual is None or expected is None:
        return Comparison(field=field, expected_value=expected, actual_value=actual,
                           classification=MatchClassification.MISSING, evaluable=False)
    if field == ComparisonField.VENDOR:
        actual_key, expected_key = vendor_key(actual), vendor_key(expected)
        matched = bool(actual_key) and actual_key == expected_key
    else:
        matched = str(actual).strip().lower() == str(expected).strip().lower()
    return Comparison(
        field=field,
        expected_value=expected,
        actual_value=actual,
        classification=MatchClassification.MATCHED if matched else MatchClassification.OUTSIDE_TOLERANCE,
        evaluable=True,
    )


def compare_with_tolerance(field: ComparisonField, actual: Optional[float], expected: Optional[float],
                            tolerance_percent: float) -> Comparison:
    if actual is None or expected is None:
        return Comparison(field=field, expected_value=expected, actual_value=actual,
                           classification=MatchClassification.MISSING, evaluable=False,
                           tolerance_percent=tolerance_percent)
    absolute_variance, percentage_variance = compute_variance(actual, expected)
    classification = classify_by_tolerance(percentage_variance, tolerance_percent)
    return Comparison(
        field=field,
        expected_value=expected,
        actual_value=actual,
        absolute_variance=round(absolute_variance, 2),
        percentage_variance=None if percentage_variance is None else round(percentage_variance, 2),
        tolerance_percent=tolerance_percent,
        classification=classification,
        evaluable=True,
    )


def billable_quantity(scalar_quantity: Optional[float], line_items) -> Optional[float]:
    """
    The quantity to set against a goods receipt.

    An itemized document has no scalar quantity by design — the extractor
    deliberately leaves it absent rather than writing a row count beside the
    first row's price. The consequence was a hole: on any invoice that
    happened to carry line items, the quantity comparison had nothing to
    compare and simply did not run, so goods invoiced but never received went
    unreported. The eval harness found it as EVAL-07085, a 4.2% quantity
    variance silently cleared.

    The single-line case is recoverable and is recovered here. A genuinely
    multi-line document is NOT: five bearings and three desks do not add up to
    eight of anything, and a goods receipt stating one `received_quantity` is
    only meaningful against one line in the first place. Those still return
    None, which the caller reports as "not evaluable" — the honest answer, and
    a stated limitation rather than a silent gap.
    """
    if scalar_quantity is not None:
        return scalar_quantity
    lines = [line for line in (line_items or []) if line]
    if len(lines) != 1:
        return None
    quantity = (lines[0].get("quantity") if isinstance(lines[0], dict)
                else getattr(lines[0], "quantity", None))
    return None if quantity is None else float(quantity)


def implied_rate(case: dict, invoiced_quantity: Optional[float]) -> float:
    """The per-unit rate to price unreceived units at.

    Normally the invoice's own amount divided by the units it bills. An
    invoice that bills ZERO units states no rate at all, and dividing by it
    raised ZeroDivisionError — which the route layer turned into a 500 for the
    whole case rather than a finding. The stated unit price is the fallback,
    and an honest zero is the answer when the document gives neither.
    """
    amount = case.get("invoice_amount")
    if invoiced_quantity and amount is not None:
        return abs(float(amount) / float(invoiced_quantity))
    for field in ("invoice_unit_price", "po_unit_price"):
        stated = case.get(field)
        if stated:
            return abs(float(stated))
    return 0.0


def compute_match_score(comparisons: list[Comparison]) -> int:
    evaluable = [c for c in comparisons if c.evaluable]
    if not evaluable:
        return 0
    matched_count = sum(1 for c in evaluable if c.classification in MATCHED_CLASSIFICATIONS)
    return round(100 * matched_count / len(evaluable))


# ---------------------------------------------------------------------------
# Line-level comparison
# ---------------------------------------------------------------------------
def _line_key(description) -> str:
    """Loose key for pairing a PO line with the invoice line that bills it.

    The same line is rarely spelled identically on both documents — a PO says
    "Water tank &Plumbing Pipeline work" where the invoice says "Water tank
    &Plumbing Pipeline". Case, spacing and punctuation are therefore dropped,
    and pairing falls back to a prefix overlap before giving up.
    """
    return "".join(ch for ch in str(description or "").lower() if ch.isalnum())


def _pair_lines(po_lines: list[dict], invoice_lines: list[dict]) -> list[tuple[Optional[dict], Optional[dict]]]:
    """Pairs lines by description, then by position for whatever is left over.

    Unpaired lines are returned too — a line billed that was never ordered is
    a finding, not something to quietly drop.
    """
    remaining = list(invoice_lines)
    pairs: list[tuple[Optional[dict], Optional[dict]]] = []

    for po_line in po_lines:
        key = _line_key(po_line.get("description"))
        chosen = None
        if key:
            for candidate in remaining:
                candidate_key = _line_key(candidate.get("description"))
                if candidate_key and (candidate_key == key
                                      or candidate_key.startswith(key)
                                      or key.startswith(candidate_key)):
                    chosen = candidate
                    break
        if chosen is not None:
            remaining.remove(chosen)
        pairs.append((po_line, chosen))

    # Anything left on the invoice was billed without an ordered counterpart.
    for leftover in remaining:
        pairs.append((None, leftover))
    return pairs


def compare_line_items(po_lines, invoice_lines, price_tolerance_percent: float) -> list[LineComparison]:
    """Per-line unit-price comparison. Empty when either side is not itemized."""
    po_lines = [dict(line) for line in (po_lines or [])]
    invoice_lines = [dict(line) for line in (invoice_lines or [])]
    if not po_lines or not invoice_lines:
        return []

    results: list[LineComparison] = []
    for po_line, inv_line in _pair_lines(po_lines, invoice_lines):
        if po_line is None or inv_line is None:
            present = inv_line or po_line
            results.append(LineComparison(
                description=present.get("description"),
                po_quantity=(po_line or {}).get("quantity"),
                invoice_quantity=(inv_line or {}).get("quantity"),
                po_unit_price=(po_line or {}).get("unit_price"),
                invoice_unit_price=(inv_line or {}).get("unit_price"),
                po_amount=(po_line or {}).get("amount"),
                invoice_amount=(inv_line or {}).get("amount"),
                classification=MatchClassification.MISSING,
                only_on="invoice" if po_line is None else "purchase_order",
            ))
            continue

        po_price, inv_price = po_line.get("unit_price"), inv_line.get("unit_price")
        if po_price is None or inv_price is None:
            classification = MatchClassification.MISSING
            absolute = percentage = None
        else:
            absolute, percentage = compute_variance(inv_price, po_price)
            classification = classify_by_tolerance(percentage, price_tolerance_percent)

        results.append(LineComparison(
            description=inv_line.get("description") or po_line.get("description"),
            po_quantity=po_line.get("quantity"),
            invoice_quantity=inv_line.get("quantity"),
            po_unit_price=po_price,
            invoice_unit_price=inv_price,
            po_amount=po_line.get("amount"),
            invoice_amount=inv_line.get("amount"),
            variance_amount=None if absolute is None else round(absolute, 2),
            percentage_variance=None if percentage is None else round(percentage, 2),
            classification=classification,
        ))
    return results


def line_overcharge_total(line_comparisons: list[LineComparison]) -> float:
    """Sum of (invoice - PO) across lines billed above the ordered price.

    Only overcharges count: a line billed BELOW the ordered price is not money
    at risk, and letting it net off a genuine overcharge on another line would
    understate the exposure a reviewer has to act on.
    """
    total = 0.0
    for line in line_comparisons:
        if line.classification != MatchClassification.OUTSIDE_TOLERANCE:
            continue
        if line.variance_amount is None or line.variance_amount <= 0:
            continue
        # Clamped for the same reason the case-level quantities are: a hyphen
        # beside a quantity parses as a minus sign, and a negative count would
        # turn an overcharge into a credit against the other lines.
        quantity = max(0.0, float(line.invoice_quantity)) if line.invoice_quantity is not None else 1.0
        total += line.variance_amount * quantity
    return round(total, 2)


# ---------------------------------------------------------------------------
# Goods vs services, and how much an unconfirmed invoice actually risks
# ---------------------------------------------------------------------------
# An Indian tax invoice distinguishes the two in its own codes: HSN codes
# classify goods, SAC codes classify services and begin with 99. That is a
# fact printed on the document rather than an inference, so it is checked
# first; wording is only consulted when no code is present.
_SERVICE_WORDS = (
    "work", "works", "labour", "labor", "service", "servicing", "installation",
    "installing", "providing and fixing", "reconditioning", "repair", "maintenance",
    "charges", "consultancy", "supervision", "erection", "commissioning", "painting",
)
# Units of measure that only make sense for work performed.
_SERVICE_UOM = ("ls", "lot", "job", "lump sum", "each job")


def classify_procurement_kind(line_items) -> str:
    """"goods" or "services", from the document's own codes and wording."""
    items = [dict(item) for item in (line_items or [])]
    if not items:
        return "goods"

    for item in items:
        code = str(item.get("hsn_sac") or "").strip()
        if code.startswith("99") and len(code) >= 4:
            return "services"

    service_hits = 0
    for item in items:
        text = str(item.get("description") or "").lower()
        if any(word in text for word in _SERVICE_WORDS):
            service_hits += 1
        elif str(item.get("uom") or "").strip().lower() in _SERVICE_UOM:
            service_hits += 1
    # A majority, so one "installation charges" line on a hardware order does
    # not reclassify the whole invoice.
    return "services" if service_hits * 2 > len(items) else "goods"


def risk_for_unconfirmed(amount: float, comparisons, high_value_threshold: float) -> str:
    """
    Risk when the only thing outstanding is confirmation of delivery.

    Previously this was the literal string "high" regardless of anything else,
    so a fully-reconciled small invoice and a wildly mismatched large one
    scored identically, and a 100% match score sat beside "high risk" with
    nothing explaining the pair.

    Something that actually disagrees is still high — an unconfirmed invoice
    that ALSO fails a comparison is the worst case. Otherwise the exposure is
    the amount: everything checkable checks out, and what is left is a
    procedural step.
    """
    breached = [c for c in comparisons
                if c.evaluable and c.classification == MatchClassification.OUTSIDE_TOLERANCE]
    if breached:
        return "high"
    if amount >= high_value_threshold:
        return "high"
    if amount >= high_value_threshold / 4:
        return "medium"
    return "low"


def describe_outstanding(awaiting: str, comparisons, line_comparisons, amount: float) -> str:
    """The sentence that reconciles a high match score with an open finding."""
    checked = [c for c in comparisons if c.evaluable]
    agreed = [c for c in checked if c.classification in MATCHED_CLASSIFICATIONS]
    parts = []
    if line_comparisons:
        matched_lines = [c for c in line_comparisons
                         if c.classification in MATCHED_CLASSIFICATIONS]
        parts.append(f"All {len(matched_lines)} of {len(line_comparisons)} ordered lines "
                     f"match the invoice" if len(matched_lines) == len(line_comparisons)
                     else f"{len(matched_lines)} of {len(line_comparisons)} ordered lines "
                          f"match the invoice")
    if checked:
        parts.append(f"{len(agreed)} of {len(checked)} checked fields agree")
    settled = "; ".join(parts) if parts else "The documents on file agree"
    return (f"{settled}. No {awaiting} is on file, so nothing yet confirms this was "
            f"delivered — that is the only thing holding {amount:,.0f}.")


def compare_tax_arithmetic(subtotal, tax, total, tolerance_percent: float) -> Optional[Comparison]:
    """
    Does the invoice add up against itself?

    This needs no second document: subtotal + tax must equal the total the
    vendor is asking to be paid. It catches ordinary transcription errors and
    the oldest invoice manipulation there is — a total quietly inflated above
    the lines and tax that justify it. Pure arithmetic over three numbers read
    off one page.

    Returns None when the invoice does not state enough to check, which is not
    a failure: many valid invoices show only a total.
    """
    if subtotal is None or total is None:
        return None
    expected = round(subtotal + (tax or 0), 2)
    absolute, percentage = compute_variance(total, expected)
    return Comparison(
        field=ComparisonField.TAX_ARITHMETIC,
        expected_value=expected,
        actual_value=round(float(total), 2),
        absolute_variance=round(absolute, 2),
        percentage_variance=None if percentage is None else round(percentage, 2),
        tolerance_percent=tolerance_percent,
        # Arithmetic on one page has no tolerance band in principle, but
        # rounding between systems is real; the configured price tolerance is
        # a deliberate over-allowance rather than a new setting to tune.
        classification=classify_by_tolerance(percentage, tolerance_percent),
        evaluable=True,
    )


def compare_quoted_price(quotation_total, po_total, tolerance_percent: float) -> Optional[Comparison]:
    """
    The order against the quotation it was raised from.

    Closes the chain offer -> order -> delivery -> invoice. Three-way matching
    verifies that an invoice matches its order; nothing verifies that the
    order matched what was actually quoted, which is where a price can be
    raised without anyone noticing.
    """
    if quotation_total in (None, 0) or po_total is None:
        return None
    absolute, percentage = compute_variance(po_total, quotation_total)
    return Comparison(
        field=ComparisonField.QUOTED_PRICE,
        expected_value=round(float(quotation_total), 2),
        actual_value=round(float(po_total), 2),
        absolute_variance=round(absolute, 2),
        percentage_variance=None if percentage is None else round(percentage, 2),
        tolerance_percent=tolerance_percent,
        classification=classify_by_tolerance(percentage, tolerance_percent),
        evaluable=True,
    )


def tax_basis(total, subtotal, tax, line_items) -> str:
    """
    Whether a stated total includes tax: "gross", "net", or "unknown".

    Comparing a tax-inclusive total against a tax-exclusive one is a units
    error, not a variance — a PO quoted ex-GST at 53,000 against an invoice of
    62,540 is an 18% "breach" that describes the tax rate. The earlier guard
    only worked when BOTH documents stated a subtotal, which the deterministic
    parser often cannot recover, so the false positive came straight back
    whenever extraction fell back.

    The basis is established from what the document itself shows:
      * a stated tax amount means the total is gross;
      * a total equal to the sum of its own line items means it is net;
      * anything else is unknown, and unknown is not comparable.
    """
    if total is None:
        return "unknown"
    if tax:
        return "gross"
    line_sum = round(sum((item or {}).get("amount") or 0 for item in (line_items or [])), 2)
    if line_sum and abs(float(total) - line_sum) < 0.01:
        return "net"
    if subtotal is not None and abs(float(total) - float(subtotal)) < 0.01:
        return "net"
    return "unknown"


def _demote_cross_document_comparisons(comparisons: list[Comparison]) -> list[Comparison]:
    """Re-mark every cross-document comparison as unable-to-verify.

    Used only when the documents have been shown to describe different
    transactions. Returning the comparisons untouched would leave the match
    workspace displaying "unit price: expected 4,500, actual 2,400, OUTSIDE
    TOLERANCE" — a precise variance between an office chair and a steel pipe,
    which is the exact fabrication the coherence check exists to stop.

    The figures are KEPT, because a reviewer settling this needs to see what
    each document actually said. Only the verdict on them is withdrawn: the
    values are real, the comparison between them is not.

    Comparisons that read a single document against itself — the invoice's own
    subtotal-plus-tax arithmetic — are left alone. They are still true.

    Note there is NO `and comparison.evaluable` guard on the cross-document
    branch, and that omission is deliberate. An earlier version skipped rows
    that were already non-evaluable, on the reasoning that they had nothing
    left to withdraw. They did: `po_billed_total` is built non-evaluable when
    the two sides are on different tax bases, and it KEEPS its computed
    percentage. So the table went on printing "Billed against this order —
    variance 2844.44%" on a case whose headline was that nothing could be
    compared. A stale number in a quiet column is still a fabricated number.
    """
    out = []
    for comparison in comparisons:
        if comparison.field not in _CROSS_DOCUMENT_FIELDS:
            out.append(comparison)
            continue
        out.append(comparison.model_copy(update={
            "classification": MatchClassification.UNABLE_TO_VERIFY,
            "evaluable": False,
            "absolute_variance": None,
            "percentage_variance": None,
        }))
    return out


# Findings that remain true even when the documents do not belong together,
# and therefore outrank UNRELATED_DOCUMENTS.
#
# Every one of them is a statement about the INVOICE — checked against the
# vendor's own history or against itself — so none of them borrowed a figure
# from the purchase order that turned out to be the wrong one. An invoice that
# is an exact copy of last month's is an exact copy whichever order sits
# beside it, and telling the reviewer to check their uploads instead of
# stopping the payment would be a worse answer, not a more precise one.
#
# Everything NOT on this list — price and quantity variance, missing goods
# receipt, vendor mismatch, and no_exception — is a claim built by comparing
# the invoice to the other documents, and is exactly what the coherence check
# invalidates. no_exception is on that side of the line deliberately: "every
# comparison passed, this invoice is payable" is the most dangerous sentence
# in the product to say about two documents that describe different orders.
_SURVIVES_INCOHERENCE = frozenset({
    ExceptionType.MISSING_PURCHASE_ORDER,
    ExceptionType.DUPLICATE_INVOICE,
    ExceptionType.PAYMENT_DETAILS_CHANGED,
    ExceptionType.PO_OVER_BILLED,
    ExceptionType.RECURRING_SUSPECTED,
    ExceptionType.VENDOR_PRICE_DRIFT,
    ExceptionType.TAX_TOTAL_MISMATCH,
})


def evaluate_exception(case: dict, tolerance: dict) -> MatchResult:
    """The public entry point: match the documents, then decide whether the
    match was ever meaningful.

    The coherence check is applied HERE rather than as another branch inside
    the cascade below, and the difference matters. The cascade has fourteen
    return statements; a check spliced into it would be one more branch that a
    fifteenth could be added in front of by accident. Applied at the exit,
    every result passes through it, and which findings outrank it is a set
    somebody can read (`_SURVIVES_INCOHERENCE`) rather than an ordering they
    have to reconstruct.
    """
    coherence = coherence_service.assess(case, case.get("link_warnings"))
    result = _match_documents(case, tolerance)
    result.coherence = coherence

    if not coherence_service.is_contradicted(coherence):
        return result

    # Withdraw the cross-document arithmetic FIRST, and unconditionally.
    #
    # These are two separate questions and an earlier version ran them as one:
    # "is this arithmetic trustworthy" and "which finding do we report". A
    # duplicate invoice outranks an incoherence — it is true whichever order
    # sits beside it — but that says nothing about the comparison table
    # underneath, which is still measuring an invoice against the wrong
    # order. So a duplicate finding was reported correctly above a panel
    # reading "Billed against PO-2026-00733, over by 2,56,000" for an invoice
    # citing PO-2026-00421.
    result = _withdraw_cross_document_figures(result)

    if result.exception_type in _SURVIVES_INCOHERENCE:
        return result
    return _unrelated_documents(result, case, coherence)


def _withdraw_cross_document_figures(result: MatchResult) -> MatchResult:
    """Strip every figure that was computed by comparing one document against
    another, keeping the findings that did not depend on one.

    Applied to EVERY contradicted case, whatever finding it ends up reporting.
    """
    demoted = _demote_cross_document_comparisons(result.comparisons)
    return result.model_copy(update={
        "comparisons": demoted,
        # Scored over the cross-document rows only, all of which have just
        # been demoted — so this is 0.
        #
        # Not `compute_match_score(demoted)`, which was the first attempt and
        # returned 100. A match score is a statement about agreement BETWEEN
        # documents, and the only evaluable row left after demotion is the
        # invoice's own subtotal-plus-tax arithmetic. That row is still true,
        # and it is not agreement with anything: an invoice that adds up,
        # sitting beside an order for different goods, scored a perfect match
        # on a case whose entire finding was that nothing could be compared.
        #
        # 0 is the same answer MISSING_PURCHASE_ORDER gives, for the same
        # reason: an invoice with no valid counterpart is unchecked.
        "match_score": compute_match_score(
            [c for c in demoted if c.field in _CROSS_DOCUMENT_FIELDS]),
        # `po_billing` answers "how much has been billed against this order in
        # total", and it took its order value from the purchase order on file
        # — the one that turns out not to be this invoice's.
        "po_billing": None,
        # Same argument, one level down: a per-line table pairing steel pipe
        # against office chairs is a list of variances between things that
        # were never comparable. What each document billed is on the Documents
        # tab, where it is presented as extraction rather than as a comparison.
        "line_comparisons": [],
    })


def _unrelated_documents(result: MatchResult, case: dict, coherence: dict) -> MatchResult:
    """Replace a variance computed across unrelated documents with the fact
    that they are unrelated.

    The financial impact is the full invoice amount, and not because anything
    was overcharged: nothing on this invoice has been verified against
    anything, so all of it is unconfirmed. That is the same basis
    MISSING_PURCHASE_ORDER uses, for the same reason — an invoice with no
    valid counterpart is entirely unchecked, whether the counterpart is
    absent or simply belongs to a different order.
    """
    evidence = [s["detail"] for s in coherence["signals"] if s["strength"] in ("hard", "context")]
    return result.model_copy(update={
        "exception_type": ExceptionType.UNRELATED_DOCUMENTS,
        "financial_impact": float(case.get("invoice_amount") or 0),
        "financial_impact_basis": (
            "The full invoice amount, because nothing on it has been verified. The documents "
            "on this case describe different transactions, so no comparison between them means "
            "anything."
        ),
        "outstanding": " ".join(evidence) + (
            " Check that the right purchase order and goods receipt were uploaded for this "
            "invoice. Until they are, no variance on this case can be computed."
        ),
        "recommended_owner": "Accounts Payable",
        "risk_level": "high",
    })


def _match_documents(case: dict, tolerance: dict) -> MatchResult:
    """
    case: normalized record with keys —
        vendor_name, po_vendor_name, po_number, invoice_po_number,
        po_unit_price, invoice_unit_price,
        po_quantity, received_quantity (None if no goods receipt), invoice_quantity,
        tax_amount, po_tax_amount,
        po_total, invoice_total,
        goods_receipt_exists (bool), purchase_order_exists (bool),
        invoice_amount (for the missing-receipt financial-impact case)
    tolerance: {"price_variance_percent": 5, "quantity_variance_percent": 2}
    """
    price_tol = tolerance["price_variance_percent"]
    qty_tol = tolerance["quantity_variance_percent"]

    comparisons: list[Comparison] = []
    comparisons.append(compare_exact(ComparisonField.VENDOR, case.get("vendor_name"), case.get("po_vendor_name")))
    comparisons.append(compare_exact(ComparisonField.PO_NUMBER, case.get("invoice_po_number"), case.get("po_number")))

    # Line-level detail, when both documents are itemized. This is the only
    # comparison that can see a single overcharged line inside an order whose
    # total still looks acceptable.
    line_comparisons = compare_line_items(
        case.get("po_line_items"), case.get("invoice_line_items"), price_tol)
    lines_outside = [c for c in line_comparisons
                     if c.classification == MatchClassification.OUTSIDE_TOLERANCE]
    lines_unmatched = [c for c in line_comparisons if c.only_on is not None]

    # --- Missing purchase order short-circuits most comparisons ---
    if not case.get("purchase_order_exists", True):
        comparisons.append(Comparison(field=ComparisonField.UNIT_PRICE, classification=MatchClassification.MISSING,
                                       evaluable=False))
        comparisons.append(Comparison(field=ComparisonField.QUANTITY, classification=MatchClassification.MISSING,
                                       evaluable=False))
        match_score = compute_match_score(comparisons)
        return MatchResult(
            exception_type=ExceptionType.MISSING_PURCHASE_ORDER,
            comparisons=comparisons,
            line_comparisons=line_comparisons,
            match_score=match_score,
            financial_impact=float(case.get("invoice_amount", 0)),
            financial_impact_basis="Full invoice amount at risk pending PO confirmation.",
            recommended_owner="Procurement",
            risk_level="high",
        )

    # --- Price comparison (Case A) ---
    price_cmp = compare_with_tolerance(
        ComparisonField.UNIT_PRICE, case.get("invoice_unit_price"), case.get("po_unit_price"), price_tol
    )
    comparisons.append(price_cmp)

    # --- Quantity comparison ---
    # Per FR-006 fix: compare_quantity now genuinely applies the tolerance
    # instead of the old `invoice_quantity > received_quantity` check.
    # Expected = received quantity (what should have been invoiced);
    # actual = invoiced quantity. Only evaluable if a goods receipt exists.
    goods_receipt_exists = case.get("goods_receipt_exists", True)
    invoiced_quantity = billable_quantity(
        case.get("invoice_quantity"), case.get("invoice_line_items"))
    if goods_receipt_exists and case.get("received_quantity") is not None:
        qty_cmp = compare_with_tolerance(
            ComparisonField.QUANTITY, invoiced_quantity, case.get("received_quantity"), qty_tol
        )
    else:
        qty_cmp = Comparison(field=ComparisonField.QUANTITY, classification=MatchClassification.MISSING,
                              evaluable=False)
    comparisons.append(qty_cmp)

    # --- Line items rolled up into one scored row ---
    if line_comparisons:
        evaluable_lines = [c for c in line_comparisons if c.classification != MatchClassification.MISSING]
        worst = max((abs(c.percentage_variance) for c in evaluable_lines
                     if c.percentage_variance is not None), default=None)
        if lines_unmatched:
            line_classification = MatchClassification.OUTSIDE_TOLERANCE
        elif lines_outside:
            line_classification = MatchClassification.OUTSIDE_TOLERANCE
        elif not evaluable_lines:
            line_classification = MatchClassification.MISSING
        elif worst == 0:
            line_classification = MatchClassification.MATCHED
        else:
            line_classification = MatchClassification.WITHIN_TOLERANCE
        comparisons.append(Comparison(
            field=ComparisonField.LINE_ITEMS,
            expected_value=f"{len(case.get('po_line_items') or [])} line(s) ordered",
            actual_value=f"{len(case.get('invoice_line_items') or [])} line(s) billed",
            percentage_variance=worst,
            tolerance_percent=price_tol,
            classification=line_classification,
            evaluable=line_classification != MatchClassification.MISSING,
        ))

    # --- Subtotal (pre-tax) — compares like with like when one document
    #     shows tax and the other does not ---
    if case.get("invoice_subtotal") is not None and case.get("po_subtotal") is not None:
        comparisons.append(compare_with_tolerance(
            ComparisonField.SUBTOTAL, case["invoice_subtotal"], case["po_subtotal"], price_tol))

    # --- The invoice against itself: subtotal + tax = total ---
    tax_arithmetic = compare_tax_arithmetic(
        case.get("invoice_subtotal"), case.get("tax_amount"), case.get("invoice_total"), price_tol)
    if tax_arithmetic is not None:
        comparisons.append(tax_arithmetic)

    # --- The order against the quotation it was raised from ---
    quoted = compare_quoted_price(
        case.get("quotation_total"), case.get("po_subtotal") or case.get("po_total"), price_tol)
    if quoted is not None:
        comparisons.append(quoted)

    # --- Everything billed against this order, across every case ---
    # Subject to the same units rule as the total comparison: a running total
    # of tax-inclusive invoices measured against a tax-exclusive order value
    # reports over-billing that is really just the tax. When the two sides are
    # not on the same basis the running total is recorded but not judged.
    billing = case.get("po_billing") or {}
    billing_comparable = (
        tax_basis(case.get("invoice_total"), case.get("invoice_subtotal"),
                  case.get("tax_amount"), case.get("invoice_line_items"))
        == tax_basis(case.get("po_total"), case.get("po_subtotal"),
                     case.get("po_tax_amount"), case.get("po_line_items"))
        != "unknown"
    )
    if billing:
        billing = dict(billing, comparable=billing_comparable)
    if billing.get("order_value"):
        comparisons.append(Comparison(
            field=ComparisonField.PO_BILLED_TOTAL,
            expected_value=round(float(billing["order_value"]), 2),
            actual_value=round(float(billing["total_billed"]), 2),
            absolute_variance=round(billing["total_billed"] - billing["order_value"], 2),
            percentage_variance=round(
                (billing["total_billed"] - billing["order_value"]) / billing["order_value"] * 100, 2),
            tolerance_percent=price_tol,
            classification=(
                MatchClassification.UNABLE_TO_VERIFY if not billing_comparable
                else MatchClassification.OUTSIDE_TOLERANCE if billing.get("is_over_billed")
                else MatchClassification.MATCHED),
            evaluable=billing_comparable,
        ))

    # --- Tax / total (exact-ish; not the MVP-priority focus but still scored) ---
    if case.get("tax_amount") is not None and case.get("po_tax_amount") is not None:
        comparisons.append(compare_with_tolerance(ComparisonField.TAX, case["tax_amount"], case["po_tax_amount"],
                                                    price_tol))
    if case.get("invoice_total") is not None and case.get("po_total") is not None:
        # Comparing a tax-inclusive total against a tax-exclusive one is not a
        # variance, it is a units error. A PO quoted ex-GST at 53,000 against
        # an invoice of 62,540 is an 18% "breach" that describes the tax rate,
        # not an overcharge. When only one side states tax, the totals are not
        # comparable and say so — the subtotal row above already compares the
        # part that IS like for like.
        invoice_basis = tax_basis(case.get("invoice_total"), case.get("invoice_subtotal"),
                                  case.get("tax_amount"), case.get("invoice_line_items"))
        po_basis = tax_basis(case.get("po_total"), case.get("po_subtotal"),
                             case.get("po_tax_amount"), case.get("po_line_items"))
        if invoice_basis != po_basis or "unknown" in (invoice_basis, po_basis):
            comparisons.append(Comparison(
                field=ComparisonField.TOTAL,
                expected_value=case["po_total"], actual_value=case["invoice_total"],
                classification=MatchClassification.UNABLE_TO_VERIFY,
                evaluable=False,
            ))
        else:
            comparisons.append(compare_with_tolerance(
                ComparisonField.TOTAL, case["invoice_total"], case["po_total"], price_tol))

    match_score = compute_match_score(comparisons)
    tolerance_source = tolerance.get("tolerance_source")

    # --- Findings that outrank every single-case comparison ---------------
    # Ordered by what a reviewer must act on first, and the order is finer
    # than "duplicates first" because the duplicate check has two very
    # different strengths.
    #
    #   1. An EXACT duplicate — same vendor, same invoice number — is
    #      near-certain, and the correct action is "do not pay this at all",
    #      which makes every other finding on the case irrelevant.
    #   2. Changed payment details come next. This ordering was wrong until
    #      the eval harness caught it: a NEAR duplicate used to outrank a bank
    #      change, so an invoice for a familiar amount arriving from a
    #      familiar vendor with an unfamiliar account was reported as a
    #      possible re-submission. That is precisely the payment-diversion
    #      pattern, and describing it as a duplicate sends the reviewer to
    #      check the wrong thing. A suspicion about the amount must not bury a
    #      fraud indicator about the destination.
    #   3. Over-billing, then a near duplicate, both of which are about the
    #      amount rather than about who gets paid.
    #
    # See eval/run_eval.py — the case that found this is EVAL-07109.
    duplicates = case.get("duplicate_of") or []
    payment_changes = case.get("payment_detail_changes") or []
    drift = case.get("price_drift") or None
    # A recurring series is reported as a duplicate-shaped finding but is NOT
    # a duplicate, so it is separated out here rather than at each use.
    recurring = [d for d in duplicates if d.get("confidence") == "recurring"]
    exact_duplicates = [d for d in duplicates if d.get("confidence") == "exact"]
    near_duplicates = [d for d in duplicates if d.get("confidence") == "near"]
    # `billing` was already augmented with `comparable` above; re-reading it
    # from the case here would drop that flag on every early return, so the
    # UI would show a running total with no indication of whether it was
    # measured against a comparable order value.

    shared = dict(
        comparisons=comparisons,
        line_comparisons=line_comparisons,
        match_score=match_score,
        duplicate_of=duplicates,
        po_billing=billing or None,
        payment_detail_changes=payment_changes,
        price_drift=drift,
        tolerance_source=tolerance_source,
    )

    def _duplicate_result(matches: list[dict], certain: bool) -> MatchResult:
        strongest = matches[0]
        return MatchResult(
            exception_type=ExceptionType.DUPLICATE_INVOICE,
            **shared,
            cross_case=True,
            financial_impact=float(case.get("invoice_amount", 0)),
            financial_impact_basis=(
                "The full invoice amount, because paying it would be paying twice. "
                + str(strongest.get("reason", ""))
            ),
            outstanding=(
                f"{strongest.get('reason')} Confirm whether this is a genuine re-submission "
                f"before any further checking — a duplicate should not be paid at all, so the "
                f"variances below do not matter until that is settled."
            ),
            recommended_owner="Accounts Payable",
            risk_level="high" if certain else "medium",
        )

    if exact_duplicates:
        return _duplicate_result(exact_duplicates, certain=True)

    if payment_changes:
        return MatchResult(
            exception_type=ExceptionType.PAYMENT_DETAILS_CHANGED,
            **shared,
            cross_case=True,
            financial_impact=float(case.get("invoice_amount", 0)),
            financial_impact_basis=(
                "The full invoice amount, because it would be paid to an account this vendor "
                "has not used before."
            ),
            outstanding=payment_changes[0].get("detail"),
            recommended_owner="Accounts Payable",
            risk_level="high",
        )

    # Only when SEVERAL invoices are involved. A single invoice above its
    # order is a price or quantity variance, which the comparisons below
    # describe precisely; this branch exists for the case no single-invoice
    # check can see, where each one passes and the running total does not.
    # `order_value` is formatted into both sentences below. cumulative_billing
    # never returns the key empty, but a case record written by an older
    # version can, and a missing order value there raised TypeError from an
    # f-string — answering the whole case with a 500 instead of a finding.
    if (billing.get("is_over_billed") and billing.get("invoice_count", 1) > 1
            and billing_comparable and billing.get("order_value")
            and billing.get("total_billed") is not None
            and billing.get("over_billed_by") is not None):
        over = billing["over_billed_by"]
        return MatchResult(
            exception_type=ExceptionType.PO_OVER_BILLED,
            **shared,
            financial_impact=float(over),
            financial_impact_basis=(
                f"{billing['total_billed']:,.2f} billed against a {billing['order_value']:,.2f} "
                f"order across {billing['invoice_count']} invoice(s) — "
                f"{over:,.2f} more than was ordered."
            ),
            outstanding=(
                f"This invoice passes on its own, but it is the {billing['invoice_count']} one "
                f"billed against {billing['po_number']}. Together they exceed the order by "
                f"{over:,.2f}. Either the order needs amending or the excess should not be paid."
            ),
            recommended_owner="Procurement",
            cross_case=True,
            risk_level="high",
        )

    # A same-vendor, same-amount match with a different invoice number. Real,
    # and weaker than everything above it — which is why it sits here rather
    # than at the top with its exact-match sibling.
    if near_duplicates:
        return _duplicate_result(near_duplicates, certain=False)

    # --- The invoice does not add up against itself -----------------------
    if tax_arithmetic is not None and tax_arithmetic.classification == MatchClassification.OUTSIDE_TOLERANCE:
        return MatchResult(
            exception_type=ExceptionType.TAX_TOTAL_MISMATCH,
            **shared,
            financial_impact=abs(float(tax_arithmetic.absolute_variance or 0)),
            financial_impact_basis=(
                f"The invoice asks for {tax_arithmetic.actual_value:,.2f} but its own subtotal "
                f"and tax add up to {tax_arithmetic.expected_value:,.2f}."
            ),
            outstanding=(
                "This invoice does not reconcile against itself, so no comparison with the "
                "purchase order can be trusted until the vendor restates it."
            ),
            recommended_owner="Accounts Payable",
            risk_level="high",
        )

    # --- Billed by someone other than who was ordered from ----------------
    vendor_cmp = next((c for c in comparisons if c.field == ComparisonField.VENDOR), None)
    if (vendor_cmp is not None and vendor_cmp.evaluable
            and vendor_cmp.classification == MatchClassification.OUTSIDE_TOLERANCE):
        return MatchResult(
            exception_type=ExceptionType.VENDOR_MISMATCH,
            **shared,
            financial_impact=float(case.get("invoice_amount", 0)),
            financial_impact_basis=(
                "The full invoice amount, because the party billing is not the party ordered from."
            ),
            outstanding=(
                f"The order was raised on {vendor_cmp.expected_value} but the invoice is from "
                f"{vendor_cmp.actual_value}. Confirm the two are the same business before paying."
            ),
            recommended_owner="Procurement",
            risk_level="high",
        )

    # --- Missing goods receipt (Case C) takes priority as the exception type
    #     when there's no receipt, regardless of what price/qty comparisons say ---
    if not goods_receipt_exists:
        amount = float(case.get("invoice_amount", 0))
        kind = classify_procurement_kind(
            case.get("invoice_line_items") or case.get("po_line_items"))
        awaiting = "service confirmation" if kind == "services" else "goods receipt"
        threshold = float(tolerance.get("high_value_threshold") or DEFAULT_HIGH_VALUE_THRESHOLD)
        return MatchResult(
            exception_type=ExceptionType.MISSING_GOODS_RECEIPT,
            comparisons=comparisons,
            line_comparisons=line_comparisons,
            match_score=match_score,
            procurement_kind=kind,
            awaiting_document=awaiting,
            outstanding=describe_outstanding(awaiting, comparisons, line_comparisons, amount),
            financial_impact=amount,
            financial_impact_basis=(
                f"Full invoice amount held pending {awaiting} "
                f"— not a computed price/quantity variance."
            ),
            tolerance_source=tolerance_source,
            recommended_owner="Requesting business unit",
            risk_level=risk_for_unconfirmed(amount, comparisons, threshold),
        )

    # --- Quantity variance (Case B) ---
    if qty_cmp.evaluable and qty_cmp.classification == MatchClassification.OUTSIDE_TOLERANCE:
        # invoiced_quantity, not case["invoice_quantity"]: on an itemized
        # document the scalar is absent and the comparison above was made
        # against the recovered line quantity. Using the raw field here would
        # raise a TypeError on exactly the cases the recovery exists for.
        billed_beyond_receipt = invoiced_quantity - case["received_quantity"]
        # Only units billed BEYOND what was received are money at risk. An
        # invoice for FEWER units than were delivered is a variance worth
        # reporting and nothing to hold, and booking it as a NEGATIVE impact
        # let one under-billed invoice cancel out a genuine overcharge in
        # every portfolio total that sums this field.
        unreceived_units = max(0.0, billed_beyond_receipt)
        implied_unit_price = implied_rate(case, invoiced_quantity)
        financial_impact = round(unreceived_units * implied_unit_price, 2)
        return MatchResult(
            exception_type=ExceptionType.QUANTITY_VARIANCE,
            comparisons=comparisons,
            line_comparisons=line_comparisons,
            match_score=match_score,
            financial_impact=financial_impact,
            financial_impact_basis=(
                f"{unreceived_units:g} unreceived units x implied unit price "
                f"({implied_unit_price:.2f}) = amount at risk pending receipt confirmation."
                if unreceived_units else
                f"{invoiced_quantity:g} unit(s) billed against "
                f"{float(case['received_quantity']):g} received — the invoice is below the "
                f"goods receipt, so nothing is at risk on it. Confirm the balance is not "
                f"still to be billed."
            ),
            tolerance_source=tolerance_source,
            recommended_owner="Receiving",
            risk_level=(
                "medium" if qty_cmp.percentage_variance is not None
                and abs(qty_cmp.percentage_variance) < 25 else "high"
            ),
        )

    # --- Price variance (Case A) ---
    if price_cmp.evaluable and price_cmp.classification == MatchClassification.OUTSIDE_TOLERANCE:
        variance_per_unit = abs(price_cmp.absolute_variance)
        # A count of units cannot be negative. _to_number accepts a leading
        # minus, so a hyphen sitting next to a quantity on a real layout parses
        # as one — and multiplying a positive per-unit variance by it produced
        # a NEGATIVE amount at risk, which then subtracted from the portfolio
        # totals that sum this field. An unusable quantity yields no computable
        # exposure, which is the honest answer, not a negative one.
        quantity = max(0.0, float(invoiced_quantity or 0))
        financial_impact = round(variance_per_unit * quantity, 2)
        return MatchResult(
            exception_type=ExceptionType.PRICE_VARIANCE,
            comparisons=comparisons,
            line_comparisons=line_comparisons,
            match_score=match_score,
            financial_impact=financial_impact,
            financial_impact_basis=(
                f"Variance/unit ({variance_per_unit:g}) x quantity ({quantity:g})."
            ),
            tolerance_source=tolerance_source,
            recommended_owner="Procurement",
            # An absent percentage means the order priced this at zero and the
            # invoice did not. That is not a small variance.
            risk_level=("high" if price_cmp.percentage_variance is None
                        or abs(price_cmp.percentage_variance) > 10 else "medium"),
        )

    # --- Price variance found at LINE level (multi-line documents) ---
    # On an itemized document the scalar unit_price is absent by design, so
    # the check above cannot fire. One overcharged line among several is still
    # a price variance, and the impact is the sum of the overcharged lines
    # rather than a single unit delta.
    if lines_outside or lines_unmatched:
        financial_impact = line_overcharge_total(line_comparisons)
        worst_line = max(
            (c for c in lines_outside if c.percentage_variance is not None),
            key=lambda c: abs(c.percentage_variance), default=None,
        )
        if lines_unmatched and financial_impact == 0:
            billed_only = [c for c in lines_unmatched if c.only_on == "invoice"]
            financial_impact = round(
                sum(max(0.0, float(c.invoice_amount or 0)) for c in billed_only), 2)
            basis = (
                f"{len(billed_only)} invoice line(s) have no matching purchase-order line; "
                f"their billed amount is the exposure."
            ) if billed_only else (
                "Ordered line(s) are missing from the invoice; no amount is at risk yet."
            )
        else:
            basis = (
                f"Sum of per-line overcharges across "
                f"{len([c for c in lines_outside if (c.variance_amount or 0) > 0])} line(s) "
                f"billed above the ordered price."
            )
        return MatchResult(
            exception_type=ExceptionType.PRICE_VARIANCE,
            comparisons=comparisons,
            line_comparisons=line_comparisons,
            match_score=match_score,
            tolerance_source=tolerance_source,
            financial_impact=financial_impact,
            financial_impact_basis=basis,
            recommended_owner="Procurement",
            risk_level="high" if (
                worst_line is not None and abs(worst_line.percentage_variance) > 10
            ) or lines_unmatched else "medium",
        )

    # --- Findings on an invoice that otherwise passes ---------------------
    # Both of the following describe an invoice where every comparison above
    # agreed. They sit here, below every single-case check, deliberately: if
    # this invoice ALSO has a price variance, that variance is the thing to
    # act on and this is context. What they are not is nothing — an invoice
    # that passes every check it can be given is exactly where a per-invoice
    # system stops looking, and both of these are still money.

    # A recognised billing schedule. Reported at low severity and with no
    # money attached: the amount is only at risk if this turns out to be a
    # second copy, and booking every month's rent as value-at-risk would make
    # the portfolio's headline figure meaningless.
    if recurring:
        pattern = recurring[0].get("pattern") or {}
        cadence = pattern.get("cadence") or f"~{pattern.get('mean_interval_days', 0):.0f}-day"
        return MatchResult(
            exception_type=ExceptionType.RECURRING_SUSPECTED,
            **shared,
            cross_case=True,
            financial_impact=0.0,
            financial_impact_basis=(
                "Nothing is booked as at risk. This is a recognised billing pattern, not a "
                "variance — the invoice amount only becomes exposure if the series turns out "
                "to contain a genuine second copy."
            ),
            outstanding=recurring[0].get("reason"),
            recommended_owner="Accounts Payable",
            risk_level="low",
        )

    # A rate that has crept. Every invoice in the series cleared on its own,
    # which is the finding.
    if drift:
        quantity = invoiced_quantity or 1
        excess_per_unit = drift["latest_price"] - drift["first_price"]
        return MatchResult(
            exception_type=ExceptionType.VENDOR_PRICE_DRIFT,
            **shared,
            cross_case=True,
            financial_impact=round(excess_per_unit * quantity, 2),
            financial_impact_basis=(
                f"This invoice's rate is {excess_per_unit:,.2f} above the "
                f"{drift['first_price']:,.2f} this vendor charged {drift['span_months']:.0f} "
                f"months ago; across {quantity:g} unit(s) that is the excess carried by this "
                f"invoice alone. The series total is larger."
            ),
            outstanding=drift.get("detail"),
            recommended_owner="Procurement",
            risk_level="high" if drift["increase_percent"] >= 3 * float(price_tol) else "medium",
        )

    # --- No exception found: everything matched or within tolerance ---
    # A real outcome, not a placeholder. The evidence chain still exists and
    # still proves something: that this invoice is payable.
    return MatchResult(
        exception_type=ExceptionType.NO_EXCEPTION,
        comparisons=comparisons,
        line_comparisons=line_comparisons,
        match_score=match_score,
        tolerance_source=tolerance_source,
        po_billing=billing or None,
        financial_impact=0.0,
        financial_impact_basis=(
            "Every comparison matched or fell within tolerance. Nothing is at risk on this invoice."
        ),
        recommended_owner="No action required",
        risk_level="low",
    )
