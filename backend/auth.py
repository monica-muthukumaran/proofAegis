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


def workspace_for_claims(claims: dict | None) -> str:
    """Which workspace a set of verified token claims belongs to.

    Pure and separately testable, because getting this wrong is how one
    person's invoices end up in another person's queue. The order is
    deliberate:

      1. An explicit `workspace_id` custom claim always wins. That is how a
         real team shares one workspace, and how an admin puts somebody
         somewhere specific.
      2. No verified user at all -> the demo workspace. This is the
         demo-auth/mock path, unchanged: no token has ever been sent, and the
         seeded cases are exactly what should be on screen.
      3. A designated demo account -> the demo workspace, even though it IS a
         real signed-in Firebase user. Without this, the one-click demo login
         the frontend ships would open on an empty queue, which is the one
         place a reviewer must not meet one.
      4. Anyone else -> `user:<uid>`, their own workspace, which starts empty.

    Keyed on uid rather than email because an email address can be changed on
    an account and a uid cannot; a workspace that moves when somebody edits
    their profile is a workspace that loses its cases.
    """
    if claims:
        claim = claims.get("workspace_id") or claims.get("workspaceId")
        if claim:
            return str(claim)

    if not claims or not config.PER_USER_WORKSPACES:
        return config.DEFAULT_WORKSPACE_ID

    email = str(claims.get("email") or "").strip().lower()
    if email and email in config.DEMO_ACCOUNT_EMAILS:
        return config.DEFAULT_WORKSPACE_ID

    uid = claims.get("uid") or claims.get("user_id") or claims.get("sub")
    if not uid:
        # A verified token with no subject is not something to guess about,
        # and dropping such a request into the shared demo workspace would be
        # the worst available guess.
        return config.DEFAULT_WORKSPACE_ID
    return f"{config.USER_WORKSPACE_PREFIX}:{uid}"


def current_workspace_id() -> str:
    """The workspace every query, Storage path and case record is scoped to.

    See workspace_for_claims for the rules. Storage paths were already
    workspace-scoped from the first byte written, so turning this on files new
    uploads correctly without a data migration.
    """
    return workspace_for_claims(getattr(g, "user", None))


def is_demo_workspace(workspace_id: str) -> bool:
    """Whether this workspace is the shared seeded one. Callers use it to
    decide what to SAY on an empty screen, never to decide what to show."""
    return workspace_id == config.DEFAULT_WORKSPACE_ID


def current_user_uid() -> str | None:
    user = getattr(g, "user", None)
    if not user:
        return None
    uid = user.get("uid") or user.get("user_id") or user.get("sub")
    return str(uid) if uid else None


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
