"""
routes/auth.py — GET /api/auth/me. Always requires a valid token (unlike the
rest of the API, which is lenient until config.AUTH_REQUIRED is flipped on) —
"who am I" has no meaningful answer without one.
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify

from auth import current_workspace_id, is_demo_workspace, require_auth_strict

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.get("/me")
@require_auth_strict
def me():
    user = g.user
    workspace_id = current_workspace_id()
    return jsonify({
        "uid": user.get("uid"),
        "email": user.get("email"),
        "email_verified": user.get("email_verified", False),
        "name": user.get("name"),
        # Which workspace this identity resolves to, and whether it is the
        # shared seeded one. The frontend uses the second field to tell an
        # empty NEW workspace ("upload your first invoice") apart from an
        # empty demo workspace, which would mean something has gone wrong.
        "workspace_id": workspace_id,
        "demo_workspace": is_demo_workspace(workspace_id),
    })
