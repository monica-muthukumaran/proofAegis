"""
conftest.py — shared test fixtures.

The auth tests exercise the REAL verification code path in
services/auth_service.py (its exception mapping, the Flask decorator's
lenient/strict behaviour, and the actor-spoofing regression). What they
cannot do is reach a live Firebase project — this sandbox has no network
and no service account — so `firebase_admin`'s network call and its app
bootstrap are the only two things stubbed here.

Everything above that line is the production code under test, not a
description of it. Token strings map to outcomes:

    "valid-token"    -> decoded claims for the demo reviewer
    "expired-token"  -> ExpiredIdTokenError
    "revoked-token"  -> RevokedIdTokenError
    anything else    -> InvalidIdTokenError

The backend README documented this stub; it had gone missing, which is why
all six auth tests failed against real firebase_admin.
"""
import os
import sys

import pytest

sys.path.insert(0, ".")

# Set BEFORE config is imported: tests must never reach a live bucket or a
# live Firestore, even on a machine that has real credentials in backend/.env.
os.environ["STORAGE_BACKEND"] = "local"
os.environ["USE_MOCK_DATA"] = "true"
# Pinned for the same reason as the two above: the suite must not change
# behaviour because backend/.env happens to be configured for a live run.
# The auth tests that DO care set config.AUTH_REQUIRED explicitly themselves.
os.environ["AUTH_REQUIRED"] = "false"

from firebase_admin import auth as firebase_auth  # noqa: E402

VALID_CLAIMS = {
    "uid": "test-uid-123",
    "email": "judge@demo.proofaegis.local",
    "email_verified": True,
    "name": "Demo Reviewer",
}


def _fake_verify_id_token(id_token, app=None, check_revoked=False):
    if id_token == "valid-token":
        return dict(VALID_CLAIMS)
    if id_token == "expired-token":
        raise firebase_auth.ExpiredIdTokenError("Token expired", None)
    if id_token == "revoked-token":
        raise firebase_auth.RevokedIdTokenError("Token revoked")
    raise firebase_auth.InvalidIdTokenError(f"Wrong number of segments in token: {id_token!r}")


@pytest.fixture(autouse=True)
def stub_firebase_verification(monkeypatch):
    """Replaces only the network call and the Admin-SDK app bootstrap."""
    monkeypatch.setattr("services.auth_service.firebase_auth.verify_id_token", _fake_verify_id_token)
    monkeypatch.setattr("services.auth_service.get_firebase_app", lambda: object())


@pytest.fixture(autouse=True)
def isolated_datastore():
    """A fresh in-memory datastore per test.

    get_datastore() caches a module-level singleton, which was harmless while
    every check looked only inside one case. It stopped being harmless when
    duplicate detection started querying across cases: two tests that each
    upload the same synthetic invoice would leave the second one correctly
    reporting the first as a duplicate, and the failure looked like a bug in
    the feature rather than shared state between tests.
    """
    import datastore

    datastore._datastore = None
    yield
    datastore._datastore = None
