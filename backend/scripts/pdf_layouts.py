"""
pdf_layouts.py — the same invoice, written the way different systems write it.

WHY

generate_synthetic_pdfs.py produced one layout: every field under an explicit
"Label:" heading, in one font, at one x position, with amounts formatted one
way. The deterministic parser was built against that layout and scores
beautifully on it, which tells you nothing — an extractor measured only on the
document it was written for is measuring its own assumptions.

Real AP documents vary along a small number of axes, and each of them breaks a
different thing:

  LABEL WORDING    "PO Number", "P.O. No.", "Buyer's Order No", "Order Ref".
                   Breaks anything matching a fixed string.
  VALUE PLACEMENT  Same line as the label, or on the line below it. PDF text
                   extraction splits columns onto separate lines, so a layout
                   that looks identical to a human is a different parsing
                   problem entirely.
  STRUCTURE        Label/value rows, or a real bordered table with a header
                   row. Breaks anything that assumes a label precedes a value.
  FONT             Serif, sans, monospace. Changes glyph widths and therefore
                   where PyMuPDF decides one text block ends and the next
                   begins.
  MONEY FORMAT     "INR 2,400.00", "Rs. 2400", "2,40,000.00" (the Indian
                   grouping), "₹2,400". Breaks number parsing.
  NOISE            Watermarks, terms-and-conditions blocks, reference clutter
                   in the header. Adds text that looks label-shaped and is not.

Each named layout below fixes one combination. eval/extraction_eval.py renders
every case in every layout and scores field recovery across all of them, so
the reported extraction accuracy describes a population of documents rather
than one template.

Nothing here is adversarial. Every layout is one a real vendor's billing
software actually produces; the point is coverage, not defeat.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Layout:
    """One document dialect."""
    name: str
    # Canonical field name -> the label this layout prints for it. A layout
    # may omit a field entirely, which is itself realistic and is scored as
    # "legitimately absent" rather than as a miss.
    labels: dict[str, str]
    # "inline" prints "Label: value"; "stacked" prints the label and puts the
    # value on the next line, which is what a two-column layout looks like
    # once PyMuPDF has flattened it.
    value_placement: str = "inline"
    # "rows" for label/value pairs; "table" draws a bordered item table with a
    # header row, which is what find_line_items has to cope with.
    structure: str = "rows"
    body_font: str = "helv"
    label_font: str = "hebo"
    font_size: float = 10.5
    # How money is written. See _format_money.
    money_format: str = "inr_prefix"
    # Extra text blocks that mean nothing, in the places real documents put
    # them. "header" adds reference clutter above the title; "footer" adds
    # terms; "watermark" adds a large diagonal word behind the content.
    noise: tuple[str, ...] = ()
    # Left edge of labels and of values, in points. Two very different column
    # positions exercise the parser's tolerance for whitespace runs.
    label_x: float = 60
    value_x: float = 230
    # Prints the supplier as an unlabelled identity block — the name on its
    # own line above a GSTIN and an address, with no "Vendor:" anywhere on the
    # page. This is what an actual GST tax invoice looks like, and it is the
    # hardest case in the set: there is no label to match, so the name has to
    # be recovered from the SHAPE of the block. A layout set where every field
    # carries a label is a set that only ever tests one of the parser's two
    # strategies.
    identity_block: bool = False
    # Prints totals in a right-aligned block whose labels and values are far
    # apart horizontally, which is how PyMuPDF ends up emitting them on
    # separate lines.
    totals_block: bool = False


# The canonical field names every layout is keyed on. Kept explicit so a
# typo in a layout's dict is a visible KeyError rather than a silently
# omitted field that looks like an extraction failure.
FIELDS = (
    "po_number", "invoice_number", "receipt_number", "vendor", "description",
    "quantity", "unit_price", "subtotal", "tax_amount", "total_amount",
    "currency", "invoice_date", "receipt_date", "received_quantity",
    "rejection_reason", "rejected_date",
)


LAYOUTS: tuple[Layout, ...] = (
    # The layout the parser was originally written against. Kept as the
    # control: if this one ever regresses, the change was not a generalization.
    Layout(
        name="baseline",
        labels={
            "bank_account": "Bank Account",
            "po_number": "PO Number", "invoice_number": "Invoice Number",
            "receipt_number": "Receipt Number", "vendor": "Vendor",
            "description": "Description", "quantity": "Quantity",
            "unit_price": "Unit Price", "subtotal": "Subtotal",
            "tax_amount": "Tax Amount", "total_amount": "Total Amount",
            "currency": "Currency", "invoice_date": "Invoice Date",
            "receipt_date": "Receipt Date", "received_quantity": "Received Quantity",
            "rejection_reason": "Rejection Reason", "rejected_date": "Rejected Date",
        },
    ),
    # An ERP export: abbreviated labels, trailing periods instead of colons,
    # values in a far-right column.
    Layout(
        name="erp_export",
        labels={
            "bank_account": "Remit To A/C",
            "po_number": "P.O. No", "invoice_number": "Invoice No",
            "receipt_number": "GRN No", "vendor": "Supplier",
            "description": "Item", "quantity": "Qty",
            "unit_price": "Rate", "subtotal": "Sub Total",
            "tax_amount": "GST", "total_amount": "Invoice Amount",
            "currency": "Currency", "invoice_date": "Dated",
            "receipt_date": "Received Date", "received_quantity": "Qty Received",
            "rejection_reason": "Reason", "rejected_date": "Rejection Date",
        },
        body_font="tiro",
        label_font="tibo",
        money_format="rs_prefix",
        value_x=360,
    ),
    # A two-column print where the value sits under its label. To a reader
    # this is the most ordinary document on the list; to a text extractor it
    # is the hardest, because every label arrives on its own line.
    Layout(
        name="stacked_columns",
        labels={
            "bank_account": "Bank Details",
            "po_number": "Purchase Order No", "invoice_number": "Invoice #",
            "receipt_number": "GRN Number", "vendor": "Vendor Name",
            "description": "Line Item", "quantity": "Units",
            "unit_price": "Price Per Unit", "subtotal": "Taxable Value",
            "tax_amount": "Tax", "total_amount": "Grand Total",
            "currency": "Currency", "invoice_date": "Date",
            "receipt_date": "Date", "received_quantity": "Quantity Received",
            "rejection_reason": "Rejected Because", "rejected_date": "Date",
        },
        value_placement="stacked",
        font_size=10,
    ),
    # A GST tax invoice with a real bordered item table, the Indian digit
    # grouping, and a terms block underneath. This is the closest to what
    # actually arrives by email.
    Layout(
        name="gst_tax_invoice",
        labels={
            "bank_account": "Bank A/c & IFSC",
            "po_number": "Buyer's Order No", "invoice_number": "Invoice No",
            "receipt_number": "Receipt No", "vendor": "Supplier",
            "description": "Particulars", "quantity": "Qty",
            "unit_price": "Rate", "subtotal": "Taxable Value",
            "tax_amount": "IGST", "total_amount": "Total Amount",
            "currency": "Currency", "invoice_date": "Invoice Date",
            "receipt_date": "Receipt Date", "received_quantity": "Received Quantity",
            "rejection_reason": "Rejection Reason", "rejected_date": "Rejected Date",
        },
        structure="table",
        money_format="indian_grouping",
        noise=("header", "footer"),
    ),
    # A monospaced print from an older system, with a watermark over it and a
    # rupee symbol rather than a currency code.
    Layout(
        name="legacy_mono",
        labels={
            "bank_account": "BANK ACCT",
            "po_number": "ORDER REF", "invoice_number": "INVOICE NO",
            "receipt_number": "RECEIPT NO", "vendor": "BILLED BY",
            "description": "DESCRIPTION", "quantity": "QTY",
            "unit_price": "UNIT PRICE", "subtotal": "SUBTOTAL",
            "tax_amount": "TAX", "total_amount": "TOTAL AMOUNT",
            "currency": "CURRENCY", "invoice_date": "DATE",
            "receipt_date": "DATE", "received_quantity": "RECEIVED",
            "rejection_reason": "REASON", "rejected_date": "DATE",
        },
        body_font="cour",
        label_font="cobo",
        font_size=9.5,
        money_format="symbol",
        noise=("watermark",),
        value_x=250,
    ),
    # The hardest one, and the most common in the wild: a GST tax invoice
    # whose supplier is an unlabelled identity block above a GSTIN, whose
    # items are a bordered table, and whose totals sit in a right-aligned
    # block. Nothing on the page says "Vendor". `vendor` is deliberately
    # absent from the label map, which is how the eval knows the field was
    # printed without a label rather than not printed at all.
    Layout(
        name="unlabelled_gst",
        labels={
            "bank_account": "Account",
            "po_number": "Buyer's Order No", "invoice_number": "Invoice No",
            "receipt_number": "Receipt No",
            "description": "Particulars", "quantity": "Qty",
            "unit_price": "Rate", "subtotal": "Taxable Value",
            "tax_amount": "IGST 18%", "total_amount": "Total",
            "invoice_date": "Dated", "receipt_date": "Receipt Date",
            "received_quantity": "Received Quantity",
            "rejection_reason": "Rejection Reason", "rejected_date": "Rejected Date",
        },
        structure="table",
        money_format="indian_grouping",
        noise=("header", "footer"),
        identity_block=True,
        totals_block=True,
        value_x=400,
    ),
)


LAYOUT_BY_NAME = {layout.name: layout for layout in LAYOUTS}


def format_money(value: float, money_format: str) -> str:
    """Writes an amount the way this layout's originating system writes it."""
    if money_format == "rs_prefix":
        return f"Rs. {value:,.2f}"
    if money_format == "symbol":
        return f"₹{value:,.2f}"
    if money_format == "indian_grouping":
        return f"INR {_indian_grouping(value)}"
    if money_format == "plain":
        return f"{value:,.2f}"
    return f"INR {value:,.2f}"


def _indian_grouping(value: float) -> str:
    """1,80,000.00 rather than 180,000.00.

    The last three digits group normally and everything above them groups in
    pairs. Every Indian invoice is written this way and a thousands separator
    regex that assumes groups of three reads 1,80,000 as 1.80.
    """
    whole, _, fraction = f"{value:.2f}".partition(".")
    sign, whole = ("-", whole[1:]) if whole.startswith("-") else ("", whole)
    if len(whole) <= 3:
        return f"{sign}{whole}.{fraction}"
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return f"{sign}{','.join(groups)},{tail}.{fraction}"
