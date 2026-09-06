"""
email_intake.py — invoices arrive in an inbox, not through a file picker.

Every case in this system currently begins with a person finding a PDF on
disk and dragging it into a browser. That is not how vendor invoices arrive:
they arrive as email attachments, all day, from addresses the AP team already
knows.

This module polls a mailbox over IMAP, turns each unread message's PDF
attachments into a case, and marks the message seen. It is deliberately a
poller rather than a webhook — an IMAP mailbox needs no public endpoint, no
inbound routing and no third-party relay, which makes it the smallest thing
that removes the manual step.

DISABLED BY DEFAULT. It does nothing until EMAIL_INTAKE_ENABLED is set and a
host, user and password are configured. Two safety rules are enforced here
rather than left to configuration:

  * Only senders on the allow-list are processed. An open inbox is an open
    door: anything that can email you could otherwise create cases and put
    documents in front of an approver.
  * Attachments are validated exactly as an upload is — extension, PDF magic
    bytes, size — before a single byte is stored.

Nothing is ever deleted from the mailbox. Messages are marked \\Seen so the
same invoice is not ingested twice; the original stays where it is, which is
the record a dispute is settled from.
"""
from __future__ import annotations

import email
import imaplib
import logging
from email.header import decode_header, make_header
from email.utils import parseaddr
from typing import Callable, Optional

from config import config
from services.ingestion_service import UploadValidationError, validate_upload

logger = logging.getLogger("proofaegis.email_intake")


def _decode(value) -> str:
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:  # noqa: BLE001 — a malformed header must not stop intake
        return str(value)


def sender_allowed(from_header: str, allow_list) -> bool:
    """
    Whether this sender may create cases.

    An entry is either a full address ("billing@sigmaengsol.com") or a domain
    ("@sigmaengsol.com"). Matching is on the parsed address only — never on
    the display name, which any sender can set to anything.
    """
    _, address = parseaddr(from_header or "")
    address = address.strip().lower()
    if not address:
        return False
    for entry in allow_list or []:
        rule = str(entry).strip().lower()
        if not rule:
            continue
        if rule.startswith("@"):
            if address.endswith(rule):
                return True
        elif address == rule:
            return True
    return False


def extract_pdf_attachments(message) -> list[dict]:
    """[{file_name, data}] for every PDF part, validated before being returned."""
    attachments = []
    for part in message.walk():
        if part.get_content_maintype() == "multipart":
            continue
        if part.get("Content-Disposition") is None:
            continue
        file_name = _decode(part.get_filename())
        if not file_name.lower().endswith(".pdf"):
            continue
        try:
            data = part.get_payload(decode=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning("attachment_decode_failed name=%s error=%s", file_name, exc)
            continue
        if not data:
            continue
        try:
            validate_upload(file_name, data, None)
        except UploadValidationError as exc:
            logger.info("attachment_rejected name=%s reason=%s", file_name, exc.code)
            continue
        attachments.append({"file_name": file_name, "data": data})
    return attachments


def fetch_unread(client, allow_list, limit: int) -> list[dict]:
    """Unread messages from allowed senders that carry at least one PDF.

    Returns [{message_id, subject, sender, attachments, uid}]. Marking as read
    is the caller's job, and deliberately happens only AFTER a case is created
    — a crash between the two must re-deliver the invoice, not lose it.
    """
    status, data = client.search(None, "UNSEEN")
    if status != "OK":
        return []

    messages = []
    for uid in (data[0] or b"").split()[: max(0, limit)]:
        status, payload = client.fetch(uid, "(BODY.PEEK[])")
        if status != "OK" or not payload or not payload[0]:
            continue
        message = email.message_from_bytes(payload[0][1])
        sender = _decode(message.get("From"))
        if not sender_allowed(sender, allow_list):
            logger.info("sender_not_allowed from=%s", sender)
            continue
        attachments = extract_pdf_attachments(message)
        if not attachments:
            continue
        messages.append({
            "uid": uid,
            "message_id": message.get("Message-ID"),
            "subject": _decode(message.get("Subject")),
            "sender": sender,
            "attachments": attachments,
        })
    return messages


def poll_once(create_case: Callable[[dict], Optional[str]]) -> dict:
    """
    One pass over the mailbox.

    `create_case` receives a message record and returns the exception_id it
    created, or None to leave the message unread for a later attempt. Keeping
    case creation in the caller means this module never imports the datastore
    and can be tested against a fake IMAP client.
    """
    if not config.EMAIL_INTAKE_ENABLED:
        return {"enabled": False, "processed": 0, "cases": []}
    if not (config.EMAIL_INTAKE_HOST and config.EMAIL_INTAKE_USER
            and config.EMAIL_INTAKE_PASSWORD):
        logger.warning("email_intake_not_configured")
        return {"enabled": False, "processed": 0, "cases": [],
                "error": "EMAIL_INTAKE_HOST, _USER and _PASSWORD must all be set."}

    created, seen = [], 0
    client = imaplib.IMAP4_SSL(config.EMAIL_INTAKE_HOST, config.EMAIL_INTAKE_PORT)
    try:
        client.login(config.EMAIL_INTAKE_USER, config.EMAIL_INTAKE_PASSWORD)
        client.select(config.EMAIL_INTAKE_FOLDER)
        for message in fetch_unread(client, config.EMAIL_INTAKE_ALLOWED_SENDERS,
                                    config.EMAIL_INTAKE_BATCH_SIZE):
            seen += 1
            exception_id = create_case(message)
            if not exception_id:
                continue
            # Only now: an unmarked message is re-delivered, a lost one is not.
            client.store(message["uid"], "+FLAGS", "\\Seen")
            created.append({"exception_id": exception_id,
                            "subject": message["subject"],
                            "sender": message["sender"],
                            "attachment_count": len(message["attachments"])})
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass

    logger.info("email_intake_pass messages=%s cases=%s", seen, len(created))
    return {"enabled": True, "processed": seen, "cases": created}
