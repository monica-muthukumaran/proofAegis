"""
The deterministic parser against layouts it was not written for.

The synthetic PDFs put every value under an explicit "Vendor:" / "Total
Amount:" label. Real vendor paperwork does not: it prints the supplier above
a GSTIN with no label at all, and puts amounts in a table whose header sits
several cells away from its values. Against the four real documents that
prompted this work, the label-only parser returned vendor "UNKNOWN", invoice
number "UNKNOWN" and a PO number truncated to "PO/SRPL".

These tests build PDFs with the same SHAPE as those documents rather than
shipping the originals, which are real commercial paperwork.
"""
import io

import fitz
import pytest

from services import pdf_field_parser as P


def _table_pdf(title, header, rows, footer_lines=()):
    """A one-page PDF with a real drawn table, like a vendor's PO or quotation."""
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 60), title, fontsize=13)

    top, left = 100, 50
    row_height, col_width = 26, 95
    all_rows = [header] + rows

    for row_index, row in enumerate(all_rows):
        y = top + row_index * row_height
        for col_index, cell in enumerate(row):
            x = left + col_index * col_width
            page.draw_rect(fitz.Rect(x, y, x + col_width, y + row_height), width=0.7)
            page.insert_text((x + 3, y + 17), str(cell)[:16], fontsize=7)

    y = top + len(all_rows) * row_height + 30
    for line in footer_lines:
        page.insert_text((50, y), line, fontsize=9)
        y += 16

    data = document.tobytes()
    document.close()
    return data


def _text(pdf_bytes):
    with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
        return "\n".join(page.get_text() for page in document)


@pytest.fixture
def multi_line_po():
    return _table_pdf(
        "Purchase Order",
        ["SNo", "Item Description", "Qty", "Unit Rate", "Amount"],
        [
            ["1", "Water tank", "1.000", "16,000.00", "16,000.00"],
            ["2", "Toilet recond", "1.000", "22,000.00", "22,000.00"],
            ["3", "EWC TOILET", "1.000", "15,000.00", "15,000.00"],
        ],
        footer_lines=[
            "PO No. PO/SRPL/26/19451",
            "SIGMA ENGINEERING SOLUTIONS",
            "GST NO: 33ANUPV1878L2ZY",
            "Basic Value: 53,000.00",
            "Others(Tax+Charges): 9,540.00",
        ],
    )


def test_line_items_are_read_from_the_table(multi_line_po):
    items = P.find_line_items(_text(multi_line_po), multi_line_po)

    assert len(items) == 3
    assert [item.unit_price for item in items] == [16000.0, 22000.0, 15000.0]
    assert [item.amount for item in items] == [16000.0, 22000.0, 15000.0]
    assert all(item.quantity == 1.0 for item in items)


def test_a_multi_line_document_leaves_the_scalar_quantity_absent(multi_line_po):
    """quantity=3 next to the first line's unit price was the original bug:
    the ROW COUNT presented as an order quantity. Absent is the truthful
    answer, and the matcher reports it as "missing" rather than comparing it.
    """
    parsed = P.parse_purchase_order(_text(multi_line_po), multi_line_po)

    assert parsed.quantity is None
    assert parsed.unit_price is None
    assert len(parsed.line_items) == 3
    assert parsed.subtotal == 53000.0


def test_a_full_reference_survives_its_slashes(multi_line_po):
    """The old pattern stopped at the first separator, so PO/SRPL/26/19451
    was captured as "PO/SRPL" and could never link two documents."""
    parsed = P.parse_purchase_order(_text(multi_line_po), multi_line_po)
    assert parsed.po_number == "PO/SRPL/26/19451"


def test_an_unlabelled_vendor_is_recovered_from_the_gstin_block(multi_line_po):
    parsed = P.parse_purchase_order(_text(multi_line_po), multi_line_po)
    assert parsed.vendor_name == "SIGMA ENGINEERING SOLUTIONS"


def test_a_label_value_document_is_not_read_as_a_table():
    """The synthetic PDFs have no table. Reading their "Quantity:" /
    "Total Amount:" labels as one-column rows produced five line items named
    after the labels; a document with no table must yield no line items."""
    document = fitz.open()
    page = document.new_page()
    for index, line in enumerate([
        "VENDOR INVOICE", "Invoice Number:", "INV-2026-1187", "Vendor:",
        "Chennai Industrial Supplies Pvt. Ltd.", "Quantity:", "100",
        "Unit Price:", "INR 2,650.00", "Total Amount:", "INR 265,000.00",
    ]):
        page.insert_text((50, 60 + index * 18), line, fontsize=10)
    data = document.tobytes()
    document.close()

    assert P.find_line_items(_text(data), data) == []


def test_a_single_line_document_still_fills_the_scalar_fields():
    pdf = _table_pdf(
        "Purchase Order",
        ["SNo", "Item Description", "Qty", "Unit Rate", "Amount"],
        [["1", "Down Light 8W", "55.000", "675.00", "37,125.00"]],
        footer_lines=["PO No. PO/SMPL/26/19596", "REFLECTIONS LIMITED", "GST NO: 33AAA1234A1Z5"],
    )
    parsed = P.parse_purchase_order(_text(pdf), pdf)

    assert len(parsed.line_items) == 1
    assert parsed.quantity == 55.0
    assert parsed.unit_price == 675.0


def test_a_quotation_is_classified_and_parsed():
    pdf = _table_pdf(
        "SIGMA ENGINEERING SOLUTIONS",
        ["S No", "Item", "Area / Qty", "Rate/Unit", "Total Cost"],
        [
            ["1", "Water tank", "1", "16,000.00", "16,000.00"],
            ["2", "Toilet recond", "1", "22,000.00", "22,000.00"],
        ],
        footer_lines=["Sub: Quotation for Plumbing Work", "OUR REF: SES/1371/8", "GST 18% EXCL."],
    )
    text = _text(pdf)

    document_type, confidence = P.classify_document(text)
    assert document_type == "quotation"
    assert confidence > 0.5

    parsed = P.parse_document("quotation", text, pdf)
    assert len(parsed.line_items) == 2
    assert parsed.total_amount == 38000.0


def test_parsing_without_the_original_bytes_still_works():
    """parse_document's pdf_bytes argument is optional; callers that only have
    text must get document-level fields rather than an exception."""
    pdf = _table_pdf(
        "Purchase Order",
        ["SNo", "Item Description", "Qty", "Unit Rate", "Amount"],
        [["1", "Down Light 8W", "55.000", "675.00", "37,125.00"]],
        footer_lines=["PO No. PO/SMPL/26/19596", "REFLECTIONS LIMITED", "GST NO: 33AAA1234A1Z5"],
    )
    parsed = P.parse_document("purchase_order", _text(pdf))

    assert parsed.line_items == []
    assert parsed.po_number == "PO/SMPL/26/19596"
