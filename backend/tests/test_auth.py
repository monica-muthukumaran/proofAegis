"""
Validates services/auth_service.py (pure token verification) and auth.py's
Flask decorator (require_auth / require_auth_strict), including the
regression that matters most: once a real token is present, a client can no
longer spoof the audit-trail 'actor' via the request body.
"""
import sys

import pytest

sys.path.insert(0, ".")

from config import config
from services.auth_service import (
    AuthError, ExpiredTokenError, InvalidTokenError, MissingTokenError,
    RevokedTokenError, verify_id_token,
)


# ---------------------------------------------------------------------------
# services/auth_service.py — pure verification logic
# ---------------------------------------------------------------------------
def test_valid_token_returns_claims():
    claims = verify_id_token("valid-token")
    assert claims["uid"] == "test-uid-123"
    assert claims["email"] == "judge@demo.proofaegis.local"
    assert claims["email_verified"] is True


def test_missing_token_raises_missing_token_error():
    with pytest.raises(MissingTokenError):
        verify_id_token("")


def test_expired_token_raises_expired_token_error():
    with pytest.raises(ExpiredTokenError):
        verify_id_token("expired-token")


def test_revoked_token_raises_revoked_token_error():
    with pytest.raises(RevokedTokenError):
        verify_id_token("revoked-token")


def test_garbage_token_raises_invalid_token_error():
    with pytest.raises(InvalidTokenError):
        verify_id_token("not-a-real-token")


def test_all_auth_errors_share_a_common_base():
    for exc_cls in (MissingTokenError, ExpiredTokenError, RevokedTokenError, InvalidTokenError):
        assert issubclass(exc_cls, AuthError)


# ---------------------------------------------------------------------------
# auth.py's Flask decorator, exercised through the real app
# ---------------------------------------------------------------------------
@pytest.fixture
def app_client():
    from app import create_app
    app = create_app()
    return app.test_client()


@pytest.fixture(autouse=True)
def reset_auth_required():
    original = config.AUTH_REQUIRED
    yield
    config.AUTH_REQUIRED = original


class TestLenientMode:
    """config.AUTH_REQUIRED = False (the default) — must never break the
    existing demo/mock-mode flow."""

    def test_no_token_still_allowed(self, app_client):
        config.AUTH_REQUIRED = False
        r = app_client.get("/api/exceptions")
        assert r.status_code == 200

    def test_bad_token_still_allowed_but_ignored(self, app_client):
        config.AUTH_REQUIRED = False
        r = app_client.get("/api/exceptions", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 200

    def test_status_update_falls_back_to_body_actor_with_no_token(self, app_client):
        config.AUTH_REQUIRED = False
        r = app_client.patch(
            "/api/exceptions/EXC-2026-0001/status",
            json={"status": "awaiting_vendor", "actor": "demo-user@example.com"},
        )
        assert r.status_code == 200
        audit = app_client.get("/api/exceptions/EXC-2026-0001/audit").get_json()
        last_event = [e for e in audit if e["action"] == "status_changed"][-1]
        assert last_event["actor"] == "demo-user@example.com"


class TestStrictMode:
    """config.AUTH_REQUIRED = True — a missing/invalid token must 401."""

    def test_no_token_rejected(self, app_client):
        config.AUTH_REQUIRED = True
        r = app_client.get("/api/exceptions")
        assert r.status_code == 401
        assert r.get_json()["error"] == "unauthorized"

    def test_bad_token_rejected(self, app_client):
        config.AUTH_REQUIRED = True
        r = app_client.get("/api/exceptions", headers={"Authorization": "Bearer garbage"})
        assert r.status_code == 401

    def test_valid_token_allowed(self, app_client):
        config.AUTH_REQUIRED = True
        r = app_client.get("/api/exceptions", headers={"Authorization": "Bearer valid-token"})
        assert r.status_code == 200


class TestActorTrustRegression:
    """The core regression: a verified token's email must win over
    whatever 'actor' the client puts in the request body — otherwise
    anyone could forge audit-trail entries as someone else."""

    def test_verified_identity_overrides_spoofed_body_actor(self, app_client):
        config.AUTH_REQUIRED = False  # even in lenient mode, a REAL token still wins
        r = app_client.patch(
            "/api/exceptions/EXC-2026-0002/status",
            json={"status": "awaiting_vendor", "actor": "attacker@spoofed.example"},
            headers={"Authorization": "Bearer valid-token"},
        )
        assert r.status_code == 200
        audit = app_client.get("/api/exceptions/EXC-2026-0002/audit").get_json()
        last_event = [e for e in audit if e["action"] == "status_changed"][-1]
        assert last_event["actor"] == "judge@demo.proofaegis.local"
        assert last_event["actor"] != "attacker@spoofed.example"


# ---------------------------------------------------------------------------
# /api/auth/me — always strict, regardless of config.AUTH_REQUIRED
# ---------------------------------------------------------------------------
class TestAuthMeEndpoint:
    def test_me_without_token_is_401_even_in_lenient_mode(self, app_client):
        config.AUTH_REQUIRED = False
        r = app_client.get("/api/auth/me")
        assert r.status_code == 401

    def test_me_with_valid_token_returns_profile(self, app_client):
        config.AUTH_REQUIRED = False
        r = app_client.get("/api/auth/me", headers={"Authorization": "Bearer valid-token"})
        assert r.status_code == 200
        body = r.get_json()
        assert body["uid"] == "test-uid-123"
        assert body["email"] == "judge@demo.proofaegis.local"

    def test_me_with_expired_token_is_401(self, app_client):
        r = app_client.get("/api/auth/me", headers={"Authorization": "Bearer expired-token"})
        assert r.status_code == 401
