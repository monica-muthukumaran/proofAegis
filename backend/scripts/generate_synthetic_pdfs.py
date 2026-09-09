"""
generate_synthetic_pdfs.py — builds the demo's uploadable PDFs.

These exist so the hero workflow can be demonstrated for real: a judge drags
files in, PyMuPDF reads them, the deterministic parser (and Gemini, when
configured) extracts fields from the actual bytes, and the matcher computes
the exception from those extracted values. Nothing about the result is
pre-seeded.

Every page carries a synthetic-data banner. Uses PyMuPDF, already a
dependency — no new package, and no reportlab.

    python scripts/generate_synthetic_pdfs.py
    python scripts/generate_synthetic_pdfs.py --layout gst_tax_invoice
    python scripts/generate_synthetic_pdfs.py --all-layouts --out data/layout_variants

LAYOUTS

Each case can be rendered in any of the dialects in scripts/pdf_layouts.py —
different label wording, value placement, fonts, table structure, money
formats and page clutter. That parameterization is what makes an extraction
accuracy figure worth quoting: measured on one template, an extractor is only
being asked to confirm its own assumptions. eval/extraction_eval.py renders
every case in every layout and scores field recovery across the population.

The `baseline` layout is what the three demo cases ship as, so the demo
documents are unchanged by any of this.

Output layout (one directory per case, matching Document 2 §8-9):

    data/synthetic_cases/
      price_variance_001/     purchase_order.pdf  vendor_invoice.pdf
                              goods_receipt_note.pdf  rejection_notice.pdf
      quantity_variance_001/  ... (same four)
      missing_receipt_001/    purchase_order.pdf  vendor_invoice.pdf
                              rejection_notice.pdf     <- no receipt: that IS the case
"""
from __future__ import annotations

import argparse
import os
import sys

import fitz  # PyMuPDF

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.pdf_layouts import LAYOUT_BY_NAME, LAYOUTS, Layout, format_money  # noqa: E402

BANNER = "Synthetic demo data - not for financial processing."
DISCLAIMER_NOTE = (
    "All vendors, amounts, and document numbers on this page are fabricated for a "
    "product demonstration. No real company, contract, or payment is represented."
)

# Clutter that a real document carries and that means nothing to the matcher.
# It is here because text that LOOKS label-shaped is exactly what makes a
# label-matching parser pick up the wrong value.
HEADER_NOISE = [
    "Original for Recipient / Duplicate for Transporter",
    "Doc Ref: SYS/2026/AUTO/00918   Page 1 of 1",
]
FOOTER_NOISE = [
    "Terms: Payment due 30 days from invoice date. Interest at 18% p.a. on overdue amounts.",
    "Goods once sold will not be taken back. Subject to Chennai jurisdiction.",
    "Declaration: We declare that this invoice shows the actual price of the goods described.",
]

CASES = {
    "price_variance_001": {
        "vendor": "Chennai Industrial Supplies Pvt. Ltd.",
        "po_number": "PO-2026-00421",
        "invoice_number": "INV-2026-1187",
        "description": "Industrial bearings, grade B",
        "po_quantity": 100,
        "po_unit_price": 2400,
        "invoice_quantity": 100,
        "invoice_unit_price": 2650,   # 10.42% over PO -> outside the 5% tolerance
        "received_quantity": 100,
        "receipt_number": "GRN-2026-0091",
        "rejection_reason": "Unit price exceeds purchase order price beyond tolerance",
        "include_receipt": True,
    },
    "quantity_variance_001": {
        "vendor": "Southern Office Systems",
        "po_number": "PO-2026-00516",
        "invoice_number": "INV-2026-2204",
        "description": "Office desk units",
        "po_quantity": 500,
        "po_unit_price": 630,
        "invoice_quantity": 500,
        "invoice_unit_price": 630,
        "received_quantity": 420,     # 19.05% over receipt -> outside the 2% tolerance
        "receipt_number": "GRN-2026-0114",
        "rejection_reason": "Invoiced quantity exceeds received quantity beyond tolerance",
        "include_receipt": True,
    },
    "missing_receipt_001": {
        "vendor": "BlueWave IT Services",
        "po_number": "PO-2026-00602",
        "invoice_number": "INV-2026-3310",
        "description": "Managed IT support - July",
        "po_quantity": 1,
        "po_unit_price": 180000,
        "invoice_quantity": 1,
        "invoice_unit_price": 180000,
        "received_quantity": None,
        "receipt_number": None,
        "rejection_reason": "No goods receipt or service confirmation on file",
        "include_receipt": False,     # the absence is the exception
    },

    # ---------------------------------------------------------------------
    # Below: the rest of the exception vocabulary, so a demo can show more
    # than a price and a quantity. Every key these add is optional and
    # defaulted in build_case(), so the three cases above render exactly as
    # they always did.
    # ---------------------------------------------------------------------

    # The control, and the most important one. Everything agrees and the queue
    # must say so: a detector that never returns "clean" is not a detector,
    # it is an alarm.
    "clean_match_001": {
        "vendor": "Kerala Packaging Works",
        "po_number": "PO-2026-00733",
        "invoice_number": "INV-2026-4401",
        "description": "Corrugated shipping cartons, 5-ply",
        "po_quantity": 2000, "po_unit_price": 48,
        "invoice_quantity": 2000, "invoice_unit_price": 48,
        "received_quantity": 2000, "receipt_number": "GRN-2026-0140",
        "include_receipt": True,
        "include_rejection": False,   # nothing was rejected, because nothing is wrong
    },

    # Line maths that does not add up: subtotal + tax != the stated total.
    "tax_total_mismatch_001": {
        "vendor": "Deccan Logistics Partners",
        "po_number": "PO-2026-00810",
        "invoice_number": "INV-2026-4502",
        "description": "Inbound freight, July consignments",
        "po_quantity": 1, "po_unit_price": 240000,
        "invoice_quantity": 1, "invoice_unit_price": 240000,
        "received_quantity": 1, "receipt_number": "GRN-2026-0151",
        "include_receipt": True,
        "invoice_tax": 43200,             # 18% GST on 240,000 = 43,200
        "invoice_total_override": 312400,  # but the total claims 312,400, not 283,200
        "rejection_reason": "Invoice total does not equal subtotal plus tax",
    },

    # The invoice comes from a different legal entity than the order.
    "vendor_mismatch_001": {
        "vendor": "Ashwin Software Labs",
        "invoice_vendor": "Ashwin Technologies (OPC) Pvt. Ltd.",
        "po_number": "PO-2026-00845",
        "invoice_number": "INV-2026-4610",
        "description": "Annual licence renewal, 25 seats",
        "po_quantity": 25, "po_unit_price": 9000,
        "invoice_quantity": 25, "invoice_unit_price": 9000,
        "received_quantity": 25, "receipt_number": "GRN-2026-0163",
        "include_receipt": True,
        "rejection_reason": "Invoice raised by an entity that does not match the purchase order",
    },

    # The coherence guard. An invoice for steel pipes against an order for
    # office chairs: every number on both pages is real, and comparing them
    # produces nonsense. The product has to refuse to compute rather than
    # report a fabricated variance — see services/coherence_service.py, which
    # exists because this once came back as a confident 211,200 quantity
    # variance built from 100 pipes minus 12 chairs.
    "unrelated_documents_001": {
        "vendor": "Meridian Facility Care",
        "po_number": "PO-2026-00901",
        "invoice_number": "INV-2026-4712",
        "description": "Ergonomic office chairs, mesh back",
        "invoice_description": "Mild steel pipes, 100mm OD, 6m lengths",
        "po_quantity": 12, "po_unit_price": 14500,
        "invoice_quantity": 100, "invoice_unit_price": 2112,
        "received_quantity": 12, "receipt_number": "GRN-2026-0170",
        "include_receipt": True,
        "rejection_reason": "Documents on this case do not describe the same transaction",
    },

    # --- Cross-case sets. Upload in alphabetical order: a, then b, then c. --
    # Each of these passes its own three-way match. The finding exists only
    # because the workspace remembers the others, which is the entire claim
    # the product is making.

    "duplicate_invoice_a": {
        "vendor": "Bharat Safety Equipment",
        "po_number": "PO-2026-00950",
        "invoice_number": "INV-2026-4890",
        "description": "Safety helmets, ISI marked",
        "po_quantity": 400, "po_unit_price": 310,
        "invoice_quantity": 400, "invoice_unit_price": 310,
        "received_quantity": 400, "receipt_number": "GRN-2026-0181",
        "include_receipt": True, "include_rejection": False,
    },
    "duplicate_invoice_b": {
        "vendor": "Bharat Safety Equipment",
        "po_number": "PO-2026-00950",
        "invoice_number": "INV-2026-4890",    # the same invoice number, again
        "description": "Safety helmets, ISI marked",
        "po_quantity": 400, "po_unit_price": 310,
        "invoice_quantity": 400, "invoice_unit_price": 310,
        "received_quantity": 400, "receipt_number": "GRN-2026-0181",
        "include_receipt": True,
        "invoice_date": "2026-07-29",         # re-presented four weeks later
        "rejection_reason": "Invoice number and amount already presented on this purchase order",
    },

    "payment_details_changed_a": {
        "vendor": "Sagar Marine Supplies",
        "po_number": "PO-2026-01002",
        "invoice_number": "INV-2026-4955",
        "description": "Marine-grade fasteners, assorted",
        "po_quantity": 1500, "po_unit_price": 74,
        "invoice_quantity": 1500, "invoice_unit_price": 74,
        "received_quantity": 1500, "receipt_number": "GRN-2026-0190",
        "include_receipt": True, "include_rejection": False,
        "bank_account": "HDFC0004411 / 50200071234567",
    },
    "payment_details_changed_b": {
        "vendor": "Sagar Marine Supplies",
        "po_number": "PO-2026-01002",
        "invoice_number": "INV-2026-5012",
        "description": "Marine-grade fasteners, assorted",
        "po_quantity": 1500, "po_unit_price": 74,
        "invoice_quantity": 1500, "invoice_unit_price": 74,
        "received_quantity": 1500, "receipt_number": "GRN-2026-0198",
        "include_receipt": True,
        "invoice_date": "2026-07-24",
        "bank_account": "IDIB000K123 / 7712004455321",   # a different bank entirely
        "rejection_reason": "Vendor bank details differ from the account on the previous invoice",
    },

    # Three invoices against ONE order. Each bills 90 of 200 units and passes
    # alone; together they bill 270 against an order for 200.
    "po_over_billed_a": {
        "vendor": "Anantha Chemicals",
        "po_number": "PO-2026-01100",
        "invoice_number": "INV-2026-5101",
        "description": "Industrial solvent, 200L drums",
        "po_quantity": 200, "po_unit_price": 5400,
        "invoice_quantity": 90, "invoice_unit_price": 5400,
        "received_quantity": 90, "receipt_number": "GRN-2026-0211",
        "include_receipt": True, "include_rejection": False,
    },
    "po_over_billed_b": {
        "vendor": "Anantha Chemicals",
        "po_number": "PO-2026-01100",
        "invoice_number": "INV-2026-5140",
        "description": "Industrial solvent, 200L drums",
        "po_quantity": 200, "po_unit_price": 5400,
        "invoice_quantity": 90, "invoice_unit_price": 5400,
        "received_quantity": 90, "receipt_number": "GRN-2026-0225",
        "include_receipt": True, "include_rejection": False,
        "invoice_date": "2026-07-16",
    },
    "po_over_billed_c": {
        "vendor": "Anantha Chemicals",
        "po_number": "PO-2026-01100",
        "invoice_number": "INV-2026-5188",
        "description": "Industrial solvent, 200L drums",
        "po_quantity": 200, "po_unit_price": 5400,
        "invoice_quantity": 90, "invoice_unit_price": 5400,
        "received_quantity": 90, "receipt_number": "GRN-2026-0240",
        "include_receipt": True,
        "invoice_date": "2026-07-30",
        "rejection_reason": "Cumulative quantity billed exceeds the quantity ordered",
    },
}

INVOICE_DATE = "2026-07-02"
RECEIPT_DATE = "2026-07-05"
REJECTED_DATE = "2026-07-06"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
def _draw_noise(page, layout: Layout, y: float) -> float:
    """Header clutter, returning the y to start real content at."""
    if "header" in layout.noise:
        for line in HEADER_NOISE:
            page.insert_text((layout.label_x, y), line, fontname=layout.body_font, fontsize=7.5)
            y += 11
        y += 6
    return y


def _draw_watermark(page, layout: Layout) -> None:
    if "watermark" not in layout.noise:
        return
    # Large, pale, and rotated — behind the content, the way a real "COPY"
    # stamp sits. It contributes text to the extraction, which is the point.
    page.insert_textbox(
        fitz.Rect(90, 300, 520, 420), "DUPLICATE COPY",
        fontname="hebo", fontsize=44, color=(0.88, 0.88, 0.9),
        align=fitz.TEXT_ALIGN_CENTER, rotate=0,
    )


def _draw_footer_noise(page, layout: Layout, y: float) -> float:
    if "footer" not in layout.noise:
        return y
    y += 10
    for line in FOOTER_NOISE:
        page.insert_textbox(fitz.Rect(layout.label_x, y, 535, y + 22), line,
                            fontname=layout.body_font, fontsize=7.5)
        y += 16
    return y


def _draw_identity_block(page, layout: Layout, vendor: str, y: float) -> float:
    """The supplier, printed the way a real tax invoice prints it.

    A name on its own line, in a larger weight, above a GSTIN and an address.
    No label anywhere — which is the point: the parser has to recover it from
    the block's shape (a company-suffixed line sitting above a GSTIN) rather
    than by matching the word "Vendor".
    """
    page.insert_text((layout.label_x, y), vendor, fontname=layout.label_font, fontsize=12)
    y += 16
    # A structurally valid GSTIN: 2 state digits, a 5-letter PAN prefix, 4
    # digits, a letter, then three more characters. The parser recognises the
    # shape, so a malformed one would be testing nothing.
    page.insert_text((layout.label_x, y), "GSTIN: 33AABCU9603R1ZM",
                     fontname=layout.body_font, fontsize=9)
    y += 13
    page.insert_text((layout.label_x, y), "14 Anna Salai, Chennai 600002, Tamil Nadu",
                     fontname=layout.body_font, fontsize=9)
    return y + 20


def _draw_totals_block(page, layout: Layout, totals: list[tuple[str, str]], y: float) -> float:
    """Right-aligned totals, labels and values far apart.

    The horizontal gap is the whole point: PyMuPDF emits a label and a value
    this far apart as separate lines, so the parser meets the "bare label,
    value on the following line" case rather than the easy inline one.
    """
    for label, value in totals:
        page.insert_text((360, y), label, fontname=layout.label_font, fontsize=layout.font_size)
        page.insert_text((470, y), str(value), fontname=layout.body_font, fontsize=layout.font_size)
        y += layout.font_size + 8
    return y + 6


def _draw_rows(page, layout: Layout, rows: list[tuple[str, str]], y: float) -> float:
    """Label/value pairs, inline or stacked."""
    for label, value in rows:
        page.insert_text((layout.label_x, y), f"{label}:",
                         fontname=layout.label_font, fontsize=layout.font_size)
        if layout.value_placement == "stacked":
            y += layout.font_size + 5
            page.insert_text((layout.label_x, y), str(value),
                             fontname=layout.body_font, fontsize=layout.font_size)
            y += layout.font_size + 12
        else:
            page.insert_text((layout.value_x, y), str(value),
                             fontname=layout.body_font, fontsize=layout.font_size)
            y += layout.font_size + 13
    return y


def _draw_table(page, layout: Layout, headers: list[str], row: list[str], y: float) -> float:
    """A bordered item table with a header row.

    Real tax invoices put the item, quantity, rate and amount in a grid, and a
    grid is a different extraction problem from a label — find_line_items has
    to recover the columns from geometry rather than from a preceding word.
    """
    left, right = layout.label_x, 535
    widths = [0.40, 0.13, 0.20, 0.27]
    xs, cursor = [], left
    for weight in widths:
        xs.append(cursor)
        cursor += (right - left) * weight

    header_height = layout.font_size + 12
    page.draw_rect(fitz.Rect(left, y - layout.font_size, right, y + 6),
                   color=(0.35, 0.35, 0.4), fill=(0.94, 0.95, 0.96), width=0.6)
    for x, text in zip(xs, headers):
        page.insert_text((x + 4, y), text, fontname=layout.label_font, fontsize=layout.font_size - 0.5)

    y += header_height
    page.draw_rect(fitz.Rect(left, y - layout.font_size, right, y + 6),
                   color=(0.35, 0.35, 0.4), width=0.6)
    for x, text in zip(xs, row):
        page.insert_text((x + 4, y), str(text), fontname=layout.body_font, fontsize=layout.font_size - 0.5)

    # Column separators, so the grid reads as a grid to a table detector.
    for x in xs[1:]:
        page.draw_line(fitz.Point(x, y - layout.font_size - header_height),
                       fitz.Point(x, y + 6), color=(0.35, 0.35, 0.4), width=0.6)
    return y + header_height + 8


def _write_pdf(path: str, title: str, rows: list[tuple[str, str]], layout: Layout,
               table: tuple[list[str], list[str]] | None = None,
               identity: str | None = None,
               totals: list[tuple[str, str]] | None = None) -> None:
    doc = fitz.open()
    page = doc.new_page()  # A4 by default

    _draw_watermark(page, layout)

    y = 70
    page.insert_text((layout.label_x, y), "ProofAegis", fontname=layout.body_font, fontsize=9)
    y = _draw_noise(page, layout, y + 18)

    page.insert_text((layout.label_x, y + 12), title, fontname=layout.label_font, fontsize=17)
    page.draw_line(fitz.Point(layout.label_x, y + 24), fitz.Point(535, y + 24))
    y += 57

    if identity is not None:
        y = _draw_identity_block(page, layout, identity, y)

    y = _draw_rows(page, layout, rows, y)
    if table is not None:
        y += 8
        y = _draw_table(page, layout, table[0], table[1], y)
    if totals:
        y += 6
        y = _draw_totals_block(page, layout, totals, y)

    y = _draw_footer_noise(page, layout, y)

    y += 18
    page.draw_line(fitz.Point(layout.label_x, y), fitz.Point(535, y))
    page.insert_text((layout.label_x, y + 22), BANNER, fontname="hebo", fontsize=9)
    page.insert_textbox(fitz.Rect(layout.label_x, y + 32, 535, y + 90), DISCLAIMER_NOTE,
                        fontname="helv", fontsize=8)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    doc.save(path)
    doc.close()


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
def _money(value: float, layout: Layout) -> str:
    return format_money(float(value), layout.money_format)


def _row(layout: Layout, key: str, value) -> tuple[str, str] | None:
    """One label/value pair, or None when this layout does not print the field."""
    label = layout.labels.get(key)
    if label is None or value is None:
        return None
    return (label, value)


def _rows(layout: Layout, *pairs) -> list[tuple[str, str]]:
    return [row for row in (_row(layout, key, value) for key, value in pairs) if row]


def build_case(case_id: str, spec: dict, out_dir: str, layout: Layout) -> list[str]:
    case_dir = os.path.join(out_dir, case_id)
    written = []
    itemized = layout.structure == "table"

    # Optional per-case overrides. Every one of these defaults to the previous
    # behaviour, so a spec that does not mention them renders as before.
    #
    #   invoice_vendor        the invoice is from a different entity than the
    #                         order (vendor_mismatch)
    #   invoice_description   the invoice is for different goods than the
    #                         order (unrelated_documents)
    #   invoice_tax /         the stated total does not equal subtotal + tax
    #   invoice_total_override    (tax_total_mismatch)
    #   bank_account          remittance details, so a change between two
    #                         invoices is visible (payment_details_changed)
    #   invoice_date          a case presented later than the default date
    #   include_rejection     a clean case has nothing to reject
    invoice_vendor = spec.get("invoice_vendor", spec["vendor"])
    invoice_description = spec.get("invoice_description", spec["description"])
    invoice_tax = spec.get("invoice_tax", 0)
    bank_account = spec.get("bank_account")
    invoice_date = spec.get("invoice_date", INVOICE_DATE)
    include_rejection = spec.get("include_rejection", True)

    # When the layout prints an unlabelled identity block, the vendor is on
    # the page but under no label; when it does not, the vendor is a labelled
    # row like any other. Never both.
    identity = spec["vendor"] if layout.identity_block else None
    invoice_identity = invoice_vendor if layout.identity_block else None

    po_subtotal = spec["po_quantity"] * spec["po_unit_price"]
    invoice_subtotal = spec["invoice_quantity"] * spec["invoice_unit_price"]
    # The number the invoice CLAIMS. Normally subtotal + tax; the override is
    # what makes tax_total_mismatch a real discrepancy on the page rather than
    # a label saying there is one.
    invoice_total = spec.get("invoice_total_override", invoice_subtotal + invoice_tax)

    def item_table(quantity, unit_price, amount, description=None):
        return (
            [layout.labels["description"], layout.labels["quantity"],
             layout.labels["unit_price"], layout.labels.get("total_amount", "Amount")],
            [description or spec["description"], quantity,
             _money(unit_price, layout), _money(amount, layout)],
        )

    def totals_for(subtotal, tax=0, total=None):
        if not layout.totals_block:
            return None
        return [
            (layout.labels["subtotal"], _money(subtotal, layout)),
            (layout.labels["tax_amount"], _money(tax, layout)),
            (layout.labels["total_amount"],
             _money(subtotal + tax if total is None else total, layout)),
        ]

    # --- Purchase order ---
    po_rows = _rows(layout, ("po_number", spec["po_number"]))
    if identity is None:
        po_rows += _rows(layout, ("vendor", spec["vendor"]))
    po_table = item_table(spec["po_quantity"], spec["po_unit_price"], po_subtotal) if itemized else None
    if not itemized:
        po_rows += _rows(layout,
                         ("description", spec["description"]),
                         ("quantity", spec["po_quantity"]),
                         ("unit_price", _money(spec["po_unit_price"], layout)))
    po_totals = totals_for(po_subtotal)
    if po_totals is None:
        po_rows += _rows(layout,
                         ("total_amount", _money(po_subtotal, layout)),
                         ("currency", "INR"))
    _write_pdf(os.path.join(case_dir, "purchase_order.pdf"), "PURCHASE ORDER",
               po_rows, layout, po_table, identity, po_totals)
    written.append("purchase_order.pdf")

    # --- Vendor invoice ---
    invoice_rows = _rows(layout,
                         ("invoice_number", spec["invoice_number"]),
                         ("invoice_date", invoice_date))
    if invoice_identity is None:
        invoice_rows += _rows(layout, ("vendor", invoice_vendor))
    invoice_rows += _rows(layout, ("po_number", spec["po_number"]))
    invoice_table = (item_table(spec["invoice_quantity"], spec["invoice_unit_price"],
                                invoice_subtotal, invoice_description) if itemized else None)
    if not itemized:
        invoice_rows += _rows(layout,
                              ("description", invoice_description),
                              ("quantity", spec["invoice_quantity"]),
                              ("unit_price", _money(spec["invoice_unit_price"], layout)))
    # Remittance details go on the invoice as a plain labelled row, which is
    # where a real one carries them — a bank change is only detectable if the
    # account is on the page in the first place.
    if bank_account:
        invoice_rows += _rows(layout, ("bank_account", bank_account))
    invoice_totals = totals_for(invoice_subtotal, invoice_tax, invoice_total)
    if invoice_totals is None:
        invoice_rows += _rows(layout,
                              ("tax_amount", _money(invoice_tax, layout)),
                              ("total_amount", _money(invoice_total, layout)))
    _write_pdf(os.path.join(case_dir, "vendor_invoice.pdf"), "VENDOR INVOICE",
               invoice_rows, layout, invoice_table, invoice_identity, invoice_totals)
    written.append("vendor_invoice.pdf")

    # --- Goods receipt (absent on purpose for missing_receipt_001) ---
    if spec["include_receipt"]:
        receipt_rows = _rows(layout,
                             ("receipt_number", spec["receipt_number"]),
                             ("po_number", spec["po_number"]))
        if identity is None:
            receipt_rows += _rows(layout, ("vendor", spec["vendor"]))
        receipt_rows += _rows(layout,
                              ("description", spec["description"]),
                              ("received_quantity", spec["received_quantity"]),
                              ("receipt_date", RECEIPT_DATE))
        _write_pdf(os.path.join(case_dir, "goods_receipt_note.pdf"), "GOODS RECEIPT NOTE",
                   receipt_rows, layout, None, identity)
        written.append("goods_receipt_note.pdf")

    # --- Rejection notice ---
    # Skipped for a clean case. Shipping a rejection notice with a case that
    # has nothing wrong with it would hand the extractor the answer.
    if not include_rejection:
        return written
    rejection_rows = _rows(layout, ("invoice_number", spec["invoice_number"]))
    if identity is None:
        rejection_rows += _rows(layout, ("vendor", spec["vendor"]))
    rejection_rows += _rows(layout,
                            ("rejection_reason", spec["rejection_reason"]),
                            ("rejected_date", REJECTED_DATE))
    _write_pdf(os.path.join(case_dir, "rejection_notice.pdf"), "INVOICE REJECTION NOTICE",
               rejection_rows, layout, None, identity)
    written.append("rejection_notice.pdf")
    return written


# What each case is FOR. Written beside the PDFs as README.md so the folder
# explains itself — a directory of 50 unlabelled PDFs is not a demo asset,
# it is a puzzle.
#
# `expect` is what the product should conclude. If uploading a case does not
# produce this, either the generator or the matcher has drifted, and this file
# is the record of which was intended.
CASE_NOTES = {
    "price_variance_001": ("price_variance",
        "Unit price 2,650 against an order at 2,400 — 10.4%, outside the 5% tolerance."),
    "quantity_variance_001": ("quantity_variance",
        "500 invoiced, 420 received — 19%, outside the 2% tolerance."),
    "missing_receipt_001": ("missing_goods_receipt",
        "No goods receipt on file. The ABSENCE is the finding, so this case ships three PDFs."),
    "clean_match_001": ("no_exception",
        "Everything agrees. The control: a detector that never says 'clean' is an alarm, "
        "not a detector. Show this one to prove the queue is not just shouting."),
    "tax_total_mismatch_001": ("tax_total_mismatch",
        "Invoice states 312,400 where subtotal 240,000 + tax 43,200 = 283,200. "
        "A 29,200 overstatement hidden in the arithmetic."),
    "vendor_mismatch_001": ("vendor_mismatch",
        "Order to 'Ashwin Software Labs', invoice from 'Ashwin Technologies (OPC) Pvt. Ltd.' — "
        "a different legal entity with a similar name."),
    "unrelated_documents_001": ("unrelated_documents",
        "Invoice for 100 steel pipes against an order for 12 office chairs. The product must "
        "REFUSE to compute rather than report a fabricated variance."),
    "duplicate_invoice_a": ("no_exception",
        "Clean on its own. Upload FIRST — it is the memory the next case is caught against."),
    "duplicate_invoice_b": ("duplicate_invoice",
        "Same invoice number and amount, re-presented four weeks later. Upload SECOND."),
    "payment_details_changed_a": ("no_exception",
        "Clean. Establishes the vendor's bank account. Upload FIRST."),
    "payment_details_changed_b": ("payment_details_changed",
        "Same vendor, different bank entirely. Upload SECOND."),
    "po_over_billed_a": ("no_exception", "90 of 200 units. Clean alone. Upload FIRST."),
    "po_over_billed_b": ("no_exception", "90 more. Still clean alone. Upload SECOND."),
    "po_over_billed_c": ("po_over_billed",
        "90 more — 270 billed against an order for 200. Upload THIRD."),
}

# Cases whose finding only exists because the workspace remembers another
# case. These are the product's actual claim and the ones worth demoing.
CROSS_CASE = {"duplicate_invoice_b", "payment_details_changed_b", "po_over_billed_c"}


def write_readme(out_dir: str, case_ids) -> str:
    lines = [
        "# Synthetic demo cases",
        "",
        "Generated by `backend/scripts/generate_synthetic_pdfs.py`. Every page is",
        "fabricated and carries a synthetic-data banner.",
        "",
        "Upload a folder through **New case from PDFs**. Nothing here is pre-seeded:",
        "the app reads the actual bytes, extracts the fields, and computes the finding.",
        "",
        "## Single-case findings",
        "",
        "Each of these is decided from its own documents. Upload in any order.",
        "",
    ]
    single = [c for c in case_ids if c not in CROSS_CASE
              and not any(c.startswith(p) for p in ("duplicate_invoice_", "payment_details_changed_", "po_over_billed_"))]
    for cid in single:
        expect, why = CASE_NOTES.get(cid, ("?", ""))
        lines += [f"### `{cid}`", f"- **Expect:** `{expect}`", f"- {why}", ""]

    lines += [
        "## Cross-case findings",
        "",
        "**Order matters.** Each of these passes its own three-way match; the finding",
        "exists only because the workspace remembers the earlier upload. This is the",
        "thing a per-invoice system cannot do, so it is the part worth demonstrating.",
        "",
    ]
    for prefix, title in [
        ("duplicate_invoice_", "Duplicate invoice"),
        ("payment_details_changed_", "Payment details changed"),
        ("po_over_billed_", "Purchase order over-billed"),
    ]:
        lines.append(f"### {title}")
        for cid in [c for c in case_ids if c.startswith(prefix)]:
            expect, why = CASE_NOTES.get(cid, ("?", ""))
            lines.append(f"- `{cid}` → expect `{expect}` — {why}")
        lines.append("")

    path = os.path.join(out_dir, "README.md")
    os.makedirs(out_dir, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))
    return path


def main() -> None:
    default_out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "data", "synthetic_cases")
    parser = argparse.ArgumentParser(description="Generate synthetic demo PDFs for ProofAegis.")
    parser.add_argument("--out", default=default_out, help="Output directory.")
    parser.add_argument("--layout", default="baseline",
                        choices=sorted(LAYOUT_BY_NAME), help="Document dialect to render in.")
    parser.add_argument("--all-layouts", action="store_true",
                        help="Render every case in every layout, one subdirectory per layout.")
    args = parser.parse_args()

    layouts = LAYOUTS if args.all_layouts else (LAYOUT_BY_NAME[args.layout],)
    for layout in layouts:
        out_dir = os.path.join(args.out, layout.name) if args.all_layouts else args.out
        for case_id, spec in CASES.items():
            written = build_case(case_id, spec, out_dir, layout)
            print(f"{layout.name}/{case_id}: {len(written)} PDFs -> {', '.join(written)}")

    readme = write_readme(args.out, list(CASES))
    print(f"\nWrote {readme}")
    print(f"Done. Upload any of these through the app: {args.out}")
    print("Note: missing_receipt_001 has no goods receipt on purpose — that absence is the finding.")
    print("Note: the *_a / *_b / *_c sets are cross-case — upload them in that order.")


if __name__ == "__main__":
    main()
