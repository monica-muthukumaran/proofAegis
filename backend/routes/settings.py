"""
routes/settings.py — the Settings screen's entire backend surface: a
read-only display of settings/tolerance_rules (FR-006, Document 1 §8).
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from auth import require_auth
from datastore import get_datastore
from config import config
from services import analytics_gateway

bp = Blueprint("settings", __name__, url_prefix="/api/settings")


@bp.get("/tolerance")
@require_auth
def get_tolerance():
    ds = get_datastore()
    return jsonify(ds.get_tolerance_rules())


@bp.get("/mode")
@require_auth
def get_mode():
    """The single source of truth for the frontend's mode banner (FR-013).

    The frontend must never infer its mode from a failed request — a 401 is
    not evidence of mock mode. It asks here instead, and this answers with
    what is actually configured on the server."""
    from services.storage_service import get_storage

    storage_kind = get_storage().kind
    return jsonify({
        "mock_mode": config.USE_MOCK_DATA,
        "auth_required": config.AUTH_REQUIRED,
        "datastore": "in_memory_seed" if config.USE_MOCK_DATA else "firestore",
        "storage_backend": storage_kind,
        # Only report a bucket when one is actually in use. Echoing a
        # configured-but-unused bucket name while writing to local disk is the
        # kind of half-truth this endpoint exists to prevent.
        "storage_bucket": config.STORAGE_BUCKET if storage_kind == "gcs" else None,
        "gemini_configured": bool(config.GEMINI_API_KEY),
        # Which engine served the analytics figures — see
        # services/analytics_gateway.py. Surfaced so the UI can name it
        # rather than leaving a viewer to assume which one ran.
        **analytics_gateway.engine_status(),
        # Configured is not the same as used: in mock mode the key is present
        # but no model is ever called, and the UI must say so.
        "gemini_active": bool(config.GEMINI_API_KEY) and not config.USE_MOCK_DATA,
        "synthetic_data": True,
        "workspace_id": config.DEFAULT_WORKSPACE_ID,
    })
