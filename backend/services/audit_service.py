"""
audit_service.py — FR-012 (audit trail).

Every status transition, system-set or user-set (FR-011), goes through
record_event() so there's exactly one code path that writes audit_events —
no route handler writes directly to the audit collection.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from schemas import AuditEvent


def build_event(exception_id: str, actor: str, action: str,
                 from_status: Optional[str] = None, to_status: Optional[str] = None,
                 note: Optional[str] = None) -> AuditEvent:
    return AuditEvent(
        event_id=f"AUD-{uuid.uuid4().hex[:12]}",
        exception_id=exception_id,
        actor=actor,
        action=action,
        from_status=from_status,
        to_status=to_status,
        note=note,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
