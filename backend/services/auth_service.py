"""
services/auth_service.py — verifies a Firebase Auth ID token and returns its
decoded claims. This is pure verification logic with no Flask dependency,
so it's testable on its own (see tests/test_auth.py) and reusable if
ProofAegis ever grows a non-HTTP entry point (a CLI, a queue worker).

We wrap firebase_admin.auth's exception zoo in our own small hierarchy so
callers (auth.py's Flask decorator) only need to catch one thing, and so a
future switch away from Firebase Auth wouldn't leak firebase_admin types
into the route layer.
"""
from __future__ import annotations

from firebase_admin import auth as firebase_auth

from firebase_app import get_firebase_app


class AuthError(Exception):
    """Base class for every token-verification failure."""


class MissingTokenError(AuthError):
    pass


class ExpiredTokenError(AuthError):
    pass


class RevokedTokenError(AuthError):
    pass


class InvalidTokenError(AuthError):
    pass


def verify_id_token(id_token: str) -> dict:
    """
    Verifies a Firebase Auth ID token (the frontend sends this in an
    `Authorization: Bearer <token>` header after firebase.auth().signInWith...()).

    Returns the decoded token dict on success — notably `uid`, `email`,
    `email_verified`. Raises a subclass of AuthError on any failure.

    check_revoked=True adds a Firestore-backed revocation check (catches a
    token from a session the user explicitly signed out of, or one an admin
    force-revoked) at the cost of one extra network call per verification —
    worth it for a finance tool where "this session was supposed to be dead"
    matters more than shaving a few milliseconds off every request.
    """
    if not id_token or not id_token.strip():
        raise MissingTokenError("No ID token provided")

    app = get_firebase_app()
    try:
        return firebase_auth.verify_id_token(id_token, app=app, check_revoked=True)
    except firebase_auth.ExpiredIdTokenError as exc:
        raise ExpiredTokenError(str(exc)) from exc
    except firebase_auth.RevokedIdTokenError as exc:
        raise RevokedTokenError(str(exc)) from exc
    except firebase_auth.InvalidIdTokenError as exc:
        raise InvalidTokenError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — any other verification failure still maps to "invalid"
        raise InvalidTokenError(str(exc)) from exc
