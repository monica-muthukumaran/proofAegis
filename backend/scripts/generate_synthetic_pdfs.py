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
    # When the layout prints an unlabelled identity block, the vendor is on
    # the page but under no label; when it does not, the vendor is a labelled
    # row like any other. Never both.
    identity = spec["vendor"] if layout.identity_block else None

    po_subtotal = spec["po_quantity"] * spec["po_unit_price"]
    invoice_subtotal = spec["invoice_quantity"] * spec["invoice_unit_price"]

    def item_table(quantity, unit_price, amount):
        return (
            [layout.labels["description"], layout.labels["quantity"],
             layout.labels["unit_price"], layout.labels.get("total_amount", "Amount")],
            [spec["description"], quantity, _money(unit_price, layout), _money(amount, layout)],
        )

    def totals_for(subtotal):
        if not layout.totals_block:
            return None
        return [
            (layout.labels["subtotal"], _money(subtotal, layout)),
            (layout.labels["tax_amount"], _money(0, layout)),
            (layout.labels["total_amount"], _money(subtotal, layout)),
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
                         ("invoice_date", INVOICE_DATE))
    if identity is None:
        invoice_rows += _rows(layout, ("vendor", spec["vendor"]))
    invoice_rows += _rows(layout, ("po_number", spec["po_number"]))
    invoice_table = (item_table(spec["invoice_quantity"], spec["invoice_unit_price"],
                                invoice_subtotal) if itemized else None)
    if not itemized:
        invoice_rows += _rows(layout,
                              ("description", spec["description"]),
                              ("quantity", spec["invoice_quantity"]),
                              ("unit_price", _money(spec["invoice_unit_price"], layout)))
    invoice_totals = totals_for(invoice_subtotal)
    if invoice_totals is None:
        invoice_rows += _rows(layout,
                              ("tax_amount", _money(0, layout)),
                              ("total_amount", _money(invoice_subtotal, layout)))
    _write_pdf(os.path.join(case_dir, "vendor_invoice.pdf"), "VENDOR INVOICE",
               invoice_rows, layout, invoice_table, identity, invoice_totals)
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

    print(f"\nDone. Upload any of these through the app: {args.out}")
    print("Note: missing_receipt_001 has no goods receipt on purpose — that absence is the finding.")


if __name__ == "__main__":
    main()
