"""
routes/intake.py — the mailbox as a source of cases.

One endpoint, deliberately: POST /api/intake/email/poll runs a single pass
over the configured inbox and returns what it created. Polling is triggered
rather than continuous so that scheduling stays outside the request path,
where it belongs — Cloud Scheduler hitting this endpoint, a cron job, or a
person pressing a button all work without this process owning a timer.

GET /api/intake/email tells the UI whether intake is configured at all, so
the screen can say "not configured" instead of failing a poll.
"""
from __future__ import annotations

import logging

from flask import Blueprint, jsonify

from auth import current_user_email, current_workspace_id, require_auth
from config import config
from datastore import get_datastore
from services import email_intake, ingestion_service
from services.audit_service import build_event

logger = logging.getLogger("proofaegis.intake")

bp = Blueprint("intake", __name__, url_prefix="/api/intake")


@bp.get("/email")
@require_auth
def email_status():
    configured = bool(config.EMAIL_INTAKE_HOST and config.EMAIL_INTAKE_USER
                      and config.EMAIL_INTAKE_PASSWORD)
    return jsonify({
        "enabled": config.EMAIL_INTAKE_ENABLED,
        "configured": configured,
        "mailbox": config.EMAIL_INTAKE_USER or None,
        "folder": config.EMAIL_INTAKE_FOLDER,
        "allowed_senders": list(config.EMAIL_INTAKE_ALLOWED_SENDERS),
        # An empty allow-list is a configuration error rather than a permissive
        # default, and the UI should say so plainly.
        "blocking_reason": (
            None if config.EMAIL_INTAKE_ENABLED and configured
            and config.EMAIL_INTAKE_ALLOWED_SENDERS
            else "Email intake needs EMAIL_INTAKE_ENABLED, a host/user/password, and at "
                 "least one allowed sender. Nothing is ingested until all four are set."
        ),
    })


@bp.post("/email/poll")
@require_auth
def poll_email():
    """Ingests every unread message from an allowed sender that carries PDFs."""
    if not (config.EMAIL_INTAKE_ENABLED and config.EMAIL_INTAKE_ALLOWED_SENDERS):
        return jsonify({
            "error": "email_intake_not_configured",
            "detail": "Set EMAIL_INTAKE_ENABLED and EMAIL_INTAKE_ALLOWED_SENDERS first.",
        }), 400

    ds = get_datastore()
    workspace_id = current_workspace_id()
    actor = current_user_email(fallback="email-intake")

    def create_case(message: dict):
        """One message -> one case holding its attachments."""
        case = ingestion_service.create_case(ds, workspace_id, actor, {
            "source": "email",
            "source_subject": message.get("subject"),
            "source_sender": message.get("sender"),
            "source_message_id": message.get("message_id"),
        })
        exception_id = case["exception_id"]
        uploads = [{"file_name": a["file_name"], "data": a["data"], "document_type": None}
                   for a in message["attachments"]]
        try:
            ingestion_service.run_ingestion(ds, exception_id, uploads, workspace_id, actor)
        except Exception as exc:  # noqa: BLE001 — one bad message must not stop the pass
            logger.error("email_case_failed exception_id=%s error=%s", exception_id, exc)
            return None

        ds.append_audit_event(exception_id, build_event(
            exception_id, actor=actor, action="case_created_from_email",
            note=f"From {message.get('sender')} — {message.get('subject')}",
        ).model_dump())
        return exception_id

    try:
        result = email_intake.poll_once(create_case)
    except Exception as exc:  # noqa: BLE001 — a mailbox outage is a 502, not a 500
        logger.error("email_poll_failed error=%s", exc)
        return jsonify({"error": "mailbox_unreachable", "detail": str(exc)}), 502

    return jsonify(result)
