"""
auth.py — Flask-layer glue around services/auth_service.py.

`require_auth` is the one decorator every route in routes/exceptions.py
uses. Its behavior is deliberately two-speed, controlled by
config.AUTH_REQUIRED:

  - AUTH_REQUIRED=False (the default — matches the existing demo/mock-mode
    posture): a missing or invalid token never blocks the request. If a
    valid token IS sent, it's still verified and g.user is populated, so
    routes can prefer the verified identity over a client-supplied "actor"
    field the moment the frontend starts sending one — without anything
    breaking for people still using the demo-auth flow.
  - AUTH_REQUIRED=True: a missing or invalid token gets a 401 immediately.
    Flip this on once real sign-in is wired up end-to-end.

g.user is either None (no/ignored token) or the decoded Firebase claims
dict (uid, email, email_verified, ...).
"""
from __future__ import annotations

import logging
from functools import wraps

from flask import g, jsonify, request

from config import config
from services.auth_service import AuthError, verify_id_token

logger = logging.getLogger("proofaegis.auth")


def _extract_bearer_token() -> str | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    token = header[len("Bearer "):].strip()
    return token or None


def _unauthorized(detail: str):
    return jsonify({"error": "unauthorized", "detail": detail}), 401


def require_auth(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token()
        g.user = None

        if token is None:
            if config.AUTH_REQUIRED:
                return _unauthorized("Missing Authorization header (expected 'Bearer <Firebase ID token>').")
            return view(*args, **kwargs)

        try:
            g.user = verify_id_token(token)
        except AuthError as exc:
            logger.warning("auth_token_rejected reason=%s", exc)
            if config.AUTH_REQUIRED:
                return _unauthorized(str(exc))
            # Lenient mode: bad token is treated the same as no token —
            # request proceeds, but g.user stays None so callers can't
            # accidentally trust a rejected identity.

        return view(*args, **kwargs)

    return wrapper


def require_auth_strict(view):
    """Like require_auth, but ALWAYS enforces a valid token regardless of
    config.AUTH_REQUIRED — for endpoints where "who am I" has no meaningful
    answer without one, like /api/auth/me."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        token = _extract_bearer_token()
        if token is None:
            return _unauthorized("Missing Authorization header (expected 'Bearer <Firebase ID token>').")
        try:
            g.user = verify_id_token(token)
        except AuthError as exc:
            logger.warning("auth_token_rejected reason=%s", exc)
            return _unauthorized(str(exc))
        return view(*args, **kwargs)

    return wrapper


def current_workspace_id() -> str:
    """The workspace every Firestore query and Storage path is scoped to.

    Single-workspace enforcement for now, and deliberately honest about it:
    a verified token carrying a `workspace_id` custom claim wins, otherwise
    everyone lands in config.DEFAULT_WORKSPACE_ID. That is not multi-tenant
    isolation — any signed-in user still sees the same workspace's cases.
    What it does buy is that storage paths and case records are scoped from
    the first byte written, so turning on real per-tenant claims later is a
    claims-and-rules change rather than a data migration.
    """
    user = getattr(g, "user", None)
    if user:
        claim = user.get("workspace_id") or user.get("workspaceId")
        if claim:
            return str(claim)
    return config.DEFAULT_WORKSPACE_ID


def current_user_role() -> str | None:
    """The approval role from the VERIFIED token's custom claims.

    Deliberately not read from the request body: a role that the client can
    state is not an authorisation, it is a suggestion. Absent when the user is
    not signed in or carries no role claim, and the approval policy decides
    what that means.
    """
    user = getattr(g, "user", None)
    if not user:
        return None
    role = user.get("role") or user.get("approval_role")
    return str(role) if role else None


def current_user_email(fallback: str | None = None) -> str | None:
    """Convenience for routes that record an 'actor' — prefers the verified
    token's email over anything the client claims in the request body."""
    user = getattr(g, "user", None)
    if user and user.get("email"):
        return user["email"]
    return fallback
