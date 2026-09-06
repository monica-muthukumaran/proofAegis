"""
pdf_field_parser.py — deterministic classification + field extraction from
the text PyMuPDF pulls out of a PDF. No LLM, no network, no cost.

Why this exists alongside document_agent.py's Gemini extraction:

  1. It gives every uploaded document a REAL extraction derived from the
     actual bytes the user uploaded, even with no Gemini key and no budget.
     "Mock mode" for an uploaded file previously meant hand-written constants
     for three seeded cases — which is fine for those three and useless for a
     document a judge drags in during the demo.
  2. It is the fallback `mock_fn` for the ADK extraction agent, so
     call_gemini_with_fallback degrades to something honest and traceable
     rather than to fiction.
  3. It is a cross-check: when Gemini IS live, a disagreement between the
     parser and the model on a numeric field is a signal worth surfacing
     rather than averaging away.

Confidence here is a real signal, not decoration: a field found under an
explicit label scores high, one recovered by a looser positional heuristic
scores lower, and an absent field is simply absent (never invented).
"""
from __future__ import annotations

import re
from typing import Optional

import fitz  # PyMuPDF — page.find_tables()

from schemas import (
    ExtractionConfidence,
    GoodsReceiptExtraction,
    InvoiceExtraction,
    LineItem,
    PurchaseOrderExtraction,
    QuotationExtraction,
    RejectionNoticeExtraction,
)

DOCUMENT_TYPES = ("vendor_invoice", "purchase_order", "goods_receipt_note",
                  "rejection_notice", "quotation")

# Classification is scored, not first-match-wins. First-match-wins got this
# wrong in an obvious way: a vendor invoice carries a "PO Number:" field, so
# any rule that treats "po number" as evidence of a purchase order
# misclassifies every invoice ever written.
#
# Two tiers, and where a phrase appears matters as much as whether it appears:
#   TITLE  — what the document calls itself. Decisive.
#   FIELD  — a label that merely *mentions* another document. Weak evidence.
# A title phrase inside the first TITLE_ZONE characters scores triple, because
# that is where a document names itself rather than references something else.
_TITLE_PHRASES = {
    "rejection_notice": ("rejection notice", "invoice rejection", "rejected invoice", "debit note"),
    "goods_receipt_note": ("goods receipt note", "goods receipt", "grn", "delivery note", "delivery receipt"),
    "purchase_order": ("purchase order", "p.o. number"),
    "vendor_invoice": ("vendor invoice", "tax invoice", "commercial invoice", "supplier invoice"),
    # A quotation names itself in many ways and, unlike an invoice, is
    # defined as much by what it is NOT: no invoice number, no amount due.
    "quotation": ("quotation", "quotation no", "estimate", "proforma", "pro forma",
                  "price quote", "quote no", "tender", "offer letter"),
}

_FIELD_PHRASES = {
    "rejection_notice": ("rejection reason", "rejected date", "rejected because"),
    "goods_receipt_note": ("received quantity", "quantity received", "receipt number", "receipt date"),
    "purchase_order": ("ordered quantity", "order value", "po amount"),
    "vendor_invoice": ("invoice number", "invoice no", "invoice date", "invoice amount", "total amount"),
    "quotation": ("quotation validity", "quote valid", "validity", "our ref", "estimate no"),
}

TITLE_ZONE = 400
_TITLE_IN_ZONE_WEIGHT = 3.0
_TITLE_WEIGHT = 1.0
_FIELD_WEIGHT = 0.4

_LABEL_CONFIDENCE = 0.96      # found under an explicit "Label:" heading
_HEURISTIC_CONFIDENCE = 0.72  # recovered by a looser pattern


def classify_document(text: str) -> tuple[Optional[str], float]:
    """
    Returns (document_type, confidence), or (None, 0.0) when the evidence is
    too thin — in which case the caller asks the user to set the type rather
    than guessing. Refusing to guess is the point: a misfiled document
    silently corrupts the matching input.
    """
    lowered = text.lower()
    title_zone = lowered[:TITLE_ZONE]

    scores: dict[str, float] = {t: 0.0 for t in DOCUMENT_TYPES}
    for doc_type, phrases in _TITLE_PHRASES.items():
        for phrase in phrases:
            if phrase in title_zone:
                scores[doc_type] += _TITLE_IN_ZONE_WEIGHT
            elif phrase in lowered:
                scores[doc_type] += _TITLE_WEIGHT
    for doc_type, phrases in _FIELD_PHRASES.items():
        for phrase in phrases:
            if phrase in lowered:
                scores[doc_type] += _FIELD_WEIGHT

    best_type = max(scores, key=lambda t: scores[t])
    best_score = scores[best_type]
    if best_score < 1.0:
        return None, 0.0

    # Confidence reflects how clearly the winner beat the runner-up, not just
    # how many words matched — a document that looks equally like two things
    # should not report 0.95.
    runner_up = max((v for t, v in scores.items() if t != best_type), default=0.0)
    margin = best_score - runner_up
    confidence = 0.60 + min(0.20, 0.04 * best_score) + min(0.18, 0.06 * margin)
    return best_type, round(min(0.98, confidence), 3)


# Text a PDF extractor returns rarely keeps a label and its value on the same
# line. Anything laid out in columns or table cells — which is most real
# invoices — comes back as "Total Amount:" on one line and "INR 265,000.00"
# on the next, because the two sit at different x positions. Both layouts
# therefore have to be understood:
#
#     Total Amount: INR 265,000.00      <- same line
#     Total Amount:                     <- label line
#     INR 265,000.00                    <-   value on the following line
#
# Labels anchor at line start, so "Quantity" never matches inside "Received
# Quantity" — those two mean different things to the matcher.
_MAX_VALUE_LOOKAHEAD = 2  # lines to scan past a bare label before giving up

_LABEL_ONLY_LINE = re.compile(r"^[A-Za-z][A-Za-z .#/]{1,28}[:\-]\s*$")


def _find_label(text: str, *labels: str) -> Optional[str]:
    """Finds a labelled value in either layout, case-insensitively. Returns
    the trimmed value, or None when the label is genuinely absent — never a
    placeholder, because 'not stated' and 'zero' are different facts."""
    lines = text.splitlines()
    for label in labels:
        # A trailing period belongs to the label, not the value. Real
        # documents print "Invoice No." and "PO No." far more often than
        # "Invoice No:", and requiring a colon made every one of them read
        # back as UNKNOWN.
        same_line = rf"^[ \t]*{re.escape(label)}\.?[ \t]*[:\-][ \t]*(.+?)[ \t]*$"
        bare_label = rf"^[ \t]*{re.escape(label)}\.?[ \t]*[:\-]?[ \t]*$"

        for index, line in enumerate(lines):
            match = re.match(same_line, line, re.IGNORECASE)
            if match and match.group(1).strip():
                return match.group(1).strip()

            if re.match(bare_label, line, re.IGNORECASE):
                for offset in range(1, _MAX_VALUE_LOOKAHEAD + 1):
                    if index + offset >= len(lines):
                        break
                    candidate = lines[index + offset].strip()
                    if not candidate:
                        continue
                    # A following line that is itself a label means this field
                    # was present but empty; don't steal the next field's value.
                    if _LABEL_ONLY_LINE.match(candidate):
                        break
                    return candidate
    return None


def _to_number(raw: Optional[str]) -> Optional[float]:
    """Parses a money/quantity token. Tolerates INR/₹ prefixes, thousands
    separators (including the Indian 1,80,000 grouping) and trailing units.
    Returns None rather than 0 when nothing numeric is present — the
    difference between 'zero' and 'not stated' matters to the matcher."""
    if raw is None:
        return None
    cleaned = raw.replace("₹", " ").replace(",", "")
    cleaned = re.sub(r"(?i)\b(inr|rs\.?|usd)\b", " ", cleaned)
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    try:
        return float(match.group(0))
    except ValueError:
        return None


def _confidences(found: dict[str, Optional[object]], heuristic_fields: set[str]) -> list[ExtractionConfidence]:
    out = []
    for name, value in found.items():
        if value is None:
            continue
        out.append(ExtractionConfidence(
            field_name=name,
            confidence=_HEURISTIC_CONFIDENCE if name in heuristic_fields else _LABEL_CONFIDENCE,
        ))
    return out


# A reference number as real systems write it: PO/SRPL/26/19451,
# PO-SRPL-26-19451, SES/1371/8. The old pattern (PO[-/][A-Z0-9-]+) stopped at
# the first slash, so PO/SRPL/26/19451 was captured as "PO/SRPL" and no two
# documents about the same order could ever be linked.
_REFERENCE = re.compile(r"(?i)\b([A-Z]{2,6}(?:[-/][A-Z0-9]{1,8}){1,5})\b")


def find_reference(text: str, prefix: str) -> Optional[str]:
    """The longest reference starting with `prefix` that contains a digit."""
    candidates = []
    for match in _REFERENCE.finditer(text):
        value = match.group(1)
        if not value.upper().startswith(prefix.upper()):
            continue
        if not any(ch.isdigit() for ch in value):
            continue
        candidates.append(value)
    if not candidates:
        return None
    return max(candidates, key=len)


def _scalars_from_lines(line_items, quantity, unit_price, heuristic):
    """The single quantity/unit_price pair, or None when no single pair is true.

    One row: that row's values. Several rows: both stay absent — see LineItem
    in schemas.py for why filling them was actively harmful.
    """
    if len(line_items) == 1:
        only = line_items[0]
        if quantity is None and only.quantity is not None:
            quantity = only.quantity
            heuristic.add("quantity")
        if unit_price is None and only.unit_price is not None:
            unit_price = only.unit_price
            heuristic.add("unit_price")
        return quantity, unit_price
    if len(line_items) > 1:
        return None, None
    return quantity, unit_price


# ---------------------------------------------------------------------------
# Payment instructions and tax identity
# ---------------------------------------------------------------------------
# Read so that a CHANGE can be detected against the vendor's previous invoice
# (services/history_service.py). Nothing here validates an account — that
# would be bank-account verification, which this product is explicitly not.

# An Indian IFSC is four letters, a zero, then six alphanumerics. The shape is
# strict enough to find without a label, which matters because plenty of
# invoices print it inside a payment block rather than against a heading.
_IFSC = re.compile(r"\b([A-Z]{4}0[A-Z0-9]{6})\b")
# GSTIN: 2-digit state code, 10-character PAN, then 3 more.
_GSTIN = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][A-Z0-9]{3})\b")


def find_bank_details(text: str) -> dict:
    """account number / IFSC / bank name, where the invoice states them."""
    details = {}

    account = _find_label(
        text, "A/c No", "A/c Number", "Account No", "Account Number",
        "Bank Account", "Bank A/c", "Current A/c No")
    if account:
        digits = re.sub(r"[^0-9]", "", account)
        # Indian account numbers run roughly 9-18 digits. Anything shorter is
        # a fragment of something else that happened to sit under the label.
        if 8 <= len(digits) <= 20:
            details["bank_account_number"] = digits

    ifsc = _find_label(text, "IFSC Code", "IFSC", "IFS Code")
    if ifsc:
        match = _IFSC.search(ifsc.upper())
        if match:
            details["bank_ifsc"] = match.group(1)
    if "bank_ifsc" not in details:
        match = _IFSC.search(text.upper())
        if match:
            details["bank_ifsc"] = match.group(1)

    bank_name = _find_label(text, "Bank Name", "Bank", "Banker", "Bank Details")
    if bank_name and len(bank_name) < 80:
        details["bank_name"] = bank_name

    return details


def find_tax_id(text: str) -> Optional[str]:
    """The SUPPLIER's GSTIN.

    An invoice carries at least two: the supplier's and the buyer's. The
    supplier's is the one printed in the issuer block at the top, so the FIRST
    occurrence is taken. A labelled "GSTIN/UIN" under a "Buyer" heading is not
    distinguished here — this is a best-effort read, and the field is used for
    display and change detection rather than for any payment decision.
    """
    labelled = _find_label(text, "GST NO", "GSTIN", "GSTIN/UIN", "GST Number", "Tax ID")
    if labelled:
        match = _GSTIN.search(labelled.upper())
        if match:
            return match.group(1)
    match = _GSTIN.search(text.upper())
    return match.group(1) if match else None


def parse_invoice(text: str, pdf_bytes: Optional[bytes] = None) -> InvoiceExtraction:
    heuristic: set[str] = set()

    invoice_number = _find_label(text, "Invoice Number", "Invoice No", "Invoice #")
    if invoice_number is None:
        match = re.search(r"\bINV[-/][A-Z0-9\-]+", text, re.IGNORECASE)
        invoice_number = match.group(0) if match else None
        if invoice_number:
            heuristic.add("invoice_number")

    vendor_name = find_vendor_name(text)
    if vendor_name and not _find_label(text, "Vendor", "Vendor Name", "Supplier", "Billed By"):
        heuristic.add("vendor_name")
    po_number = _find_label(text, "PO Number", "Purchase Order", "PO No", "P.O. Number",
                            "Buyer's Order No")
    if po_number is None or not any(ch.isdigit() for ch in po_number):
        recovered = find_reference(text, "PO")
        if recovered:
            po_number = recovered
            heuristic.add("po_number")

    quantity = _to_number(_find_label(text, "Quantity", "Qty", "Units"))
    unit_price = _to_number(_find_label(text, "Unit Price", "Rate", "Price Per Unit"))
    subtotal, tax_amount, total_amount = find_totals(text)

    line_items = find_line_items(text, pdf_bytes)
    if line_items:
        heuristic.add("line_items")
    # The scalar pair describes a one-row document and nothing else. On a
    # multi-row document it is left absent rather than filled with the first
    # row's price beside a row count, which is what produced a fabricated
    # quantity variance before.
    quantity, unit_price = _scalars_from_lines(line_items, quantity, unit_price, heuristic)

    subtotal, tax_amount, total_amount = reconcile_totals(
        subtotal, tax_amount, total_amount, line_items)
    if total_amount is None and quantity is not None and unit_price is not None:
        total_amount = round(quantity * unit_price, 2)
        heuristic.add("total_amount")

    fields = {
        "invoice_number": invoice_number, "vendor_name": vendor_name, "po_number": po_number,
        "quantity": quantity, "unit_price": unit_price, "total_amount": total_amount,
        "tax_amount": tax_amount, "subtotal": subtotal,
    }
    return InvoiceExtraction(
        invoice_number=invoice_number or "UNKNOWN",
        vendor_name=vendor_name or "UNKNOWN",
        po_number=po_number,
        invoice_date=_find_label(text, "Invoice Date", "Date", "Dated"),
        line_items=line_items,
        line_item_description=(line_items[0].description if len(line_items) == 1
                               else _find_label(text, "Description", "Line Item", "Item")),
        quantity=quantity,
        unit_price=unit_price,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total_amount=total_amount if total_amount is not None else 0.0,
        vendor_tax_id=find_tax_id(text),
        **find_bank_details(text),
        field_confidences=_confidences(fields, heuristic),
    )


def parse_purchase_order(text: str, pdf_bytes: Optional[bytes] = None) -> PurchaseOrderExtraction:
    heuristic: set[str] = set()

    po_number = _find_label(text, "PO Number", "Purchase Order Number", "PO No", "P.O. Number")
    if po_number is None or not any(ch.isdigit() for ch in po_number):
        recovered = find_reference(text, "PO")
        if recovered:
            po_number = recovered
            heuristic.add("po_number")

    # On a PO the buyer's identity block usually comes first, so the generic
    # "name above a GSTIN" rule finds the wrong company. The labelled supplier
    # block wins whenever the document has one.
    vendor_name = find_supplier_from_labelled_block(pdf_bytes) or find_vendor_name(text)
    if vendor_name and not _find_label(text, "Vendor", "Vendor Name", "Supplier"):
        heuristic.add("vendor_name")
    quantity = _to_number(_find_label(text, "Quantity", "Qty", "Units", "Ordered Quantity"))
    unit_price = _to_number(_find_label(text, "Unit Price", "Rate", "Agreed Price", "Price Per Unit"))
    subtotal, tax_amount, total_amount = find_totals(text)

    line_items = find_line_items(text, pdf_bytes)
    if line_items:
        heuristic.add("line_items")
    quantity, unit_price = _scalars_from_lines(line_items, quantity, unit_price, heuristic)

    subtotal, tax_amount, total_amount = reconcile_totals(
        subtotal, tax_amount, total_amount, line_items)
    if total_amount is None and quantity is not None and unit_price is not None:
        total_amount = round(quantity * unit_price, 2)
        heuristic.add("total_amount")

    fields = {"po_number": po_number, "vendor_name": vendor_name, "quantity": quantity,
              "unit_price": unit_price, "total_amount": total_amount, "subtotal": subtotal,
              "tax_amount": tax_amount}
    return PurchaseOrderExtraction(
        po_number=po_number or "UNKNOWN",
        vendor_name=vendor_name or "UNKNOWN",
        line_items=line_items,
        line_item_description=(line_items[0].description if len(line_items) == 1
                               else _find_label(text, "Description", "Line Item", "Item")),
        quantity=quantity,
        unit_price=unit_price,
        subtotal=subtotal,
        tax_amount=tax_amount,
        total_amount=total_amount if total_amount is not None else 0.0,
        field_confidences=_confidences(fields, heuristic),
    )


def parse_goods_receipt(text: str, pdf_bytes: Optional[bytes] = None) -> GoodsReceiptExtraction:
    po_number = _find_label(text, "PO Number", "Purchase Order", "PO No")
    heuristic: set[str] = set()
    if po_number is None:
        match = re.search(r"\bPO[-/][A-Z0-9\-]+", text, re.IGNORECASE)
        po_number = match.group(0) if match else None
        if po_number:
            heuristic.add("po_number")

    received_quantity = _to_number(
        _find_label(text, "Received Quantity", "Quantity Received", "Qty Received", "Received")
    )
    fields = {"po_number": po_number, "received_quantity": received_quantity}
    return GoodsReceiptExtraction(
        # "Receipt No" and "GRN" were missing until the layout eval measured
        # them: two of the five document dialects print the receipt number
        # under a label this list did not carry, and the field came back as
        # not-stated on every goods receipt from either of them. See
        # eval/extraction_eval.py.
        receipt_number=_find_label(text, "Receipt Number", "Receipt No", "GRN Number",
                                   "GRN No", "GRN", "Note Number", "Note No"),
        po_number=po_number or "UNKNOWN",
        received_quantity=received_quantity if received_quantity is not None else 0.0,
        receipt_date=_find_label(text, "Receipt Date", "Received Date", "Date"),
        field_confidences=_confidences(fields, heuristic),
    )


def parse_rejection_notice(text: str, pdf_bytes: Optional[bytes] = None) -> RejectionNoticeExtraction:
    invoice_number = _find_label(text, "Invoice Number", "Invoice No", "Invoice #")
    heuristic: set[str] = set()
    if invoice_number is None:
        match = re.search(r"\bINV[-/][A-Z0-9\-]+", text, re.IGNORECASE)
        invoice_number = match.group(0) if match else None
        if invoice_number:
            heuristic.add("invoice_number")

    reason = _find_label(text, "Rejection Reason", "Reason", "Rejected Because")
    fields = {"invoice_number": invoice_number, "rejection_reason": reason}
    return RejectionNoticeExtraction(
        invoice_number=invoice_number or "UNKNOWN",
        rejection_reason=reason or "Reason not stated in the rejection notice.",
        rejected_date=_find_label(text, "Rejected Date", "Rejection Date", "Date"),
        field_confidences=_confidences(fields, heuristic),
    )


# ---------------------------------------------------------------------------
# Money and line-item recovery from real-world layouts
# ---------------------------------------------------------------------------
# The label-based helpers above were built against the synthetic PDFs, where
# every value sits under an explicit "Vendor:" or "Total Amount:" heading.
# Real documents mostly do not. A GST tax invoice prints the vendor name on
# its own line above a GSTIN with no label at all, and puts amounts in a
# column whose header ("Amount", "Total Cost", "Unit Rate") is separated from
# its values by every other cell in the table.
#
# What follows recovers those by shape instead. Nothing here invents a value:
# every number returned was read out of the text, and anything recovered by
# shape rather than by an explicit label is marked heuristic so the UI can
# show how it was obtained.

_MONEY = re.compile(r"(?<![\d.])(\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|\d+\.\d{2})(?![\d])")

# A line holding a GSTIN is an identity block, which is where an unlabelled
# vendor name lives on an Indian tax invoice.
_GSTIN_LINE = re.compile(r"(?i)\bGST\s*(?:NO|IN)?\b|\bGSTIN\b")
_COMPANY_SUFFIX = re.compile(
    r"(?i)\b(pvt|private|ltd|limited|llp|inc|corp|corporation|company|co|solutions|"
    r"services|enterprises|engineering|industries|traders|associates|technologies)\b"
)


def _money_values(line):
    """Every money-shaped token on a line, in order."""
    out = []
    for raw in _MONEY.findall(line):
        try:
            out.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return out


def looks_like_document_title(line: str) -> bool:
    """Whether a line is the document naming ITSELF rather than naming a party.

    "PURCHASE ORDER" printed above a GSTIN block is upper-case, is the right
    length, and sits exactly where a supplier name sits — so the shape rules
    below accepted it, and every unlabelled tax invoice from a vendor whose
    name carries no legal suffix was extracted with the document's own title
    as its supplier. That is the worst class of extraction failure: not a gap,
    a plausible-looking value that flows straight into a vendor comparison and
    produces a mismatch against a company that does not exist.

    The module already catalogues what a document calls itself, for
    classification. The same list answers this question.

    Found by eval/extraction_eval.py on the unlabelled_gst layout.
    """
    lowered = line.strip().lower()
    if not lowered:
        return False
    return any(phrase in lowered
               for phrases in _TITLE_PHRASES.values()
               for phrase in phrases)


def find_vendor_name(text: str) -> Optional[str]:
    """
    The supplier on a document that never labels it.

    Strongest evidence first: an explicit label; then the line above a GSTIN
    block, which is where a tax invoice prints its issuer; then the first line
    that reads like a company name. None rather than a guess when none hold.
    """
    labelled = _find_label(text, "Vendor", "Vendor Name", "Supplier", "Billed By", "Sold By")
    if labelled:
        return labelled

    lines = [ln.strip() for ln in text.splitlines()]
    for index, line in enumerate(lines):
        if not _GSTIN_LINE.search(line):
            continue
        for offset in range(1, 4):
            if index - offset < 0:
                break
            candidate = lines[index - offset]
            if len(candidate) < 4 or _GSTIN_LINE.search(candidate):
                continue
            if looks_like_document_title(candidate):
                continue
            if _COMPANY_SUFFIX.search(candidate) or candidate.isupper():
                return _strip_name_prefix(candidate)
            # A line directly above a GSTIN, carrying no money and no label,
            # is the issuer's name whether or not it ends in "Ltd." Plenty of
            # real suppliers do not — "Southern Office Systems" is a company
            # by any reading, and requiring a legal suffix rejected it.
            if (offset == 1 and 4 < len(candidate) < 70
                    and not _MONEY.search(candidate) and ":" not in candidate):
                return _strip_name_prefix(candidate)

    for line in lines:
        if (4 < len(line) < 70 and _COMPANY_SUFFIX.search(line)
                and not _MONEY.search(line) and not looks_like_document_title(line)):
            return _strip_name_prefix(line)
    return None


def _strip_name_prefix(line: str) -> str:
    """Drops the sign-off word a document puts before its own name."""
    cleaned = line.strip().rstrip(",")
    for prefix in ("for ", "m/s. ", "m/s ", "from "):
        if cleaned.lower().startswith(prefix):
            return cleaned[len(prefix):].strip()
    return cleaned


# Reconstructing an item table from the flattened text stream does not work.
# PyMuPDF returns cells in layout order, not reading order, so "16,000.00"
# and the description it belongs to can be twenty lines apart, and a
# label/value document ("Quantity:" then "100") has exactly the same shape as
# a one-column table. Every heuristic over that stream produced rows like
# "Page 1 of 2" priced at 1.00.
#
# The page itself knows where its table is, so that is what gets asked:
# PyMuPDF's table finder returns real rows and real columns, and the columns
# are then mapped by their headers. When a document has no detectable table,
# this returns nothing rather than a guess — the extraction agent still reads
# the line items, and the deterministic path degrades to document-level
# totals instead of to fiction.

_COLUMN_PATTERNS = {
    "description": ("description", "item", "particulars", "goods", "service", "material"),
    "quantity": ("qty", "quantity", "area / qty", "units"),
    "unit_price": ("rate", "unit rate", "unit price", "rate/unit", "price"),
    "amount": ("amount", "total cost", "total", "value"),
    "hsn_sac": ("hsn", "sac", "hsn/sac"),
}


def _header_index(header_cells, keys):
    """Column position whose header matches one of `keys`, or None."""
    best = None
    for index, cell in enumerate(header_cells):
        text = (cell or "").strip().lower()
        if not text:
            continue
        for key in keys:
            if text == key or key in text:
                # Prefer an exact header over a substring hit.
                if text == key:
                    return index
                if best is None:
                    best = index
    return best


def _score_item_table(header_cells) -> int:
    """How much this table's header looks like an item table's."""
    score = 0
    if _header_index(header_cells, _COLUMN_PATTERNS["description"]) is not None:
        score += 2
    if _header_index(header_cells, _COLUMN_PATTERNS["amount"]) is not None:
        score += 2
    if _header_index(header_cells, _COLUMN_PATTERNS["unit_price"]) is not None:
        score += 1
    if _header_index(header_cells, _COLUMN_PATTERNS["quantity"]) is not None:
        score += 1
    return score


def _cell_number(row, index):
    if index is None or index >= len(row):
        return None
    return _to_number(row[index])


def _cell_text(row, index):
    if index is None or index >= len(row):
        return None
    value = (row[index] or "").replace("\n", " ").strip()
    return value or None


# A purchase order carries BOTH parties: the buyer issues it, the supplier
# receives it, and both print a name and a GSTIN. find_vendor_name walks the
# identity blocks and cannot tell them apart — on a real PO it confidently
# returned the buying company as the "vendor", which then failed the vendor
# comparison against the invoice for entirely the wrong reason.
#
# The document itself labels the distinction ("SUPPLIER DETAILS"), and the
# table finder preserves which cell sits under which heading, so that is what
# gets asked.
_SUPPLIER_HEADINGS = ("supplier details", "supplier", "vendor details", "vendor",
                      "billed by", "sold by", "from")


def find_supplier_from_labelled_block(pdf_bytes) -> Optional[str]:
    """The name printed under a "SUPPLIER DETAILS"-style heading, or None."""
    if not pdf_bytes:
        return None
    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:  # noqa: BLE001
        return None

    try:
        for page in document:
            try:
                tables = page.find_tables()
            except Exception:  # noqa: BLE001
                continue
            for table in tables.tables:
                try:
                    rows = table.extract()
                except Exception:  # noqa: BLE001
                    continue
                for row_index, row in enumerate(rows):
                    for col_index, cell in enumerate(row):
                        heading = (cell or "").strip().lower().rstrip(":")
                        if heading not in _SUPPLIER_HEADINGS:
                            continue
                        # Scan down the same column for the first real name.
                        for below in rows[row_index + 1:]:
                            if col_index >= len(below):
                                continue
                            # The cell holds the whole supplier block — name,
                            # then address, then email. Only the first line is
                            # the name; keeping the rest made the vendor
                            # comparison against the invoice impossible.
                            value = (below[col_index] or "").strip()
                            if len(value) < 4:
                                continue
                            first = value.splitlines()[0].strip()
                            if len(first) < 4:
                                continue
                            if _MONEY.fullmatch(first) or first.lower() in _SUPPLIER_HEADINGS:
                                continue
                            return first[:120].rstrip(",")
    finally:
        document.close()
    return None


def find_line_items(text: str, pdf_bytes: Optional[bytes] = None):
    """
    The document's item rows, read from its actual table.

    `text` is accepted so the signature matches the other helpers and so a
    caller with no original bytes still gets a defined answer; without
    `pdf_bytes` there is no table to read and the result is an empty list.
    """
    if not pdf_bytes:
        return []

    try:
        document = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception:  # noqa: BLE001 — an unreadable PDF is a data problem
        return []

    best_rows, best_score = None, 0
    try:
        for page in document:
            try:
                tables = page.find_tables()
            except Exception:  # noqa: BLE001 — table finding is best-effort
                continue
            for table in tables.tables:
                try:
                    rows = table.extract()
                except Exception:  # noqa: BLE001
                    continue
                if not rows or len(rows) < 2:
                    continue
                score = _score_item_table(rows[0])
                if score > best_score:
                    best_rows, best_score = rows, score
    finally:
        document.close()

    # A table needs at least a description column and an amount column before
    # its rows can be read as line items.
    if not best_rows or best_score < 4:
        return []

    header = best_rows[0]
    columns = {name: _header_index(header, keys) for name, keys in _COLUMN_PATTERNS.items()}

    # Stacked headers are common: "Unit Rate" on the header row with "Amount"
    # directly beneath it in the SAME column. Both then resolve to one index,
    # the rate is read twice, and the real amount — which sits on the row's
    # continuation line — is lost. A 55-unit order at 675 comes back as 675
    # instead of 37,125.
    stacked_amount = (columns["amount"] is not None
                      and columns["amount"] == columns["unit_price"])

    items = []
    rows = best_rows[1:]
    for index, row in enumerate(rows):
        description = _cell_text(row, columns["description"])
        amount = _cell_number(row, columns["amount"])
        unit_price = _cell_number(row, columns["unit_price"])
        quantity = _cell_number(row, columns["quantity"])

        # Continuation rows carry a UOM or the amount under an empty
        # description; they belong to the row above, not to a new item.
        if not description:
            continue
        if amount is None and unit_price is None:
            continue
        # A totals row names itself rather than an item.
        if _is_totals_row(description):
            continue

        if stacked_amount:
            amount = None
            following = rows[index + 1] if index + 1 < len(rows) else None
            if following is not None and not _cell_text(following, columns["description"]):
                amount = _cell_number(following, columns["amount"])

        # Last resort, and only when the document's own numbers agree with it.
        if amount is None and quantity is not None and unit_price is not None:
            amount = round(quantity * unit_price, 2)

        items.append(LineItem(
            description=description[:180],
            quantity=quantity,
            unit_price=unit_price,
            amount=amount,
            hsn_sac=_cell_text(row, columns["hsn_sac"]),
        ))
    return items[:50]


_TOTALS_WORDS = ("total", "grand total", "sub total", "subtotal", "basic value",
                 "amount in words", "discount", "tax", "gst", "round off")


def _is_totals_row(description: str) -> bool:
    cleaned = description.strip().lower()
    return any(cleaned.startswith(word) or cleaned == word for word in _TOTALS_WORDS)


def find_totals(text: str):
    """(subtotal, tax_amount, total) from labelled rows, then from the
    document's own arithmetic.

    The largest money value on the page is deliberately NOT used as a
    fallback: that is how a phone number or a quantity becomes an amount.
    """
    subtotal = _to_number(_find_label(
        text, "Basic Value", "Sub Total", "Subtotal", "Taxable Value", "Total Basic", "Total Cost"))
    tax = _to_number(_find_label(
        text, "Tax Amount", "Total Tax", "GST Amount", "CGST", "Others(Tax+Charges)", "Tax"))
    total = _to_number(_find_label(
        text, "Grand Total", "Total Amount", "Invoice Amount", "Net Payable",
        "Amount Payable", "Total Purchase Order", "Total"))

    if total is None and subtotal is not None and tax is not None:
        total = round(subtotal + tax, 2)
    if subtotal is None and total is not None and tax is not None:
        subtotal = round(total - tax, 2)
    return subtotal, tax, total


def reconcile_totals(subtotal, tax, total, line_items):
    """
    Cross-checks the document's stated totals against its own line items.

    Stacked and multi-column footers defeat label reading: on a real purchase
    order "Total Purchase Order" / "Basic Value" / "Others(Tax+Charges)" are
    printed as three stacked labels followed by three stacked values, and
    reading the label nearest a number returned a "total" of 4.00 against
    53,000.00 of line items.

    A total below the sum of the lines it supposedly totals is arithmetically
    impossible, so it is discarded rather than shown. The replacement is the
    document's own arithmetic — the sum of its rows, plus tax when tax was
    read — never an outside estimate.
    """
    line_sum = round(sum(item.amount or 0 for item in (line_items or [])), 2)
    if not line_sum:
        return subtotal, tax, total

    if subtotal is None or subtotal < line_sum - 0.01:
        subtotal = line_sum
    if total is not None and total < line_sum - 0.01:
        total = None
    if total is None:
        total = round(subtotal + tax, 2) if tax is not None else subtotal
    return subtotal, tax, total


def parse_quotation(text: str, pdf_bytes: Optional[bytes] = None) -> QuotationExtraction:
    """A quotation is evidence, not a matching input — see QuotationExtraction."""
    heuristic = set()
    quotation_number = _find_label(text, "Quotation No", "Quotation Number", "Quote No",
                                   "Estimate No", "Ref No", "Our Ref", "OUR REF")
    vendor_name = find_vendor_name(text)
    if vendor_name and not _find_label(text, "Vendor", "Supplier"):
        heuristic.add("vendor_name")

    line_items = find_line_items(text, pdf_bytes)
    subtotal, tax, total = reconcile_totals(*find_totals(text), line_items)

    fields = {"quotation_number": quotation_number, "vendor_name": vendor_name,
              "subtotal": subtotal, "tax_amount": tax, "total_amount": total}
    return QuotationExtraction(
        quotation_number=quotation_number,
        vendor_name=vendor_name or "UNKNOWN",
        quotation_date=_find_label(text, "Quotation Date", "Date"),
        reference=_find_label(text, "Reference", "Sub", "Subject"),
        line_items=line_items,
        subtotal=subtotal,
        tax_amount=tax,
        total_amount=total,
        field_confidences=_confidences(fields, heuristic),
    )


_PARSERS = {
    "vendor_invoice": parse_invoice,
    "purchase_order": parse_purchase_order,
    "goods_receipt_note": parse_goods_receipt,
    "rejection_notice": parse_rejection_notice,
    "quotation": parse_quotation,
}


def parse_document(document_type: str, text: str, pdf_bytes: Optional[bytes] = None):
    """Deterministic extraction for one document type. Raises KeyError for an
    unsupported type — callers validate the type before getting here.

    `pdf_bytes` is optional: with it the item table can be read from the page
    layout, without it extraction falls back to document-level fields only.
    """
    return _PARSERS[document_type](text, pdf_bytes)


def average_confidence(extraction) -> float:
    """One document-level number for the UI. Zero when nothing was found,
    which is the honest answer for an unreadable/scanned PDF."""
    confidences = [c.confidence for c in extraction.field_confidences]
    if not confidences:
        return 0.0
    return round(sum(confidences) / len(confidences), 3)
