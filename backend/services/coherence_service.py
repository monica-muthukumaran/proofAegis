"""
coherence_service.py — do these documents describe the same transaction?

Every check in matching_service.py compares a field on the invoice against the
same field on the purchase order or goods receipt. All of them take one thing
for granted, and none of them verified it: that the two documents are about
the same order in the first place.

They are not always. A user uploads the wrong PO, or drops an unrelated
document into a case alongside the right ones, and the matcher compares them
anyway. The result is not a missing finding — it is a CONFIDENT WRONG ONE. An
invoice for 100 steel pipes against an order for 12 office chairs was reported
as a 211,200 quantity variance at high risk, with the basis "88 unreceived
units x implied unit price". 88 is 100 pipes minus 12 chairs. Every digit of
that finding was fabricated, and it was phrased exactly like a real one.

So this module runs BEFORE the variance branches and answers one question with
evidence attached:

    consistent   — the documents were checked and do belong together
    unverified   — something does not line up, but not enough to assert it
    contradicted — they demonstrably describe different transactions

WHY THE BAR IS SET WHERE IT IS

The failure modes are not symmetric.

Missing a mismatch leaves things as they were — the reviewer sees a variance
and, being a person looking at two documents, notices they are unrelated.
Wrongly declaring documents unrelated sends them to re-upload files that were
fine, and if it happens twice they stop believing the check. So `contradicted`
requires evidence a person would accept, and everything weaker is reported as
`unverified` rather than rounded up.

THE SIGNALS

Hard (any one is conclusive on its own):

  * `po_reference_conflict` — the invoice cites purchase order A and the
    purchase order on the case IS purchase order B. Both documents state a
    number, and the numbers are different. There is no reading of that where
    they belong to one order. This was already computed by
    ingestion_service._select_related and thrown away.
  * `receipt_reference_conflict` — the same, for the goods receipt.
  * `unrelated_line_items` — see below.

Soft (reported, never conclusive alone):

  * `no_descriptive_overlap` — both documents are itemised, both carry real
    descriptions, and they share no meaningful word.
  * `unverified_link` — a counterpart document was paired with the invoice on
    upload recency because nothing carried a matching reference.

WHY TEXT ALONE IS NOT ENOUGH

Zero word overlap looks conclusive and is not. A purchase order for "Annual
maintenance contract" and an invoice for "AMC renewal Q1 FY26" share no word
at all, and are the same transaction. Reporting that as unrelated documents
would be wrong in a way that is very hard for a reviewer to argue with.

What separates that case from the steel-pipes one is the MONEY. The AMC
invoice is 30,000 against a 120,000 order — a quarter of it, exactly what a
partial billing looks like. The steel invoice is 240,000 against a 54,000
order. So `unrelated_line_items` fires only when the descriptions share
nothing AND the invoice total is more than the order could account for. Two
independent dimensions have to disagree, and a partial billing — the common,
legitimate case — can never trigger it, because a smaller invoice is always
explicable by its order.

RELATIONSHIP TO group_by_reference

ingestion_service.group_by_reference already warns at UPLOAD time when one
batch carries documents stating two different purchase order numbers, so a
person can split the batch before anything is analysed. It is the better place
to catch that, and it catches it earlier.

What it cannot see is the case this module exists for: documents whose stated
references agree, or are absent, and whose CONTENTS do not belong together.
That is the shape a user hits when they drop an unrelated document into a case
alongside the right ones, and it survived the upload warning untouched.

The two overlap on purpose. An upload warning a person clicked past is not a
reason to compute a fabricated variance an hour later.

WHAT THIS IS NOT

It is not a judgement about whether the RIGHT documents were uploaded, and it
never asks a model. Everything here is arithmetic and string comparison over
fields already extracted, for the same reason the rest of the deterministic
core is: a reviewer must be able to check the reasoning, and "the two
documents share no word and the invoice is 4.4x the order" is checkable in a
way that "the model thought they looked unrelated" is not.
"""
from __future__ import annotations

import re
from typing import Optional

CONSISTENT = "consistent"
UNVERIFIED = "unverified"
CONTRADICTED = "contradicted"

# How far above the order's value an invoice may sit before the order stops
# being able to explain it. Generous on purpose: this is not the over-billing
# check (that is history_service.cumulative_billing, and it is allowed to be
# precise because it has already established the documents belong together).
# Here the number only has to rule out "this could be a normal billing of that
# order" before a text signal is allowed to become conclusive, so it is set
# where an honest over-billing would still fall below it.
_EXPLICABLE_MULTIPLE = 1.5

# Words that carry no product identity. Two documents sharing only "the" and
# "of" share nothing, and without this list they would look related.
_STOPWORDS = frozenset({
    "and", "for", "the", "with", "per", "each", "unit", "units", "item",
    "items", "nos", "no", "qty", "quantity", "rate", "amount", "total",
    "including", "incl", "excluding", "excl", "tax", "gst", "supply",
    "supplied", "delivery", "delivered", "charges", "charge", "service",
    "services", "work", "works", "job", "misc", "other", "others", "sub",
    "part", "parts", "set", "sets", "pcs", "pieces", "assorted", "various",
    # Catalogue-reference words. They appear on both documents whatever the
    # goods are, so they establish nothing when shared and nothing when not.
    "sku", "code", "ref", "reference", "model", "type", "line", "description",
})

# How many meaningful words a document's descriptions must carry before an
# overlap comparison is worth making.
#
# One is not enough, and "SKU 4471" is why: it reduces to the single token
# "sku", which is non-empty, so a document that says nothing about its goods
# looked comparable and its zero overlap with "Mild steel pipe" looked like
# evidence. Two independent words is the point at which their joint absence
# from the other document means something.
_MIN_DESCRIPTIVE_TOKENS = 2

# A token has to be at least this long to count as descriptive. "MS" and "50"
# are real content on a pipe spec but far too common to establish that two
# documents are about the same thing.
_MIN_TOKEN_LENGTH = 3


def _tokens(description) -> set[str]:
    """Meaningful words in a line description, lowercased.

    Digits are kept when attached to letters (`50mm`, `4471a`) and dropped
    when standalone: a bare "12" appearing on both documents says nothing
    about whether they describe the same goods.
    """
    words = re.split(r"[^a-z0-9]+", str(description or "").lower())
    return {
        word for word in words
        if len(word) >= _MIN_TOKEN_LENGTH
        and word not in _STOPWORDS
        and not word.isdigit()
    }


def _descriptive_tokens(line_items) -> set[str]:
    """Every meaningful word across a document's line items.

    Returns empty when the document is not itemised, when its descriptions are
    all codes and stock phrases, or when they carry fewer than
    _MIN_DESCRIPTIVE_TOKENS meaningful words in total.

    Empty means NOT COMPARABLE, and the caller must treat it as "no signal
    available" rather than as "no overlap" — a purchase order listing "SKU
    4471" against an invoice listing "Mild steel pipe 50mm" has nothing to
    compare, and calling that a contradiction would fire on every terse
    purchase order in the corpus.
    """
    tokens: set[str] = set()
    for line in line_items or []:
        tokens |= _tokens((line or {}).get("description"))
    return tokens if len(tokens) >= _MIN_DESCRIPTIVE_TOKENS else set()


def _reference_key(value) -> str:
    """A comparable form of a purchase order number.

    Punctuation and case are dropped because the same order is written
    "PO-2026-00421", "po 2026 00421" and "PO/2026/00421" across three
    documents from the same vendor. What is NOT dropped is any digit — the
    whole point of this comparison is that 00421 and 00422 are different
    orders.
    """
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _signal(code: str, strength: str, detail: str, **extra) -> dict:
    return {"code": code, "strength": strength, "detail": detail, **extra}


def _explicable_by_order(invoice_total, po_total) -> Optional[bool]:
    """Whether the order could account for an invoice of this size.

    None when either figure is missing or non-positive — absence is not
    evidence, and a zero order value would make every invoice look
    inexplicable.

    A SMALLER invoice is always explicable: partial billing, staged delivery
    and a quarterly draw against an annual contract are all normal, and none
    of them mean the documents are unrelated.
    """
    try:
        invoice = float(invoice_total)
        order = float(po_total)
    except (TypeError, ValueError):
        return None
    if invoice <= 0 or order <= 0:
        return None
    return invoice <= order * _EXPLICABLE_MULTIPLE


def assess(case: dict, link_warnings: Optional[list[dict]] = None) -> dict:
    """The coherence verdict for one case, with its evidence.

    `case` is the same normalized matching_input evaluate_exception receives.
    `link_warnings` come from ingestion_service._select_related — how the
    counterpart documents were chosen, which is evidence in its own right.

    Always returns a dict, including when there is nothing to check: a case
    with no purchase order has no coherence question, and saying so is more
    useful than an absent field the UI has to guess about.
    """
    signals: list[dict] = []

    if not case.get("purchase_order_exists", True):
        return {
            "verdict": CONSISTENT,
            "checked": False,
            "signals": [],
            "summary": "No purchase order on this case, so there is nothing to cross-check the invoice against.",
        }

    # --- Hard: the two documents name different orders --------------------
    invoice_reference = _reference_key(case.get("invoice_po_number"))
    po_reference = _reference_key(case.get("po_number"))
    if invoice_reference and po_reference and invoice_reference != po_reference:
        signals.append(_signal(
            "po_reference_conflict", "hard",
            f"The invoice cites purchase order {case.get('invoice_po_number')}, but the "
            f"purchase order on this case is {case.get('po_number')}. They are different orders.",
            invoice_reference=case.get("invoice_po_number"),
            document_reference=case.get("po_number"),
        ))

    receipt_reference = _reference_key(case.get("receipt_po_number"))
    if receipt_reference and invoice_reference and receipt_reference != invoice_reference:
        signals.append(_signal(
            "receipt_reference_conflict", "hard",
            f"The goods receipt records a delivery against purchase order "
            f"{case.get('receipt_po_number')}, but the invoice cites "
            f"{case.get('invoice_po_number')}.",
            invoice_reference=case.get("invoice_po_number"),
            document_reference=case.get("receipt_po_number"),
        ))

    # --- Text and money, which are only conclusive together ---------------
    po_tokens = _descriptive_tokens(case.get("po_line_items"))
    invoice_tokens = _descriptive_tokens(case.get("invoice_line_items"))
    comparable_descriptions = bool(po_tokens and invoice_tokens)
    shared = po_tokens & invoice_tokens

    if comparable_descriptions and not shared:
        explicable = _explicable_by_order(case.get("invoice_total") or case.get("invoice_amount"),
                                          case.get("po_total"))
        ordered = _preview(case.get("po_line_items"))
        billed = _preview(case.get("invoice_line_items"))
        if explicable is False:
            signals.append(_signal(
                "unrelated_line_items", "hard",
                f"The order is for {ordered} and the invoice bills for {billed} — no shared "
                f"description between them — and the invoice total exceeds what this order "
                f"could account for. These are two different transactions, not a variance on one.",
                ordered=ordered, billed=billed,
            ))
        else:
            # Descriptions disagree but the money is consistent with a normal
            # billing of this order. That is what a rewording looks like — an
            # annual maintenance contract billed as "AMC renewal Q1" — so it
            # is reported and not asserted.
            signals.append(_signal(
                "no_descriptive_overlap", "soft",
                f"The order describes {ordered} and the invoice describes {billed}, with no "
                f"wording in common. The amounts are consistent with this order, so the two may "
                f"simply be worded differently — confirm they are the same items.",
                ordered=ordered, billed=billed,
            ))

    # --- Different vendors, as corroboration only -------------------------
    # Never decisive here. A vendor difference on documents that otherwise
    # agree is exception_type VENDOR_MISMATCH — a possible payment diversion,
    # which is a far more specific and more serious finding than "wrong file
    # uploaded", and the matcher must be left free to report it. What this
    # signal does is explain a contradiction already established by other
    # means: told the documents describe different orders, a reviewer's next
    # question is "how different", and "a different vendor as well" answers it.
    from services.matching_service import vendor_key  # noqa: PLC0415 — circular at module load

    invoice_vendor = vendor_key(case.get("vendor_name"))
    po_vendor = vendor_key(case.get("po_vendor_name"))
    if invoice_vendor and po_vendor and invoice_vendor != po_vendor:
        signals.append(_signal(
            "different_vendor", "context",
            f"The order was raised on {case.get('po_vendor_name')} and the invoice is from "
            f"{case.get('vendor_name')}.",
        ))

    # --- How the counterpart documents were chosen ------------------------
    for warning in link_warnings or []:
        # A reference_mismatch warning describes the same fact as
        # po_reference_conflict above, from the selection side. Recording both
        # would double-count one piece of evidence and make a single problem
        # look like two.
        if warning.get("code") == "reference_mismatch" and any(
                s["code"] in ("po_reference_conflict", "receipt_reference_conflict") for s in signals):
            continue
        signals.append(_signal(
            warning.get("code", "unverified_link"), "soft",
            warning.get("detail", "A document was paired with the invoice without a confirmed reference."),
            role=warning.get("role"),
        ))

    hard = [s for s in signals if s["strength"] == "hard"]
    soft = [s for s in signals if s["strength"] == "soft"]
    if hard:
        verdict = CONTRADICTED
        summary = hard[0]["detail"]
    elif soft:
        verdict = UNVERIFIED
        summary = soft[0]["detail"]
    elif signals:
        # Context-only signals. A different vendor with everything else in
        # agreement is VENDOR_MISMATCH's business, not a coherence problem, so
        # the verdict stays consistent and the observation is carried anyway.
        verdict = CONSISTENT
        summary = ("The documents describe the same order. "
                   + signals[0]["detail"])
    else:
        verdict = CONSISTENT
        summary = ("The invoice, purchase order and goods receipt were checked against each other "
                   "and describe the same order.")

    return {
        "verdict": verdict,
        "checked": True,
        "signals": signals,
        "summary": summary,
    }


def _preview(line_items, limit: int = 2) -> str:
    """A short, readable description of what a document is for.

    Used in the finding's own sentence, so a reviewer can see WHY the two
    documents were called unrelated without opening either of them — "the
    order is for ergonomic office chairs and the invoice bills for MS steel
    pipe" settles it in one line.
    """
    descriptions = [str((line or {}).get("description") or "").strip()
                    for line in (line_items or [])]
    descriptions = [d for d in descriptions if d]
    if not descriptions:
        return "unspecified items"
    shown = descriptions[:limit]
    text = "; ".join(shown)
    if len(descriptions) > limit:
        text += f" (+{len(descriptions) - limit} more)"
    return text


def is_contradicted(coherence: Optional[dict]) -> bool:
    return bool(coherence) and coherence.get("verdict") == CONTRADICTED
