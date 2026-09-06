"""
routes/auth.py — GET /api/auth/me. Always requires a valid token (unlike the
rest of the API, which is lenient until config.AUTH_REQUIRED is flipped on) —
"who am I" has no meaningful answer without one.
"""
from __future__ import annotations

from flask import Blueprint, g, jsonify

from auth import require_auth_strict

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


@bp.get("/me")
@require_auth_strict
def me():
    user = g.user
    return jsonify({
        "uid": user.get("uid"),
        "email": user.get("email"),
        "email_verified": user.get("email_verified", False),
        "name": user.get("name"),
    })
