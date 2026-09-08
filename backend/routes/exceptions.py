"""
routes/exceptions.py — FR-001 (queue), FR-005/006 (match workspace),
FR-008/009 (evidence graph), FR-010 (resolution), FR-011/012 (status + audit).

Per the pack's explicit note on FR-001: no server-side filtering. The queue
endpoint returns the full (3-10 record) dataset once; search/filter/sort
happens client-side in the frontend.

Every route is wrapped in @require_auth (see auth.py) — lenient until
config.AUTH_REQUIRED is turned on, so this is a no-op for the existing
demo/mock-mode flow, but g.user gets populated whenever a real token IS
sent, which is what lets update_status() trust the verified identity
instead of a client-supplied 'actor' string.
"""
from __future__ import annotations

import asyncio
import io

from flask import Blueprint, g, jsonify, request, send_file

from auth import current_user_email, current_user_role, current_workspace_id, require_auth
from config import config
from datastore import get_datastore
from schemas import ALL_STATUSES, SYSTEM_SET_STATUSES, USER_SETTABLE_STATUSES
from services import approval_service, case_service, ingestion_service
from services.audit_service import build_event
from services.resolution_agent import draft_resolution
from services.storage_service import StorageError, get_storage

bp = Blueprint("exceptions", __name__, url_prefix="/api/exceptions")


def _visible_case(ds, exception_id: str):
    """The case, or None when it does not exist OR belongs to someone else.

    Those two are deliberately one answer. Returning 403 for "exists but not
    yours" would confirm the id is real to anyone willing to guess at one, so
    every caller below turns a None from here into the same 404 it already
    returned for a genuinely unknown id.

    Every route that reads or writes a single case goes through this. The
    routes that then call into services/case_service.py rely on it having run
    first — those functions take an exception_id and fetch unscoped, which is
    correct for them (a background re-analysis has no request identity) and
    is exactly why the check belongs here, at the edge, once.
    """
    return ds.get_exception(exception_id, current_workspace_id())


@bp.get("")
@require_auth
def list_exceptions():
    """FR-001. Each record carries its DERIVED match summary (type, score,
    impact, risk, owner) recomputed on read, so the queue can never disagree
    with the match workspace. Filtering/sorting stays client-side per the
    pack's explicit note."""
    ds = get_datastore()
    workspace_id = current_workspace_id()
    return jsonify([case_service.summarize_exception(e)
                    for e in ds.list_exceptions(workspace_id)])


@bp.get("/<exception_id>")
@require_auth
def get_exception(exception_id: str):
    ds = get_datastore()
    exc = _visible_case(ds, exception_id)
    if exc is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(case_service.summarize_exception(exc))


@bp.get("/<exception_id>/documents")
@require_auth
def get_documents(exception_id: str):
    ds = get_datastore()
    if _visible_case(ds, exception_id) is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(ds.get_documents(exception_id))


@bp.get("/<exception_id>/progress")
@require_auth
def get_progress(exception_id: str):
    """Per-document processing state while an upload batch is being read.

    The upload request itself stays open until the whole batch is done, so
    the client polls this in parallel to say WHICH document is being read
    rather than showing a full bar and the word "Processing" for the entire
    wait.
    """
    ds = get_datastore()
    if _visible_case(ds, exception_id) is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(ingestion_service.progress(ds.get_documents(exception_id)))


@bp.get("/<exception_id>/match")
@require_auth
def get_match(exception_id: str):
    if _visible_case(get_datastore(), exception_id) is None:
        return jsonify({"error": "not_found"}), 404
    result = case_service.get_match_result(exception_id)
    if result is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(result.model_dump())


@bp.get("/<exception_id>/graph")
@require_auth
def get_graph(exception_id: str):
    if _visible_case(get_datastore(), exception_id) is None:
        return jsonify({"error": "not_found"}), 404
    graph = case_service.get_evidence_graph(exception_id)
    if graph is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(graph.model_dump())


@bp.get("/<exception_id>/reasoning")
@require_auth
def get_reasoning(exception_id: str):
    """FR-007 — cached Exception Reasoning Agent output, if already generated."""
    ds = get_datastore()
    if _visible_case(ds, exception_id) is None:
        return jsonify({"error": "not_found"}), 404
    existing = ds.get_reasoning(exception_id)
    if existing:
        return jsonify(existing)
    return jsonify({"error": "not_generated"}), 404


@bp.post("/<exception_id>/reasoning/generate")
@require_auth
def generate_reasoning(exception_id: str):
    ds = get_datastore()
    if _visible_case(ds, exception_id) is None:
        return jsonify({"error": "not_found"}), 404

    ai_result = asyncio.run(case_service.get_exception_reasoning(exception_id))
    if ai_result is None:
        return jsonify({
            "error": "not_analyzed",
            "detail": "This case has no match result yet. Upload a vendor invoice first.",
        }), 409

    reasoning = ai_result.data
    reasoning["_ai_source"] = ai_result.source  # FR-013: mock-mode indicator
    ds.save_reasoning(exception_id, reasoning)

    triggered_by = current_user_email(fallback="unknown_user")
    ds.append_audit_event(exception_id, build_event(
        exception_id, actor="system", action="exception_reasoning_generated",
        note=f"source={ai_result.source}; triggered_by={triggered_by}",
    ).model_dump())

    return jsonify(reasoning)


@bp.get("/<exception_id>/trust")
@require_auth
def get_trust_check(exception_id: str):
    """What the model said the money was, and what the code computed.

    Present only once the reasoning agent has run on this case — before that
    there is no model figure to have checked, and reporting agreement would be
    reporting a comparison that never happened.
    """
    case = _visible_case(get_datastore(), exception_id)
    if case is None:
        return jsonify({"error": "not_found"}), 404
    check = case.get("trust_check")
    if not check:
        return jsonify({"error": "not_checked"}), 404
    return jsonify(check)


@bp.get("/<exception_id>/hypotheses")
@require_auth
def get_hypotheses(exception_id: str):
    """FR-007b — cached hypothesis set, if already generated."""
    ds = get_datastore()
    if _visible_case(ds, exception_id) is None:
        return jsonify({"error": "not_found"}), 404
    existing = ds.get_hypotheses(exception_id)
    if existing:
        return jsonify(existing)
    return jsonify({"error": "not_generated"}), 404


@bp.post("/<exception_id>/hypotheses/generate")
@require_auth
def generate_hypotheses_route(exception_id: str):
    """Ranked candidate explanations for the computed finding.

    This is the one agent whose output contains no numbers at all — see
    services/hypothesis_agent.py. There is nothing here for the financial
    guardrail to check, because there is nothing financial in it.
    """
    ds = get_datastore()
    if _visible_case(ds, exception_id) is None:
        return jsonify({"error": "not_found"}), 404

    ai_result = asyncio.run(case_service.get_investigation_hypotheses(exception_id))
    if ai_result is None:
        return jsonify({
            "error": "not_analyzed",
            "detail": "This case has no match result yet. Upload a vendor invoice first.",
        }), 409

    hypotheses = ai_result.data
    hypotheses["_ai_source"] = ai_result.source  # FR-013: mock-mode indicator
    ds.save_hypotheses(exception_id, hypotheses)

    ds.append_audit_event(exception_id, build_event(
        exception_id, actor="system", action="investigation_hypotheses_generated",
        note=(f"source={ai_result.source}; "
              f"triggered_by={current_user_email(fallback='unknown_user')}"),
    ).model_dump())

    return jsonify(hypotheses)


@bp.get("/<exception_id>/resolution")
@require_auth
def get_resolution(exception_id: str):
    ds = get_datastore()
    if _visible_case(ds, exception_id) is None:
        return jsonify({"error": "not_found"}), 404
    existing = ds.get_resolution_draft(exception_id)
    if existing:
        return jsonify(existing)
    return jsonify({"error": "not_generated"}), 404


@bp.post("/<exception_id>/resolution/generate")
@require_auth
def generate_resolution(exception_id: str):
    ds = get_datastore()
    exc = _visible_case(ds, exception_id)
    if exc is None:
        return jsonify({"error": "not_found"}), 404

    match_result = case_service.get_match_result(exception_id)
    if match_result is None:
        return jsonify({
            "error": "not_analyzed",
            "detail": "This case has no match result yet. Upload a vendor invoice first.",
        }), 409
    graph = case_service.get_evidence_graph(exception_id)
    fallback_fn = case_service.get_resolution_fallback(exception_id)
    if fallback_fn is None:
        return jsonify({"error": "not_analyzed"}), 409

    case_context = {"exception_id": exception_id, "vendor_name": exc.get("vendor_name"),
                     "invoice_id": exc.get("invoice_id"), "currency": exc.get("currency", "INR")}

    ai_result = asyncio.run(draft_resolution(match_result, graph, case_context, fallback_fn))
    draft = ai_result.data
    draft["_ai_source"] = ai_result.source  # FR-013: mock-mode indicator
    ds.save_resolution_draft(exception_id, draft)

    triggered_by = current_user_email(fallback="unknown_user")
    ds.append_audit_event(exception_id, build_event(
        exception_id, actor="system", action="resolution_draft_generated",
        note=f"source={ai_result.source}; triggered_by={triggered_by}",
    ).model_dump())

    return jsonify(draft)


@bp.get("/<exception_id>/audit")
@require_auth
def get_audit(exception_id: str):
    ds = get_datastore()
    if _visible_case(ds, exception_id) is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(ds.get_audit_events(exception_id))


@bp.patch("/<exception_id>/status")
@require_auth
def update_status(exception_id: str):
    """FR-011: only user-settable statuses may be set through this endpoint —
    system-set statuses (received, processing, exception_detected, assigned)
    are pipeline-only and rejected here even if a client tries to send one.

    The audit trail's actor is the VERIFIED token identity whenever one is
    present — a client-supplied 'actor' field in the request body is only
    ever used as a fallback for the still-supported demo-auth flow, never
    allowed to override a real signed-in identity."""
    ds = get_datastore()
    exc = _visible_case(ds, exception_id)
    if exc is None:
        return jsonify({"error": "not_found"}), 404

    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    actor = current_user_email(fallback=body.get("actor", "unknown_user"))
    note = body.get("note")

    if new_status not in ALL_STATUSES:
        return jsonify({"error": "invalid_status", "allowed": sorted(ALL_STATUSES)}), 400
    if new_status in SYSTEM_SET_STATUSES:
        return jsonify({
            "error": "status_is_system_set",
            "detail": f"'{new_status}' is set automatically by the pipeline, not user-selectable.",
            "allowed": sorted(USER_SETTABLE_STATUSES),
        }), 400

    # Authority is checked BEFORE the status moves. Recording who approved
    # something they were not allowed to approve is a log of a control
    # failure, not a control.
    try:
        match_result = case_service.get_match_result(exception_id)
        approval_service.check_approval(
            new_status,
            actor=actor,
            actor_role=current_user_role(),
            case=exc,
            documents=ds.get_documents(exception_id),
            amount=float(match_result.financial_impact) if match_result else 0.0,
            policy=ds.get_approval_policy(),
        )
    except approval_service.ApprovalDenied as denied:
        ds.append_audit_event(exception_id, build_event(
            exception_id, actor=actor, action="status_change_refused",
            from_status=exc["status"], to_status=new_status, note=denied.detail,
        ).model_dump())
        return jsonify({"error": denied.code, "detail": denied.detail, **denied.context}), 403

    old_status = exc["status"]
    updated = ds.update_status(exception_id, new_status)
    ds.append_audit_event(exception_id, build_event(
        exception_id, actor=actor, action="status_changed",
        from_status=old_status, to_status=new_status, note=note,
    ).model_dump())

    return jsonify(updated)


# ---------------------------------------------------------------------------
# P0 ingestion — create a case, then add any number of documents to it.
#
# There is deliberately no fixed set of upload slots. A case accepts as many
# PDFs as an investigation needs, in any order, across as many requests as
# the user likes; each batch re-runs the deterministic analysis. A missing
# purchase order or goods receipt is reported as a FINDING by
# matching_service.py, never rejected as an upload error — the only genuine
# blocker is having no readable vendor invoice, because there is then
# nothing to investigate.
# ---------------------------------------------------------------------------
@bp.post("")
@require_auth
def create_exception():
    """Creates an empty case. Optional body fields (title, invoice_id,
    vendor_name, purchase_order_id, business_unit, currency) are convenience
    labels only — every figure the app acts on comes from extraction, never
    from these.

    `title` is what a person calls this case ("Q3 pipe delivery dispute").
    Optional by design: a case with no title is displayed under its generated
    exception id exactly as before, and nothing in the product requires one.
    """
    ds = get_datastore()
    body = request.get_json(silent=True) or {}
    actor = current_user_email(fallback=body.get("actor", "unknown_user"))
    workspace_id = current_workspace_id()

    allowed = {"title", "invoice_id", "vendor_name", "purchase_order_id",
               "business_unit", "currency"}
    metadata = {k: v for k, v in body.items() if k in allowed and v}

    case = ingestion_service.create_case(ds, workspace_id, actor, metadata)
    ds.append_audit_event(case["exception_id"], build_event(
        case["exception_id"], actor=actor, action="case_created",
        to_status="received",
        note=(f'Case opened for document upload as "{case["title"]}".' if case.get("title")
              else "Case opened for document upload."),
    ).model_dump())
    return jsonify(case), 201


@bp.patch("/<exception_id>")
@require_auth
def rename_exception(exception_id: str):
    """Set or clear this case's title.

    Separate from PATCH /status because they are different kinds of change and
    conflating them would put a rename through the approval policy. A title
    carries no authority: it is a label, it is checked by nothing, and
    changing it can never move a case toward being paid.

    Send `{"title": null}` or an empty string to go back to displaying the
    exception id. Renaming IS audited — not because a title matters to a
    control, but because "the case I approved was called something else" is a
    question an auditor can ask, and it should have an answer.
    """
    ds = get_datastore()
    exc = _visible_case(ds, exception_id)
    if exc is None:
        return jsonify({"error": "not_found"}), 404

    body = request.get_json(silent=True) or {}
    if "title" not in body:
        return jsonify({
            "error": "nothing_to_update",
            "detail": "Send a 'title' field. Use null or \"\" to clear it.",
        }), 400

    previous = exc.get("title")
    title = ingestion_service.normalize_title(body.get("title"))
    if title == previous:
        return jsonify(exc)

    updated = ds.update_case_fields(exception_id, {"title": title})
    actor = current_user_email(fallback=body.get("actor", "unknown_user"))
    ds.append_audit_event(exception_id, build_event(
        exception_id, actor=actor, action="case_renamed",
        note=(f'Renamed from "{previous}" to "{title}".' if previous and title
              else f'Named "{title}".' if title
              else f'Title "{previous}" removed; the case now shows its reference.'),
    ).model_dump())
    return jsonify(updated)


@bp.post("/<exception_id>/documents")
@require_auth
def upload_documents(exception_id: str):
    """
    Multipart upload of one or many PDFs. Field name `files` (repeatable).

    An optional parallel `document_types` field assigns a type per file, in
    the same order; anything left blank or sent as "auto" is classified from
    the PDF's own text. Files are validated (extension, PDF magic bytes,
    size) BEFORE anything is stored, and each file's outcome is reported
    independently so one bad PDF never fails the batch.
    """
    ds = get_datastore()
    exc = _visible_case(ds, exception_id)
    if exc is None:
        return jsonify({"error": "not_found"}), 404

    actor = current_user_email(fallback=request.form.get("actor", "unknown_user"))
    # No separate cross-workspace check here any more: _visible_case above
    # already returned None for a case this workspace does not own, and one
    # check that always runs beats two that can disagree.
    workspace_id = current_workspace_id()

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "no_files", "detail": "Attach at least one PDF in the 'files' field."}), 400
    if len(files) > config.MAX_FILES_PER_REQUEST:
        return jsonify({
            "error": "too_many_files_in_one_request",
            "detail": (
                f"Send at most {config.MAX_FILES_PER_REQUEST} files per request. "
                "A case itself has no document limit — upload the rest in another batch."
            ),
        }), 400

    declared_types = request.form.getlist("document_types")

    accepted, rejected = [], []
    for index, storage_file in enumerate(files):
        file_name = storage_file.filename or f"upload-{index + 1}.pdf"
        declared = declared_types[index] if index < len(declared_types) else None
        if declared in ("", "auto", None):
            declared = None

        data = storage_file.read()
        try:
            ingestion_service.validate_upload(file_name, data, declared)
        except ingestion_service.UploadValidationError as exc_err:
            rejected.append({"file_name": file_name, "error": exc_err.code, "detail": exc_err.detail})
            continue
        accepted.append({"file_name": file_name, "data": data, "document_type": declared})

    if not accepted:
        return jsonify({"error": "all_files_rejected", "rejected": rejected}), 400

    result = ingestion_service.run_ingestion(ds, exception_id, accepted, workspace_id, actor)

    documents = [{k: v for k, v in d.items() if k != "data"} for d in result["documents"]]
    ds.append_audit_event(exception_id, build_event(
        exception_id, actor=actor, action="documents_uploaded",
        note=(f"{len(accepted)} accepted, {len(rejected)} rejected; "
              f"analyzed={result['analysis'].get('analyzed')}"),
    ).model_dump())

    updated = _visible_case(ds, exception_id)
    status_code = 207 if rejected else 201
    return jsonify({
        "exception_id": exception_id,
        "documents": documents,
        "rejected": rejected,
        "analysis": result["analysis"],
        "exception": updated,
    }), status_code


@bp.post("/<exception_id>/documents/<document_id>/retry")
@require_auth
def retry_document(exception_id: str, document_id: str):
    """Re-processes one failed document from its already-stored bytes."""
    ds = get_datastore()
    if _visible_case(ds, exception_id) is None:
        return jsonify({"error": "not_found"}), 404

    record = asyncio.run(ingestion_service.retry_document(ds, exception_id, document_id))
    if record is None:
        return jsonify({"error": "not_found"}), 404

    analysis = ingestion_service.run_analysis(ds, exception_id)
    actor = current_user_email(fallback="unknown_user")
    ds.append_audit_event(exception_id, build_event(
        exception_id, actor=actor, action="document_retried",
        note=f"document={document_id}; state={record.get('processing_state')}",
    ).model_dump())
    return jsonify({"document": record, "analysis": analysis})


@bp.post("/<exception_id>/analyze")
@require_auth
def analyze_exception(exception_id: str):
    """Re-runs deterministic matching over whatever documents the case now
    holds. Idempotent, and safe to call after adding evidence at any time."""
    ds = get_datastore()
    if _visible_case(ds, exception_id) is None:
        return jsonify({"error": "not_found"}), 404

    analysis = ingestion_service.run_analysis(ds, exception_id)
    actor = current_user_email(fallback="unknown_user")
    ds.append_audit_event(exception_id, build_event(
        exception_id, actor=actor, action="analysis_run",
        note=f"analyzed={analysis.get('analyzed')}",
    ).model_dump())
    return jsonify({"exception": _visible_case(ds, exception_id), "analysis": analysis})


@bp.get("/<exception_id>/readiness")
@require_auth
def get_readiness(exception_id: str):
    """What the case has, what it is missing, and whether it can be analyzed —
    so the UI can explain the state instead of guessing at it."""
    ds = get_datastore()
    if _visible_case(ds, exception_id) is None:
        return jsonify({"error": "not_found"}), 404
    return jsonify(ingestion_service.readiness(ds.get_documents(exception_id)))


@bp.get("/<exception_id>/documents/<document_id>/content")
@require_auth
def get_document_content(exception_id: str, document_id: str):
    """
    Authenticated document view. Streams the PDF through the backend rather
    than handing out a bucket URL, so access is checked on every read.

    `?mode=signed` instead returns a short-lived signed URL for clients that
    want to hand the file to a native PDF viewer. Never a permanent public
    URL, and never issued without passing this route's auth first.
    """
    ds = get_datastore()
    if _visible_case(ds, exception_id) is None:
        return jsonify({"error": "not_found"}), 404

    record = ds.get_document(document_id)
    if record is None or record.get("exception_id") != exception_id:
        return jsonify({"error": "not_found"}), 404

    workspace_id = current_workspace_id()
    if record.get("workspace_id") and record["workspace_id"] != workspace_id:
        return jsonify({"error": "forbidden"}), 403

    storage_path = record.get("storage_path")
    if not storage_path:
        return jsonify({
            "error": "no_stored_file",
            "detail": "This is a seeded demo document with no uploaded file behind it.",
        }), 404

    if request.args.get("mode") == "signed":
        url = get_storage().signed_url(storage_path, config.SIGNED_URL_TTL_MINUTES)
        if url is None:
            return jsonify({
                "error": "signed_url_unavailable",
                "detail": "Signed URLs are not available on this storage backend. Use this endpoint directly.",
            }), 501
        return jsonify({"url": url, "expires_in_minutes": config.SIGNED_URL_TTL_MINUTES})

    try:
        data = ingestion_service.read_document_bytes(storage_path)
    except StorageError:
        return jsonify({"error": "not_found"}), 404

    return send_file(
        io.BytesIO(data),
        mimetype="application/pdf",
        as_attachment=False,
        download_name=record.get("file_name", f"{document_id}.pdf"),
    )
