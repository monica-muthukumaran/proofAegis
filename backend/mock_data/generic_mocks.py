"""
generic_mocks.py — fallback reasoning and resolution drafts for cases that
have no hand-written mock.

mock_extractions.py covers the three seeded demo cases by exception_id. A
case a user creates by uploading PDFs has no such entry, and the old
behaviour was a 500 `no_mock_available_for_this_case` — meaning the moment
you built a real case, the two AI-backed features stopped working entirely
whenever Gemini was off or failed.

These builders close that hole without inventing anything. Every number and
every citation is read from the deterministic MatchResult and the case's
real source documents; the only thing being templated is the English around
them. That keeps the product boundary intact — the text is generated, the
figures are computed — and it means the fallback path is honest enough to
demo rather than something to hide.
"""
from __future__ import annotations

from typing import Optional

from schemas import (
    Citation,
    ExceptionReasoning,
    ExceptionType,
    MatchResult,
    ResolutionDraft,
    Severity,
)

_SEVERITY_BY_RISK = {
    "low": Severity.LOW,
    "medium": Severity.MEDIUM,
    "high": Severity.HIGH,
    "critical": Severity.CRITICAL,
}

_ACTION_BY_TYPE = {
    ExceptionType.PRICE_VARIANCE: (
        "Request a corrected invoice at the purchase-order price, or written confirmation of an agreed price change."
    ),
    ExceptionType.QUANTITY_VARIANCE: (
        "Ask Receiving to confirm whether the uninvoiced balance is still in transit before releasing payment."
    ),
    ExceptionType.MISSING_GOODS_RECEIPT: (
        "Obtain a goods receipt or written service-completion confirmation from the requesting business unit."
    ),
    ExceptionType.MISSING_PURCHASE_ORDER: (
        "Locate the approving purchase order, or route the invoice for retrospective procurement approval."
    ),
    ExceptionType.VENDOR_MISMATCH: (
        "Confirm the vendor record against the approved supplier master before proceeding."
    ),
    ExceptionType.TAX_TOTAL_MISMATCH: (
        "Ask the vendor to reissue the invoice with corrected tax and total figures."
    ),
    ExceptionType.DUPLICATE_INVOICE: (
        "Check the prior submission before paying; hold this invoice until the duplicate is ruled out."
    ),
}


def _money(value: float, currency: str = "INR") -> str:
    return f"{currency} {value:,.2f}".rstrip("0").rstrip(".") if value % 1 else f"{currency} {value:,.0f}"


def _variance_sentence(match_result: MatchResult) -> str:
    """Describes the comparison that actually drove the exception, using the
    computed figures rather than a generic phrase."""
    for cmp in match_result.comparisons:
        if cmp.classification.value == "outside_tolerance" and cmp.percentage_variance is not None:
            return (
                f"The {cmp.field.value.replace('_', ' ')} on the invoice is {cmp.actual_value}, "
                f"against an expected {cmp.expected_value} — a variance of "
                f"{cmp.percentage_variance:.2f}%, outside the {cmp.tolerance_percent}% tolerance."
            )
    for cmp in match_result.comparisons:
        if cmp.classification.value == "outside_tolerance":
            return (
                f"The {cmp.field.value.replace('_', ' ')} on the invoice ({cmp.actual_value}) does not "
                f"match the expected value ({cmp.expected_value})."
            )
    return "No comparison fell outside the configured tolerance."


def build_reasoning_fallback(match_result: MatchResult, rejection_notice_text: str = "") -> ExceptionReasoning:
    """Deterministic ExceptionReasoning built from the computed MatchResult.
    exception_agent.py's guardrail still runs over this, so financial_impact
    and requires_human_review are enforced the same way as for a live model."""
    detail = _variance_sentence(match_result)
    if match_result.exception_type == ExceptionType.MISSING_GOODS_RECEIPT:
        detail = (
            "No goods receipt or service confirmation is on file for this invoice, so the amount "
            "billed cannot be verified against anything actually received."
        )
    elif match_result.exception_type == ExceptionType.MISSING_PURCHASE_ORDER:
        detail = (
            "No purchase order is on file for this invoice, so there is no approved price or "
            "quantity to check the billed amount against."
        )

    description = f"{detail} {match_result.financial_impact_basis}".strip()
    if rejection_notice_text:
        description = f"{description} The rejection notice recorded: \"{rejection_notice_text}\"."

    return ExceptionReasoning(
        exception_type=match_result.exception_type,
        severity=_SEVERITY_BY_RISK.get(match_result.risk_level, Severity.MEDIUM),
        description=description,
        financial_impact=match_result.financial_impact,
        recommended_owner=match_result.recommended_owner,
        recommended_action=_ACTION_BY_TYPE.get(
            match_result.exception_type, "Review the supporting documents and confirm the correct figures."
        ),
        # Deliberately not 0.9-something: this is a template over computed
        # values, and overstating certainty would be the dishonest choice.
        confidence=0.75,
        requires_human_review=True,
    )


def _citations_from(match_result: MatchResult, source_documents: dict) -> list[Citation]:
    """One citation per evaluable comparison, pointed at the document that
    actually supplied the value. Never emits a citation for a document the
    case does not hold."""
    invoice_id = source_documents.get("vendor_invoice")
    po_id = source_documents.get("purchase_order")
    grn_id = source_documents.get("goods_receipt_note")

    citations: list[Citation] = []
    for cmp in match_result.comparisons:
        if not cmp.evaluable or cmp.actual_value is None:
            continue
        field = cmp.field.value
        if field == "quantity" and grn_id:
            citations.append(Citation(claim=f"Received quantity {cmp.expected_value}",
                                       source_document_id=grn_id, source_field="received_quantity"))
        if field in ("unit_price", "quantity", "total", "tax") and invoice_id:
            citations.append(Citation(claim=f"Invoice {field.replace('_', ' ')} {cmp.actual_value}",
                                       source_document_id=invoice_id, source_field=field))
        if field in ("unit_price", "total") and po_id and cmp.expected_value is not None:
            citations.append(Citation(claim=f"Purchase order {field.replace('_', ' ')} {cmp.expected_value}",
                                       source_document_id=po_id, source_field=field))

    if not citations and invoice_id:
        citations.append(Citation(claim="Invoice on file", source_document_id=invoice_id,
                                   source_field="total_amount"))
    return citations


def build_resolution_fallback(match_result: MatchResult, case_context: dict,
                               source_documents: Optional[dict] = None) -> ResolutionDraft:
    """Deterministic ResolutionDraft. Cited, human-review-flagged, and built
    only from figures matching_service.py computed."""
    source_documents = source_documents or {}
    invoice_id = case_context.get("invoice_id") or "this invoice"
    vendor_name = case_context.get("vendor_name") or "the vendor"
    currency = case_context.get("currency", "INR")

    subject_by_type = {
        ExceptionType.PRICE_VARIANCE: f"Price variance on {invoice_id} — request for correction",
        ExceptionType.QUANTITY_VARIANCE: f"Quantity variance on {invoice_id} — confirmation needed",
        ExceptionType.MISSING_GOODS_RECEIPT: f"Missing goods receipt for {invoice_id} — confirmation needed",
        ExceptionType.MISSING_PURCHASE_ORDER: f"No purchase order on file for {invoice_id}",
    }
    subject = subject_by_type.get(match_result.exception_type, f"Query on {invoice_id}")

    body = (
        f"Hello,\n\n"
        f"We are holding invoice {invoice_id} from {vendor_name} pending clarification.\n\n"
        f"{_variance_sentence(match_result)}\n\n"
        f"Amount affected: {_money(match_result.financial_impact, currency)}. "
        f"{match_result.financial_impact_basis}\n\n"
        f"{_ACTION_BY_TYPE.get(match_result.exception_type, 'Could you confirm the correct figures?')}\n\n"
        f"Thanks,\nAccounts Payable"
    )

    return ResolutionDraft(
        subject=subject,
        body=body,
        citations=_citations_from(match_result, source_documents),
        recommended_owner=match_result.recommended_owner,
        requires_human_review=True,
    )
