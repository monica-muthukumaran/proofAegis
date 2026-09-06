"""
document_agent.py — FR-003 (classification) + FR-004 (field extraction).

Pipeline order matters and was a fixed bug in this pack (Document 1, change
#7): PDF text extraction happens BEFORE the Gemini call, not after. PyMuPDF
pulls raw text out of the PDF; only that extracted text — never the raw
bytes — goes to the ADK agent, which is prompted to return one of the
per-document-type schemas in schemas.py via `output_schema`.

Each ADK agent runs through the standard ADK Runner + InMemorySessionService
pattern: a single-turn invocation per document, no persisted conversation
state, because there's no multi-turn dialogue here — one document in, one
structured extraction out.
"""
from __future__ import annotations

import uuid

import fitz  # PyMuPDF
from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from config import config
from schemas import (
    AIResult,
    GoodsReceiptExtraction,
    InvoiceExtraction,
    PurchaseOrderExtraction,
    QuotationExtraction,
    RejectionNoticeExtraction,
)
from services.ai_fallback import call_gemini_with_fallback

APP_NAME = "proofaegis-document-extraction"

_SCHEMA_BY_DOC_TYPE = {
    "vendor_invoice": InvoiceExtraction,
    "purchase_order": PurchaseOrderExtraction,
    "goods_receipt_note": GoodsReceiptExtraction,
    "rejection_notice": RejectionNoticeExtraction,
    "quotation": QuotationExtraction,
}

_LINE_ITEM_RULE = (
    " Put EVERY row of the item table in line_items, one entry per row, with its own "
    "description, quantity, unit_price and amount. Never collapse several rows into one, "
    "and never put the NUMBER OF ROWS in a quantity field. "
    "Set the top-level quantity and unit_price ONLY when the document has exactly one row; "
    "when it has more than one, leave both null and rely on line_items. "
    "subtotal is the value before tax; total_amount is the final payable including tax "
    "(they are equal when no tax is shown). Never guess a number that is not in the text: "
    "if a field is genuinely absent, omit it rather than inventing a value."
)

_INSTRUCTION_BY_DOC_TYPE = {
    "vendor_invoice": (
        "You extract structured fields from a vendor invoice PDF's text. "
        "Return invoice_number, vendor_name, po_number, invoice_date, line_items, "
        "currency, subtotal, tax_amount, total_amount, vendor_tax_id, and a confidence "
        "score per field. Also return the payment instructions printed on the invoice as "
        "bank_account_number, bank_ifsc and bank_name — copy them exactly, digit for "
        "digit, and omit any that are absent rather than guessing."
        + _LINE_ITEM_RULE
    ),
    "purchase_order": (
        "You extract structured fields from a purchase order PDF's text. "
        "Return po_number, vendor_name, line_items, currency, subtotal, tax_amount, "
        "total_amount, and a confidence score per field."
        + _LINE_ITEM_RULE
    ),
    "goods_receipt_note": (
        "You extract structured fields from a goods receipt note PDF's text. "
        "Return receipt_number, po_number, received_quantity, receipt_date, "
        "and a confidence score per field."
    ),
    "rejection_notice": (
        "You extract structured fields from an invoice rejection notice PDF's text. "
        "Return invoice_number, rejection_reason, rejected_date, and a confidence score per field."
    ),
    "quotation": (
        "You extract structured fields from a vendor quotation or estimate PDF's text. "
        "Return quotation_number, vendor_name, quotation_date, reference, line_items, "
        "currency, subtotal, tax_amount, total_amount, and a confidence score per field. "
        "vendor_name is the party OFFERING the price, not the party being quoted to. "
        "A quotation often shows a price excluding tax — when it says so, subtotal is that "
        "figure and total_amount is left equal to it rather than grossed up."
        + _LINE_ITEM_RULE
    ),
}


def extract_pdf_text(pdf_path: str) -> str:
    """Runs BEFORE any Gemini call — see module docstring."""
    with fitz.open(pdf_path) as doc:
        return "\n".join(page.get_text() for page in doc)


def _build_agent(document_type: str) -> LlmAgent:
    schema = _SCHEMA_BY_DOC_TYPE[document_type]
    return LlmAgent(
        name=f"{document_type}_extraction_agent",
        model=config.GEMINI_MODEL,
        description=f"Extracts structured fields from a {document_type} document.",
        instruction=_INSTRUCTION_BY_DOC_TYPE[document_type],
        output_schema=schema,
        output_key="extraction_result",
    )


async def _run_extraction_agent(document_type: str, document_text: str):
    schema = _SCHEMA_BY_DOC_TYPE[document_type]
    agent = _build_agent(document_type)
    session_service = InMemorySessionService()
    user_id, session_id = "backend", str(uuid.uuid4())
    await session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)

    message = types.Content(role="user", parts=[types.Part(text=document_text)])
    async for _event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        pass  # we only need the final session state, collected below

    session = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    raw = session.state["extraction_result"]
    return schema.model_validate(raw)


async def extract_document_fields(document_type: str, pdf_path: str, mock_fn) -> AIResult:
    """
    mock_fn: zero-arg callable returning the correct mock *Extraction model for
    this exact document (see mock_data/mock_extractions.py) — used verbatim in
    mock mode and as the fallback if the live ADK call fails.
    """
    document_text = extract_pdf_text(pdf_path) if not config.USE_MOCK_DATA else ""

    async def ai_call():
        return await _run_extraction_agent(document_type, document_text)

    return await call_gemini_with_fallback(ai_call, mock_fn, label=f"extract:{document_type}")


async def extract_fields_from_text(document_type: str, document_text: str, fallback_fn, *, label: str) -> AIResult:
    """
    Text-in entry point used by the upload pipeline (services/ingestion_service.py).

    The path-based function above re-reads the PDF from disk; an uploaded file
    is already in memory and its text has already been pulled by PyMuPDF, so
    re-serializing it through a temp file would be pure overhead. Pipeline
    order is unchanged and still mandatory: PyMuPDF first, Gemini second — the
    model only ever sees extracted text, never PDF bytes.

    fallback_fn is the deterministic parser result for THIS document (see
    services/pdf_field_parser.py), not a hand-written constant — so a failed
    or unconfigured Gemini call degrades to fields genuinely read from the
    uploaded file rather than to fiction.
    """
    async def ai_call():
        return await _run_extraction_agent(document_type, document_text)

    return await call_gemini_with_fallback(ai_call, fallback_fn, label=label)
