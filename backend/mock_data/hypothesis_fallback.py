"""
hypothesis_fallback.py — what the hypothesis agent degrades to with no model.

This fallback is deliberately WORSE than the agent, and that is worth stating
plainly because it is the opposite of how the other fallbacks in this project
work. mock_data/generic_mocks.py produces a description and a resolution draft
that are genuinely close to what Gemini returns, which is why those two agents
read as decorative — a template does the job.

Here a template cannot. The value of a hypothesis set is the RANKING, and
ranking requires weighing a candidate cause against what this vendor has been
doing for six months. A lookup table keyed on exception type can list the
usual causes; it cannot know that this particular supplier's rate has been
climbing since April and that a "one-off keying error" is therefore the least
likely explanation on the list.

So this returns the standard checks for the exception type, in a fixed order,
and the API marks the response `source: "mock"` so the UI can say the ranking
is generic rather than reasoned. An honest degradation, labelled.
"""
from __future__ import annotations

from schemas import ExceptionType, MatchResult

# Keyed on exception type. Each entry is the ordinary set of checks an AP
# reviewer would run, written the way this product writes them: name the
# document, and say what each outcome means.
_CATALOGUE: dict[str, list[dict]] = {
    ExceptionType.PRICE_VARIANCE.value: [
        {
            "cause": "The vendor has applied a revised rate card that we do not have on file.",
            "evidence_to_check": "A price revision notice or updated rate card dated after the purchase order.",
            "confirms_if": "A revision notice exists and its effective date precedes the invoice date.",
            "rules_out_if": "No revision exists, or its effective date is after this invoice.",
            "where_to_look": "Vendor correspondence and the contract file.",
        },
        {
            "cause": "The purchase order carries a stale rate that was never updated from the quotation.",
            "evidence_to_check": "The quotation the purchase order was raised from.",
            "confirms_if": "The quotation shows the invoiced rate and the order shows the older one.",
            "rules_out_if": "The quotation agrees with the order.",
            "where_to_look": "The procurement file for this order.",
        },
        {
            "cause": "The invoice line was matched against the wrong order line.",
            "evidence_to_check": "The HSN/SAC codes and item descriptions on both documents.",
            "confirms_if": "The codes differ, or two order lines have similar descriptions.",
            "rules_out_if": "The codes and descriptions agree.",
            "where_to_look": "Both documents, side by side.",
        },
    ],
    ExceptionType.QUANTITY_VARIANCE.value: [
        {
            "cause": "Part of the order is still in transit and will be receipted later.",
            "evidence_to_check": "The delivery note or transport document for the balance.",
            "confirms_if": "A dispatch record exists for the unreceipted units.",
            "rules_out_if": "The vendor's dispatch records show the full quantity already delivered.",
            "where_to_look": "Receiving, and the vendor's dispatch confirmation.",
        },
        {
            "cause": "The goods arrived but the receipt was raised late or for a partial quantity.",
            "evidence_to_check": "The gate entry or security log against the receipt.",
            "confirms_if": "The gate entry shows more units than the receipt records.",
            "rules_out_if": "The gate entry and receipt agree.",
            "where_to_look": "The receiving log for the delivery date.",
        },
        {
            "cause": "The vendor invoiced the ordered quantity rather than the delivered quantity.",
            "evidence_to_check": "Whether the invoiced quantity equals the ordered quantity exactly.",
            "confirms_if": "It matches the order and not the receipt.",
            "rules_out_if": "It matches neither.",
            "where_to_look": "The purchase order.",
        },
    ],
    ExceptionType.MISSING_GOODS_RECEIPT.value: [
        {
            "cause": "The delivery happened and nobody raised the receipt.",
            "evidence_to_check": "A signed delivery note or the requester's confirmation.",
            "confirms_if": "Someone in the business unit confirms receipt.",
            "rules_out_if": "Nobody can confirm the goods or service arrived.",
            "where_to_look": "The requesting business unit.",
        },
        {
            "cause": "This is a service with nothing physical to receive, so no receipt was ever expected.",
            "evidence_to_check": "The order's HSN/SAC codes and the description of what was bought.",
            "confirms_if": "The codes are service codes, or the work is billed as a period.",
            "rules_out_if": "The order is for goods.",
            "where_to_look": "The purchase order.",
        },
        {
            "cause": "The invoice was raised before the work was delivered.",
            "evidence_to_check": "The invoice date against the contracted delivery or service window.",
            "confirms_if": "The invoice predates the period it bills for.",
            "rules_out_if": "The dates are consistent.",
            "where_to_look": "The contract or order terms.",
        },
    ],
    ExceptionType.DUPLICATE_INVOICE.value: [
        {
            "cause": "The vendor re-sent an unpaid invoice as a reminder.",
            "evidence_to_check": "Whether the earlier invoice was ever paid.",
            "confirms_if": "The earlier one is unpaid and this is the same document.",
            "rules_out_if": "The earlier one was paid, in which case this is a second claim.",
            "where_to_look": "The payment record for the earlier invoice.",
        },
        {
            "cause": "Two genuine deliveries were billed at the same amount.",
            "evidence_to_check": "The delivery or service dates each invoice covers.",
            "confirms_if": "They cover different periods or different deliveries.",
            "rules_out_if": "They cover the same one.",
            "where_to_look": "Both invoices and their goods receipts.",
        },
        {
            "cause": "The invoice was submitted through two channels — email and the portal — and both were captured.",
            "evidence_to_check": "How each copy arrived.",
            "confirms_if": "The two copies came in by different routes on close dates.",
            "rules_out_if": "Both arrived the same way.",
            "where_to_look": "The intake record on each case.",
        },
    ],
    ExceptionType.PAYMENT_DETAILS_CHANGED.value: [
        {
            "cause": "The vendor genuinely changed banks and told us through a channel we did not record.",
            "evidence_to_check": "A bank-change instruction on vendor letterhead, verified by calling a number already on file.",
            "confirms_if": "A known contact confirms the change on a number taken from the vendor master, not from this invoice.",
            "rules_out_if": "No such instruction exists, or the contact cannot be reached on a known number.",
            "where_to_look": "The vendor master record — never the contact details printed on this invoice.",
        },
        {
            "cause": "The invoice was intercepted and altered in transit.",
            "evidence_to_check": "The sending address and mail headers against previous invoices from this vendor.",
            "confirms_if": "The domain or address differs subtly from the one used before.",
            "rules_out_if": "It arrived from the address used for every previous invoice.",
            "where_to_look": "The email intake record.",
        },
    ],
    ExceptionType.PO_OVER_BILLED.value: [
        {
            "cause": "The order was varied upward and the amendment was never recorded.",
            "evidence_to_check": "A change order or amendment against this purchase order.",
            "confirms_if": "An approved amendment covers the additional value.",
            "rules_out_if": "The order stands at its original value.",
            "where_to_look": "The procurement file.",
        },
        {
            "cause": "An invoice was billed against the wrong order number.",
            "evidence_to_check": "Whether every invoice in the running total describes the same goods as this order.",
            "confirms_if": "One of them describes something the order does not cover.",
            "rules_out_if": "All of them match the order's lines.",
            "where_to_look": "The earlier invoices named in the billing summary.",
        },
    ],
    ExceptionType.VENDOR_PRICE_DRIFT.value: [
        {
            "cause": "Each order was raised at the vendor's then-current rate, so no single invoice ever breached tolerance.",
            "evidence_to_check": "Whether the purchase orders themselves rose in step with the invoices.",
            "confirms_if": "Each order matches its own invoice and the orders climb together.",
            "rules_out_if": "The orders held a flat rate and only the invoices rose.",
            "where_to_look": "The purchase orders across the period.",
        },
        {
            "cause": "An indexation or escalation clause in the contract is being applied as agreed.",
            "evidence_to_check": "The contract's price escalation terms.",
            "confirms_if": "The contract permits an increase at about this cadence.",
            "rules_out_if": "The contract fixes the rate for the period.",
            "where_to_look": "The signed contract or framework agreement.",
        },
        {
            "cause": "Nobody re-tendered, and the rate drifted because no one was comparing to the original.",
            "evidence_to_check": "When this line was last competitively quoted.",
            "confirms_if": "The last quotation predates the drift.",
            "rules_out_if": "A recent quotation supports the current rate.",
            "where_to_look": "Procurement's sourcing record.",
        },
    ],
}

# Used for any exception type with no specific catalogue entry. Generic, and
# labelled as such rather than dressed up.
_DEFAULT = [
    {
        "cause": "The documents on file describe different transactions.",
        "evidence_to_check": "That the invoice, order and receipt all name the same order reference.",
        "confirms_if": "One of them references a different order.",
        "rules_out_if": "All three agree on the reference.",
        "where_to_look": "The documents tab on this case.",
    },
    {
        "cause": "A value was mis-read from one of the documents.",
        "evidence_to_check": "The extracted fields against the source PDF.",
        "confirms_if": "A field on the page differs from what was extracted.",
        "rules_out_if": "Every extracted value matches the page.",
        "where_to_look": "The document preview, which shows both.",
    },
]


def build_hypothesis_fallback(match_result: MatchResult, document_types: list[str]):
    """A generic, unranked checklist for this exception type.

    Imported lazily by the agent to avoid a circular import at module load.
    """
    from services.hypothesis_agent import Hypothesis, HypothesisSet

    entries = _CATALOGUE.get(match_result.exception_type.value, _DEFAULT)
    return HypothesisSet(
        finding=match_result.exception_type.value.replace("_", " "),
        hypotheses=[
            Hypothesis(
                rank=index,
                # Confidence descends by position, and the position is the
                # catalogue's fixed order rather than a judgement about this
                # case. Kept low across the board so the numbers do not
                # pretend to a precision that a lookup table does not have.
                likelihood=round(max(0.2, 0.55 - 0.1 * (index - 1)), 2),
                **entry,
            )
            for index, entry in enumerate(entries, start=1)
        ],
        what_would_change_this=(
            "These are the standard checks for this exception type, in a fixed order. They are "
            "not ranked against this vendor's own history — that requires the reasoning model, "
            "which did not answer."
        ),
    )
