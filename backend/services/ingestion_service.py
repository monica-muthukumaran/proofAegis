"""
ingestion_service.py — the pipeline that was missing: uploaded PDF in,
investigated exception out.

    validate -> store -> PyMuPDF text -> classify -> extract fields
      -> persist per-document state -> assemble matching_input
      -> deterministic match + evidence graph -> case status

Two design rules this module exists to enforce:

1. **A case holds any number of documents.** There is no fixed four-slot
   form. A real investigation accumulates evidence over days — a corrected
   invoice arrives, a late goods receipt turns up, procurement sends a
   revised PO. Uploading more documents re-runs the analysis; nothing is
   capped and nothing needs to arrive in order. Where several documents
   share a type, the most recently uploaded COMPLETED one is primary, and
   the document_id chosen for each role is recorded on the case so evidence
   citations always resolve to a real file.

2. **A missing document is a finding, never an upload error.** No goods
   receipt produces `missing_goods_receipt`; no purchase order produces
   `missing_purchase_order`. Both are legitimate analysis outcomes that
   matching_service.py already models. The only true blocker is having no
   readable vendor invoice, because there is then nothing to investigate.

Processing states are per-document and retry-safe: `queued` -> `processing`
-> `completed` | `failed`. A failed document can be retried without
disturbing the ones that succeeded, and a re-run is idempotent.
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Optional

import fitz  # PyMuPDF

from config import config
from schemas import ExceptionType
from services import history_service, pdf_field_parser
from services.document_agent import extract_fields_from_text
from services.storage_service import build_object_path, get_storage, looks_like_pdf

logger = logging.getLogger("proofaegis.ingestion")

# Per-document processing states (FR-002 / FR-014).
QUEUED = "queued"
PROCESSING = "processing"
COMPLETED = "completed"
FAILED = "failed"

SUPPORTED_TYPES = set(pdf_field_parser.DOCUMENT_TYPES)


class UploadValidationError(Exception):
    """Rejected before anything is stored. Carries an HTTP-ready reason code."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_exception_id() -> str:
    return f"EXC-{datetime.now(timezone.utc).strftime('%Y')}-{uuid.uuid4().hex[:8].upper()}"


def new_document_id() -> str:
    return f"DOC-{uuid.uuid4().hex[:12].upper()}"


# ---------------------------------------------------------------------------
# Validation (FR-002)
# ---------------------------------------------------------------------------
def validate_upload(file_name: str, data: bytes, document_type: Optional[str]) -> None:
    """Extension, magic bytes, size, and declared type. Runs before a single
    byte reaches storage, so a rejected file never costs a write."""
    if not data:
        raise UploadValidationError("empty_file", f"'{file_name}' is empty.")

    extension = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    if extension not in config.ALLOWED_UPLOAD_EXTENSIONS:
        raise UploadValidationError(
            "unsupported_file_type",
            f"'{file_name}' is not a PDF. Allowed: {sorted(config.ALLOWED_UPLOAD_EXTENSIONS)}.",
        )

    if not looks_like_pdf(data):
        raise UploadValidationError(
            "not_a_pdf",
            f"'{file_name}' has a .pdf extension but its contents are not a PDF.",
        )

    max_bytes = config.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(data) > max_bytes:
        raise UploadValidationError(
            "file_too_large",
            f"'{file_name}' is {len(data) / 1024 / 1024:.1f} MB; the limit is {config.MAX_UPLOAD_SIZE_MB} MB.",
        )

    if document_type is not None and document_type not in SUPPORTED_TYPES:
        raise UploadValidationError(
            "unsupported_document_type",
            f"'{document_type}' is not a supported document type. Allowed: {sorted(SUPPORTED_TYPES)}.",
        )


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------
def extract_text_from_bytes(data: bytes) -> str:
    """PyMuPDF, in memory. Always runs BEFORE any Gemini call."""
    with fitz.open(stream=data, filetype="pdf") as doc:
        return "\n".join(page.get_text() for page in doc)


# ---------------------------------------------------------------------------
# OCR for scanned documents
# ---------------------------------------------------------------------------
# A large share of real vendor invoices arrive as scans or phone photos with
# no text layer at all. Until now those were rejected outright ("No text layer
# found"), which for many AP teams is every second document.
#
# PyMuPDF can drive Tesseract when it is installed, so OCR is attempted only
# as a FALLBACK — a PDF with a real text layer must never be OCR'd, because
# the embedded text is exact and OCR output is a guess. When Tesseract is not
# installed the failure message says so and names the fix, instead of blaming
# the document.
_OCR_CHECKED = False
_OCR_AVAILABLE = False


def ocr_available() -> bool:
    """Whether Tesseract can actually be driven from here. Cached: the probe
    costs a subprocess and the answer cannot change mid-process."""
    global _OCR_CHECKED, _OCR_AVAILABLE
    if _OCR_CHECKED:
        return _OCR_AVAILABLE

    _OCR_CHECKED = True
    _OCR_AVAILABLE = False
    if not config.OCR_ENABLED:
        return False
    try:
        probe = fitz.open()
        page = probe.new_page()
        page.get_textpage_ocr(flags=0, full=False)
        probe.close()
        _OCR_AVAILABLE = True
    except Exception as exc:  # noqa: BLE001 — a missing binary is not a crash
        logger.info("ocr_unavailable reason=%s", exc)
    return _OCR_AVAILABLE


def extract_text_with_ocr(data: bytes) -> str:
    """Rasterize-and-read, one page at a time. Never called for a PDF that
    already has a text layer."""
    out = []
    with fitz.open(stream=data, filetype="pdf") as document:
        for page in document:
            try:
                textpage = page.get_textpage_ocr(flags=0, dpi=config.OCR_DPI, full=True)
                out.append(page.get_text(textpage=textpage))
            except Exception as exc:  # noqa: BLE001
                logger.warning("ocr_page_failed error=%s", exc)
    return "\n".join(out)



# ---------------------------------------------------------------------------
# Single-document processing
# ---------------------------------------------------------------------------
async def process_document(document: dict, pdf_bytes: bytes) -> dict:
    """
    Runs text extraction -> classification -> field extraction for ONE
    document and returns the updated record. Never raises for a bad document:
    a failure is recorded on the record as `failed` with a reason, so one
    unreadable PDF cannot take down a batch or a case.
    """
    document["processing_state"] = PROCESSING
    document["attempts"] = document.get("attempts", 0) + 1
    document["error"] = None

    try:
        text = extract_text_from_bytes(pdf_bytes)
    except Exception as exc:  # noqa: BLE001 — a corrupt PDF is a data problem, not a crash
        logger.warning("pdf_text_extraction_failed doc=%s error=%s", document["document_id"], exc)
        document["processing_state"] = FAILED
        document["error"] = "Could not read text from this PDF. It may be corrupt or image-only."
        document["processed_at"] = _now()
        return document

    if not text.strip():
        # No embedded text: a scan or a photo. OCR is the fallback, never the
        # first choice — embedded text is exact and OCR output is inference.
        if ocr_available():
            try:
                text = extract_text_with_ocr(pdf_bytes)
                document["text_source"] = "ocr"
            except Exception as exc:  # noqa: BLE001
                logger.warning("ocr_failed doc=%s error=%s", document["document_id"], exc)
                text = ""
        if not text.strip():
            document["processing_state"] = FAILED
            document["error"] = (
                "No text layer found — this looks like a scan or a photo. "
                + ("OCR ran but could not read it; try a clearer scan."
                   if ocr_available() else
                   "OCR is not enabled on this server: install Tesseract and set "
                   "OCR_ENABLED=true to read scanned documents.")
            )
            document["processed_at"] = _now()
            return document
    document.setdefault("text_source", "embedded")

    document["text_characters"] = len(text)

    # Classification: an explicit user-assigned type always wins over detection.
    if not document.get("document_type"):
        detected, detect_confidence = pdf_field_parser.classify_document(text)
        if detected is None:
            document["processing_state"] = FAILED
            document["error"] = (
                "Could not tell what kind of document this is. Set the document type manually and retry."
            )
            document["processed_at"] = _now()
            return document
        document["document_type"] = detected
        document["type_source"] = "detected"
        document["type_confidence"] = detect_confidence
    else:
        document.setdefault("type_source", "user")
        document.setdefault("type_confidence", 1.0)

    document_type = document["document_type"]

    # Deterministic parse first — this is both the real extraction when Gemini
    # is off and the fallback when it fails, so it is never skipped.
    try:
        parsed = pdf_field_parser.parse_document(document_type, text, pdf_bytes)
    except Exception as exc:  # noqa: BLE001
        logger.warning("deterministic_parse_failed doc=%s error=%s", document["document_id"], exc)
        document["processing_state"] = FAILED
        document["error"] = f"Could not extract fields from this {document_type.replace('_', ' ')}."
        document["processed_at"] = _now()
        return document

    result = await extract_fields_from_text(
        document_type, text, lambda: parsed, label=f"extract:{document_type}:{document['document_id']}",
    )

    document["extraction"] = result.data
    # ai_fallback reports "ai" or "mock"; for an uploaded file "mock" means the
    # deterministic parser ran on the real bytes, so label it as what it is.
    document["extraction_source"] = "ai" if result.source == "ai" else "deterministic_parser"
    document["extraction_error"] = result.error
    document["field_confidences"] = result.data.get("field_confidences", [])
    document["confidence"] = pdf_field_parser.average_confidence(parsed)
    # Text recovered by OCR is a reading of an image, not the document's own
    # characters. Every field derived from it inherits that uncertainty, so
    # the document-level confidence is capped and the source recorded.
    if document.get("text_source") == "ocr":
        document["confidence"] = round(min(document["confidence"], 0.75), 3)
    document["processing_state"] = COMPLETED
    document["processed_at"] = _now()
    return document


# ---------------------------------------------------------------------------
# Assembling matching_input from however many documents a case holds
# ---------------------------------------------------------------------------
def _completed_of_type(documents: list[dict], document_type: str) -> list[dict]:
    return [
        d for d in documents
        if d.get("document_type") == document_type
        and d.get("processing_state") == COMPLETED
        and d.get("extraction")
    ]


def _primary_by_type(documents: list[dict], document_type: str) -> Optional[dict]:
    """Most recently uploaded COMPLETED document of this type. A case may hold
    several — a revised invoice supersedes the original — and the newest
    successfully-processed one is what the analysis uses."""
    candidates = _completed_of_type(documents, document_type)
    if not candidates:
        return None
    return max(candidates, key=lambda d: d.get("uploaded_at", ""))


def normalize_reference(value) -> str:
    """
    Reference numbers are the same identifier written differently by every
    system that touches them: PO/SRPL/26/19451 on the purchase order,
    PO-SRPL-26-19451 in an ERP export, "po srpl 26 19451" after a bad copy
    and paste. Comparing them raw makes two documents about the same order
    look unrelated, so every separator and case difference is flattened
    before comparison. Digits and letters are preserved exactly — this
    normalizes punctuation, never content.
    """
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _select_by_reference(candidates: list[dict], reference: str, field: str = "po_number") -> Optional[dict]:
    """The candidate whose `field` matches `reference`, newest first. None
    when nothing matches — which is a meaningful answer, not a failure."""
    if not reference:
        return None
    target = normalize_reference(reference)
    matches = [
        d for d in candidates
        if normalize_reference((d.get("extraction") or {}).get(field)) == target
    ]
    if not matches:
        return None
    return max(matches, key=lambda d: d.get("uploaded_at", ""))


def _select_related(candidates: list[dict], invoice_po_number, role: str) -> tuple[Optional[dict], Optional[dict]]:
    """
    Picks the document that belongs to the SAME order as the invoice, and
    reports when that could not be established.

    Selecting by upload recency alone was an outright correctness bug: upload
    an unrelated purchase order last and the case would compare the invoice
    against it, then present the resulting nonsense — a 2270% price variance
    between a plumbing invoice and a lighting PO — with full confidence.

    The invoice states which order it belongs to, so that is what selects the
    counterpart document. Recency is only the fallback for when no candidate
    carries a matching reference, and taking that fallback is recorded as an
    `unverified_link` warning rather than hidden, because a match assembled
    from documents that may not belong together is exactly the thing a
    reviewer must be told about.

    Returns (chosen_document, warning_or_None).
    """
    if not candidates:
        return None, None

    matched = _select_by_reference(candidates, invoice_po_number)
    if matched is not None:
        return matched, None

    chosen = max(candidates, key=lambda d: d.get("uploaded_at", ""))
    chosen_reference = (chosen.get("extraction") or {}).get("po_number")

    # Nothing to reconcile against: the invoice never named an order.
    if not invoice_po_number:
        return chosen, {
            "code": "unverified_link",
            "role": role,
            "document_id": chosen.get("document_id"),
            "detail": (
                f"The invoice does not state a purchase order number, so the {role.replace('_', ' ')} "
                f"could not be confirmed to belong to the same order. The most recently uploaded one "
                f"was used. Verify it is the right document before acting on this case."
            ),
        }

    return chosen, {
        "code": "reference_mismatch",
        "role": role,
        "document_id": chosen.get("document_id"),
        "detail": (
            f"The invoice cites purchase order {invoice_po_number}, but no uploaded "
            f"{role.replace('_', ' ')} carries that number"
            + (f" (the one used states {chosen_reference})" if chosen_reference else "")
            + ". These documents may describe different orders — verify before acting on this case."
        ),
    }


def build_matching_input(documents: list[dict], ds=None,
                        exception_id: Optional[str] = None) -> tuple[Optional[dict], dict]:
    """
    Returns (matching_input, source_documents).

    matching_input is None when there is no usable vendor invoice — the one
    genuine blocker. source_documents maps each role to the document_id that
    supplied it, so every number in the evidence graph traces to a real file.
    """
    invoice_doc = _primary_by_type(documents, "vendor_invoice")

    if invoice_doc is None:
        return None, {}

    invoice = invoice_doc.get("extraction", {})

    # The invoice names the order it belongs to; that is what selects every
    # counterpart document. See _select_related for why recency alone is wrong.
    invoice_po_number = invoice.get("po_number")
    po_doc, po_warning = _select_related(
        _completed_of_type(documents, "purchase_order"), invoice_po_number, "purchase_order")
    grn_doc, grn_warning = _select_related(
        _completed_of_type(documents, "goods_receipt_note"), invoice_po_number, "goods_receipt_note")
    rejection_doc = _primary_by_type(documents, "rejection_notice")
    quotation_doc = _primary_by_type(documents, "quotation")
    quotation = quotation_doc.get("extraction", {}) if quotation_doc else {}
    link_warnings = [w for w in (po_warning, grn_warning) if w]
    po = po_doc.get("extraction", {}) if po_doc else {}
    grn = grn_doc.get("extraction", {}) if grn_doc else {}

    invoice_quantity = invoice.get("quantity")
    invoice_total = invoice.get("total_amount")

    matching_input = {
        "vendor_name": invoice.get("vendor_name"),
        "po_vendor_name": po.get("vendor_name") if po_doc else None,
        "po_number": po.get("po_number") if po_doc else None,
        "invoice_po_number": invoice.get("po_number"),
        "purchase_order_exists": po_doc is not None,
        "goods_receipt_exists": grn_doc is not None,
        "po_unit_price": po.get("unit_price") if po_doc else None,
        "invoice_unit_price": invoice.get("unit_price"),
        "po_quantity": po.get("quantity") if po_doc else None,
        "received_quantity": grn.get("received_quantity") if grn_doc else None,
        "invoice_quantity": invoice_quantity,
        "invoice_amount": invoice_total or 0,
        "tax_amount": invoice.get("tax_amount"),
        "po_tax_amount": po.get("tax_amount") if po_doc else None,
        "invoice_total": invoice_total,
        "po_total": po.get("total_amount") if po_doc else None,
        # Itemized rows, when the documents carry them. Comparing pre-tax
        # subtotals matters as much as the rows: an invoice showing GST
        # against a PO quoted ex-tax differs on `total` for a reason that is
        # not a variance at all.
        "invoice_subtotal": invoice.get("subtotal"),
        "po_subtotal": po.get("subtotal") if po_doc else None,
        "invoice_line_items": invoice.get("line_items") or [],
        "po_line_items": (po.get("line_items") or []) if po_doc else [],
        "currency": invoice.get("currency"),
        # A quotation is evidence rather than a matching input, but the order
        # raised from it is checkable against it — the one link in
        # offer -> order -> delivery -> invoice that nothing else verifies.
        "quotation_total": (quotation.get("subtotal") or quotation.get("total_amount")
                            if quotation_doc else None),
    }

    # --- Checks that need every other case in the workspace ---------------
    # A duplicate, cumulative over-billing and a changed bank account are
    # invisible from inside one case by construction. `ds` is optional so the
    # matching input can still be assembled in isolation (tests, and the
    # readiness preview before a case is saved).
    if ds is not None:
        prior_invoices = ds.find_documents_by_type("vendor_invoice",
                                                    exclude_exception_id=exception_id)
        matching_input["duplicate_of"] = history_service.find_duplicate_invoices(
            invoice_doc, prior_invoices)
        matching_input["payment_detail_changes"] = history_service.find_payment_detail_changes(
            invoice_doc, prior_invoices)
        matching_input["po_billing"] = history_service.cumulative_billing(
            matching_input["po_number"] or invoice.get("po_number"),
            matching_input["po_total"],
            invoice_doc,
            prior_invoices,
        )
        # Price drift needs the tolerance to know what "inside tolerance every
        # month" meant for this vendor, so it is resolved here rather than
        # assumed. The whole finding is that each rise cleared THAT number.
        from services import case_service

        tolerance = case_service.tolerance_for(ds, matching_input)
        matching_input["price_drift"] = history_service.detect_price_drift(
            invoice_doc, prior_invoices, tolerance["price_variance_percent"])

    source_documents = {
        "vendor_invoice": invoice_doc["document_id"],
        "purchase_order": po_doc["document_id"] if po_doc else None,
        "goods_receipt_note": grn_doc["document_id"] if grn_doc else None,
        "rejection_notice": rejection_doc["document_id"] if rejection_doc else None,
        "quotation": quotation_doc["document_id"] if quotation_doc else None,
        # Empty on the normal path. Non-empty means at least one document was
        # paired with the invoice on recency rather than on a matching
        # reference, and the UI must say so.
        "link_warnings": link_warnings,
    }
    return matching_input, source_documents


def progress(documents: list[dict]) -> dict:
    """Per-document processing state for the upload progress display.

    The backend already tracked queued/processing/completed/failed per
    document and never exposed it, so the UI could only show a bar that hit
    100% when the bytes had been sent and then sat there for the entire
    extraction. This is what makes the wait legible.
    """
    ordered = sorted(documents, key=lambda d: d.get("uploaded_at", ""))
    done = sum(1 for d in ordered if d.get("processing_state") in (COMPLETED, FAILED))
    active = next((d for d in ordered if d.get("processing_state") == PROCESSING), None)
    return {
        "total": len(ordered),
        "completed": sum(1 for d in ordered if d.get("processing_state") == COMPLETED),
        "failed": sum(1 for d in ordered if d.get("processing_state") == FAILED),
        "pending": sum(1 for d in ordered if d.get("processing_state") in (QUEUED, PROCESSING)),
        "finished": done,
        "percent": round(100 * done / len(ordered)) if ordered else 0,
        "active_document": None if active is None else {
            "document_id": active.get("document_id"),
            "file_name": active.get("file_name"),
            "document_type": active.get("document_type"),
        },
        "documents": [
            {
                "document_id": d.get("document_id"),
                "file_name": d.get("file_name"),
                "document_type": d.get("document_type"),
                "processing_state": d.get("processing_state"),
                "error": d.get("error"),
            }
            for d in ordered
        ],
    }


def group_by_reference(documents: list[dict]) -> dict:
    """
    Which uploaded documents belong to the same order.

    A case is meant to hold one investigation. Nothing stopped a batch drop
    from mixing two unrelated orders into one, and the analysis then compared
    an invoice against a purchase order for entirely different work — the
    failure that prompted reference-based document selection in the first
    place. Selection fixes the comparison; this surfaces the problem at upload
    time, where a person can still split the batch.

    Returns {"groups": [...], "is_mixed": bool}. Documents that state no
    reference are listed as unassigned rather than forced into a group: a
    goods receipt with no PO number could belong to any of them.
    """
    groups: dict[str, dict] = {}
    unassigned = []

    for document in documents:
        extraction = document.get("extraction") or {}
        # Grouped on the PURCHASE ORDER only. A quotation carries its own
        # number by nature, and counting that as a second "order" flagged a
        # perfectly ordinary quotation + PO + invoice set as mixed.
        reference = extraction.get("po_number")
        entry = {
            "document_id": document.get("document_id"),
            "file_name": document.get("file_name"),
            "document_type": document.get("document_type"),
        }
        if not reference:
            unassigned.append(entry)
            continue
        key = normalize_reference(reference)
        group = groups.setdefault(key, {"reference": reference, "documents": []})
        group["documents"].append(entry)

    ordered = sorted(groups.values(), key=lambda g: -len(g["documents"]))
    return {
        "groups": ordered,
        "unassigned": unassigned,
        "is_mixed": len(ordered) > 1,
        "detail": (
            f"These {len(documents)} documents reference {len(ordered)} different orders "
            f"({', '.join(g['reference'] for g in ordered)}). A case should hold one order — "
            f"consider splitting them, or confirm they genuinely belong together."
        ) if len(ordered) > 1 else None,
    }


def readiness(documents: list[dict]) -> dict:
    """What the UI needs to explain the current state of a case honestly:
    what is present, what is missing, and whether analysis can run at all."""
    present = {t: [] for t in SUPPORTED_TYPES}
    for d in documents:
        doc_type = d.get("document_type")
        if doc_type in present:
            present[doc_type].append(d)

    completed = {t: [d for d in docs if d.get("processing_state") == COMPLETED] for t, docs in present.items()}
    has_invoice = bool(completed["vendor_invoice"])

    missing_optional = [t for t in ("purchase_order", "goods_receipt_note") if not completed[t]]
    return {
        "can_analyze": has_invoice,
        "blocking_reason": None if has_invoice else (
            "Add a vendor invoice to analyze this case. Every other document is optional — "
            "a missing purchase order or goods receipt is reported as a finding, not an error."
        ),
        "document_counts": {t: len(docs) for t, docs in present.items()},
        "completed_counts": {t: len(docs) for t, docs in completed.items()},
        "missing_document_types": missing_optional,
        "total_documents": len(documents),
        "processing_count": sum(1 for d in documents if d.get("processing_state") in (QUEUED, PROCESSING)),
        "failed_count": sum(1 for d in documents if d.get("processing_state") == FAILED),
        # Warns when one case is holding documents from several orders.
        "reference_groups": group_by_reference(
            [d for d in documents if d.get("processing_state") == COMPLETED]),
    }


# ---------------------------------------------------------------------------
# Case-level orchestration
# ---------------------------------------------------------------------------
def store_document_bytes(workspace_id: str, exception_id: str, document_id: str, data: bytes) -> str:
    object_path = build_object_path(workspace_id, exception_id, document_id)
    get_storage().upload(object_path, data)
    return object_path


def read_document_bytes(storage_path: str) -> bytes:
    return get_storage().download(storage_path)


async def ingest_documents(ds, exception_id: str, uploads: list[dict], workspace_id: str,
                            actor: str) -> list[dict]:
    """
    uploads: [{file_name, data (bytes), document_type (optional)}]

    Stores each file, processes it, and persists the resulting document
    record. Validation has already run in the route layer, so anything
    reaching here is a real PDF within the size limit.
    """
    records = []
    for upload in uploads:
        document_id = new_document_id()
        data = upload["data"]

        record = {
            "document_id": document_id,
            "exception_id": exception_id,
            "workspace_id": workspace_id,
            "file_name": upload["file_name"],
            "document_type": upload.get("document_type"),
            "size_bytes": len(data),
            "content_type": "application/pdf",
            "processing_state": QUEUED,
            "uploaded_at": _now(),
            "uploaded_by": actor,
            "attempts": 0,
        }

        try:
            record["storage_path"] = store_document_bytes(workspace_id, exception_id, document_id, data)
        except Exception as exc:  # noqa: BLE001 — storage outage must not lose the audit of the attempt
            logger.error("document_store_failed doc=%s error=%s", document_id, exc)
            record["processing_state"] = FAILED
            record["error"] = "Could not store this file. Try again."
            ds.save_document(record)
            records.append(record)
            continue

        # Persisted as `queued` BEFORE the slow part, so a progress poll can
        # see the document exists and is waiting. Without this write, nothing
        # is observable until the whole batch finishes and the UI has no
        # honest answer to "what is it doing?".
        ds.save_document(record)

        # And again as `processing` the moment work starts on it, so the
        # progress poll can name the document currently being read rather
        # than only counting what has finished.
        record["processing_state"] = PROCESSING
        ds.save_document(record)

        record = await process_document(record, data)
        ds.save_document(record)
        records.append(record)

    return records


async def retry_document(ds, exception_id: str, document_id: str) -> Optional[dict]:
    """Re-processes one previously failed document from its stored bytes.
    Retry-safe: the file is already in storage, so this never re-uploads."""
    record = ds.get_document(document_id)
    if record is None or record.get("exception_id") != exception_id:
        return None
    storage_path = record.get("storage_path")
    if not storage_path:
        record["processing_state"] = FAILED
        record["error"] = "This document has no stored file to retry."
        ds.save_document(record)
        return record

    data = read_document_bytes(storage_path)
    record = await process_document(record, data)
    ds.save_document(record)
    return record


def run_analysis(ds, exception_id: str) -> dict:
    """
    Rebuilds matching_input from every document currently on the case and
    re-runs the deterministic matcher. Called after each upload batch and by
    POST /analyze. Idempotent — safe to run as often as you like.

    Nothing in here is AI-assisted: the exception type, the money, the match
    score, and the status all come from matching_service.py.
    """
    from services import case_service  # local import avoids a circular import at module load

    documents = ds.get_documents(exception_id)
    state = readiness(documents)

    exception = ds.get_exception(exception_id) or {}
    matching_input, source_documents = build_matching_input(documents, ds, exception_id)

    if matching_input is None:
        # Nothing extractable to match on yet. Record readiness so the UI can
        # say WHY, but never clear a matching_input the case already has —
        # seeded demo cases carry theirs directly and must survive this.
        ds.update_case_fields(exception_id, {
            "readiness": state,
            "processing_state": COMPLETED if state["processing_count"] == 0 else PROCESSING,
            "updated_at": _now(),
        })
        return {"analyzed": False, "readiness": state}

    ds.update_case_fields(exception_id, {
        "matching_input": matching_input,
        "source_documents": source_documents,
        "readiness": state,
        "updated_at": _now(),
    })

    match_result = case_service.get_match_result(exception_id)
    if match_result is None:
        return {"analyzed": False, "readiness": state}

    # Carry the identifying fields the queue and detail views display. These
    # come from the extraction, not from anything a user typed.
    invoice_doc = _primary_by_type(documents, "vendor_invoice")
    invoice = invoice_doc.get("extraction", {}) if invoice_doc else {}

    updates = {
        "invoice_id": invoice.get("invoice_number") or exception.get("invoice_id"),
        "vendor_name": invoice.get("vendor_name") or exception.get("vendor_name"),
        "purchase_order_id": matching_input.get("po_number") or invoice.get("po_number"),
        "invoice_amount": matching_input.get("invoice_amount"),
        "po_amount": matching_input.get("po_total"),
        "currency": exception.get("currency", "INR"),
        "exception_type": match_result.exception_type.value,
        "match_score": match_result.match_score,
        "financial_impact": match_result.financial_impact,
        "risk_level": match_result.risk_level,
        "assigned_team": match_result.recommended_owner,
        "processing_state": COMPLETED,
        "updated_at": _now(),
    }

    # FR-011: the pipeline owns system-set statuses only, and only while the
    # case is still in a system-set state. Once a human has moved it to
    # awaiting_vendor (or anything else user-settable), re-analysis must not
    # yank it back.
    from schemas import SYSTEM_SET_STATUSES

    current_status = exception.get("status", "received")
    if current_status in SYSTEM_SET_STATUSES:
        clean = match_result.exception_type == ExceptionType.NO_EXCEPTION
        updates["status"] = "cleared" if clean else "exception_detected"

    ds.update_case_fields(exception_id, updates)
    return {
        "analyzed": True,
        "readiness": state,
        "match_score": match_result.match_score,
        "exception_type": match_result.exception_type.value,
        "financial_impact": match_result.financial_impact,
    }


def create_case(ds, workspace_id: str, actor: str, metadata: Optional[dict] = None) -> dict:
    """Creates an empty case. Documents are added afterwards, in any number
    and any order."""
    metadata = metadata or {}
    exception_id = new_exception_id()
    now = _now()
    case = {
        "exception_id": exception_id,
        "workspace_id": workspace_id,
        "invoice_id": metadata.get("invoice_id"),
        "vendor_name": metadata.get("vendor_name"),
        "purchase_order_id": metadata.get("purchase_order_id"),
        "business_unit": metadata.get("business_unit"),
        "currency": metadata.get("currency", "INR"),
        "invoice_amount": None,
        "po_amount": None,
        "status": "received",
        "processing_state": QUEUED,
        "origin": "upload",
        "created_by": actor,
        "created_at": now,
        "updated_at": now,
        "matching_input": None,
        "source_documents": {},
        "readiness": readiness([]),
    }
    ds.create_exception(case)
    return case


def run_ingestion(ds, exception_id: str, uploads: list[dict], workspace_id: str, actor: str) -> dict:
    """Synchronous wrapper the Flask route calls: process this batch, then
    re-analyze the whole case."""
    ds.update_case_fields(exception_id, {"processing_state": PROCESSING, "updated_at": _now()})
    records = asyncio.run(ingest_documents(ds, exception_id, uploads, workspace_id, actor))
    analysis = run_analysis(ds, exception_id)
    return {"documents": records, "analysis": analysis}
