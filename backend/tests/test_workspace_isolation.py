"""
test_workspace_isolation.py — a fresh login opens on an empty page, and what
that user does after stays theirs.

The seeded corpus used to be everybody's case list. That was correct while
there was one workspace and one demo, and it is wrong the moment a real
person signs up: they would open the queue to three hundred synthetic
invoices belonging to nobody, and their first genuine upload would land in
the same shared pile.

So the seeded data now does two separate jobs, and the split is what these
tests defend:

  * DEMO WORKSPACE — the seeded cases are the demo login's case list, exactly
    as before. Nothing about the demo may regress; several tests here exist
    only to say so.
  * MODEL CONTEXT — the same corpus still calibrates the reasoning agent's
    severity scale for EVERY workspace, including an empty one, through
    services/seed_context.py. That path is deliberately not scoped, so it is
    tested for what it does NOT carry across the boundary.

The sharpest assertion in the file is
`test_a_real_invoice_is_not_reported_as_a_duplicate_of_a_seeded_one`. Getting
tenancy wrong on a queue is embarrassing; getting it wrong on the duplicate
check accuses a real user of re-billing an invoice they have never seen, in
the highest-ranked finding this product produces.
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")

from auth import workspace_for_claims  # noqa: E402
from config import config  # noqa: E402
from datastore import get_datastore  # noqa: E402
from services import ingestion_service  # noqa: E402
from tests.conftest import ALICE_CLAIMS, BOB_CLAIMS, VALID_CLAIMS  # noqa: E402

DEMO = config.DEFAULT_WORKSPACE_ID

ALICE = {"Authorization": "Bearer alice-token"}
BOB = {"Authorization": "Bearer bob-token"}
DEMO_REVIEWER = {"Authorization": "Bearer valid-token"}


@pytest.fixture
def client():
    from app import create_app

    return create_app().test_client()


# ---------------------------------------------------------------------------
# The rule itself, tested as a pure function
# ---------------------------------------------------------------------------
class TestWorkspaceResolution:
    def test_no_verified_user_lands_in_the_demo_workspace(self):
        """The demo-auth and mock-mode path, unchanged. No token has ever
        been sent, and the seeded cases are exactly what should be on screen."""
        assert workspace_for_claims(None) == DEMO
        assert workspace_for_claims({}) == DEMO

    def test_an_ordinary_signed_in_user_gets_their_own_workspace(self):
        assert workspace_for_claims(ALICE_CLAIMS) == "user:uid-alice"
        assert workspace_for_claims(BOB_CLAIMS) == "user:uid-bob"

    def test_two_users_never_share_a_workspace(self):
        assert workspace_for_claims(ALICE_CLAIMS) != workspace_for_claims(BOB_CLAIMS)

    def test_the_designated_demo_account_still_sees_the_demo_workspace(self):
        """A real Firebase sign-in, and still the seeded workspace. Without
        this the one-click demo login the frontend ships would open on an
        empty queue — the one place a reviewer must not meet one."""
        assert VALID_CLAIMS["email"] in config.DEMO_ACCOUNT_EMAILS
        assert workspace_for_claims(VALID_CLAIMS) == DEMO

    def test_the_demo_account_match_is_case_insensitive(self):
        claims = {**ALICE_CLAIMS, "email": "JUDGE@Demo.ProofAegis.Local"}
        assert workspace_for_claims(claims) == DEMO

    def test_an_explicit_workspace_claim_beats_everything(self):
        """How a real team shares one workspace, and how an admin puts
        somebody somewhere specific."""
        assert workspace_for_claims({**ALICE_CLAIMS, "workspace_id": "acme"}) == "acme"
        assert workspace_for_claims({**VALID_CLAIMS, "workspace_id": "acme"}) == "acme"

    def test_the_workspace_is_keyed_on_uid_not_email(self):
        """An email address can be changed on an account and a uid cannot. A
        workspace that moved when somebody edited their profile would be a
        workspace that lost every case in it."""
        renamed = {**ALICE_CLAIMS, "email": "alice.smith@acme.example"}
        assert workspace_for_claims(renamed) == workspace_for_claims(ALICE_CLAIMS)

    def test_a_verified_token_with_no_subject_does_not_guess(self):
        """Dropping an unidentifiable token into a private workspace would be
        the worst available guess; the shared demo is the safe one."""
        assert workspace_for_claims({"email": "nobody@acme.example"}) == DEMO

    def test_the_feature_can_be_turned_off(self, monkeypatch):
        monkeypatch.setattr(config, "PER_USER_WORKSPACES", False)
        assert workspace_for_claims(ALICE_CLAIMS) == DEMO


# ---------------------------------------------------------------------------
# A fresh login opens on nothing
# ---------------------------------------------------------------------------
class TestFreshLoginIsEmpty:
    def test_a_new_users_queue_is_empty(self, client):
        assert client.get("/api/exceptions", headers=ALICE).get_json() == []

    def test_the_seeded_cases_are_still_there_for_the_demo_workspace(self, client):
        """The counterweight to the test above: proving the queue is empty is
        worthless if it is empty for everybody."""
        seeded = client.get("/api/exceptions", headers=DEMO_REVIEWER).get_json()
        assert len(seeded) >= 3
        assert {"EXC-2026-0001", "EXC-2026-0002", "EXC-2026-0003"} <= {
            case["exception_id"] for case in seeded}

    def test_an_unauthenticated_request_still_sees_the_demo_workspace(self, client):
        """Mock mode and demo-auth send no token at all. That flow must not
        change at all."""
        assert len(client.get("/api/exceptions").get_json()) >= 3

    def test_a_new_users_dashboard_reads_zero_rather_than_the_demo_numbers(self, client):
        summary = client.get("/api/dashboard/summary", headers=ALICE).get_json()
        assert summary["invoice_count"] == 0
        assert summary["open_exceptions_count"] == 0
        assert summary["value_on_hold"] == 0
        assert summary["exception_type_breakdown"] == {}

    def test_a_new_users_analytics_describe_an_empty_population(self, client):
        overview = client.get("/api/analytics/overview", headers=ALICE).get_json()
        assert overview["summary"]["invoice_count"] == 0
        assert overview["vendor_risk"]["vendors"] == []

    def test_the_demo_dashboard_still_has_numbers_on_it(self, client):
        summary = client.get("/api/dashboard/summary", headers=DEMO_REVIEWER).get_json()
        assert summary["invoice_count"] > 0

    def test_me_reports_which_workspace_the_login_resolved_to(self, client):
        """So the frontend can tell an empty NEW workspace ("upload your first
        invoice") from an empty demo one, which would mean something broke."""
        alice = client.get("/api/auth/me", headers=ALICE).get_json()
        assert alice["workspace_id"] == "user:uid-alice"
        assert alice["demo_workspace"] is False

        reviewer = client.get("/api/auth/me", headers=DEMO_REVIEWER).get_json()
        assert reviewer["demo_workspace"] is True

    def test_mode_stops_claiming_synthetic_data_in_a_real_users_workspace(self, client):
        """The banner says "synthetic data" because the seeded cases are. In
        Alice's workspace every case is one she uploaded, and the banner must
        stop saying it."""
        assert client.get("/api/settings/mode", headers=DEMO_REVIEWER).get_json()["synthetic_data"] is True
        assert client.get("/api/settings/mode", headers=ALICE).get_json()["synthetic_data"] is False


# ---------------------------------------------------------------------------
# What a user creates stays theirs
# ---------------------------------------------------------------------------
class TestCasesAreTrackedWithTheLogin:
    def test_a_created_case_is_stamped_with_the_creators_workspace_and_login(self, client):
        created = client.post("/api/exceptions", headers=ALICE,
                              json={"vendor_name": "Acme Parts"}).get_json()
        assert created["workspace_id"] == "user:uid-alice"
        # The verified email, not anything the client said about itself.
        assert created["created_by"] == "alice@acme.example"

    def test_the_body_cannot_spoof_the_creator_when_a_token_is_present(self, client):
        created = client.post("/api/exceptions", headers=ALICE,
                              json={"actor": "ceo@acme.example"}).get_json()
        assert created["created_by"] == "alice@acme.example"

    def test_a_created_case_appears_in_its_owners_queue(self, client):
        created = client.post("/api/exceptions", headers=ALICE, json={}).get_json()
        mine = client.get("/api/exceptions", headers=ALICE).get_json()
        assert [case["exception_id"] for case in mine] == [created["exception_id"]]

    def test_it_appears_in_nobody_elses(self, client):
        client.post("/api/exceptions", headers=ALICE, json={})
        assert client.get("/api/exceptions", headers=BOB).get_json() == []
        demo_ids = {c["exception_id"] for c in
                    client.get("/api/exceptions", headers=DEMO_REVIEWER).get_json()}
        assert all(not i.startswith("EXC-2026-") or i in demo_ids for i in demo_ids)
        assert len(demo_ids) >= 3

    def test_the_audit_trail_records_the_verified_login(self, client):
        created = client.post("/api/exceptions", headers=ALICE, json={}).get_json()
        audit = client.get(f"/api/exceptions/{created['exception_id']}/audit",
                           headers=ALICE).get_json()
        assert audit[0]["action"] == "case_created"
        assert audit[0]["actor"] == "alice@acme.example"


# ---------------------------------------------------------------------------
# Reading somebody else's case
# ---------------------------------------------------------------------------
class TestCrossWorkspaceReadsAreRefused:
    @pytest.fixture
    def alices_case(self, client):
        return client.post("/api/exceptions", headers=ALICE,
                           json={"vendor_name": "Acme Parts"}).get_json()["exception_id"]

    def test_another_user_cannot_read_it(self, client, alices_case):
        assert client.get(f"/api/exceptions/{alices_case}", headers=BOB).status_code == 404

    def test_the_refusal_is_404_and_not_403(self, client, alices_case):
        """Deliberately indistinguishable from an id that was never issued. A
        403 would confirm the case is real to anyone willing to guess at an
        id, which is a slower leak but a leak."""
        real = client.get(f"/api/exceptions/{alices_case}", headers=BOB)
        invented = client.get("/api/exceptions/EXC-2026-DOESNOTEXIST", headers=BOB)
        assert real.status_code == invented.status_code == 404
        assert real.get_json() == invented.get_json()

    @pytest.mark.parametrize("suffix", [
        "", "/documents", "/match", "/graph", "/audit", "/readiness",
        "/reasoning", "/hypotheses", "/resolution", "/trust", "/progress",
    ])
    def test_every_read_route_refuses(self, client, alices_case, suffix):
        """Parameterised over the whole surface rather than spot-checked. The
        routes that reach straight into case_service had no ownership check at
        all before this change, and those are precisely the ones a spot check
        would have missed.

        The body is asserted, not just the status. Several of these routes
        answer 404 to their own owner too — `not_generated` for an unrun
        agent, `not_checked` for an unchecked case — so a status-only
        assertion would pass on four of them without the ownership check ever
        running.
        """
        response = client.get(f"/api/exceptions/{alices_case}{suffix}", headers=BOB)
        assert response.status_code == 404
        assert response.get_json() == {"error": "not_found"}

    def test_a_status_change_from_another_workspace_is_refused(self, client, alices_case):
        response = client.patch(f"/api/exceptions/{alices_case}/status", headers=BOB,
                                json={"status": "awaiting_vendor"})
        assert response.status_code == 404

    def test_and_the_case_is_untouched_by_the_attempt(self, client, alices_case):
        client.patch(f"/api/exceptions/{alices_case}/status", headers=BOB,
                     json={"status": "awaiting_vendor"})
        case = client.get(f"/api/exceptions/{alices_case}", headers=ALICE).get_json()
        assert case["status"] == "received"

    def test_the_owner_is_unaffected(self, client, alices_case):
        assert client.get(f"/api/exceptions/{alices_case}", headers=ALICE).status_code == 200

    def test_nobody_can_upload_into_another_workspaces_case(self, client, alices_case):
        response = client.post(f"/api/exceptions/{alices_case}/documents", headers=BOB,
                               data={"files": []}, content_type="multipart/form-data")
        assert response.status_code == 404


# ---------------------------------------------------------------------------
# The cross-case checks stop at the workspace boundary
# ---------------------------------------------------------------------------
class TestCrossCaseChecksAreScoped:
    """The checks in services/history_service.py assert that two documents are
    THE SAME BILL. Run across workspaces, the seeded corpus would report a
    new user's first genuine invoice as a duplicate of a synthetic one."""

    @staticmethod
    def _invoice_document(exception_id: str, workspace_id: str, *, number: str,
                          vendor: str, amount: float) -> dict:
        return {
            "document_id": f"DOC-{exception_id}",
            "exception_id": exception_id,
            "workspace_id": workspace_id,
            "document_type": "vendor_invoice",
            "processing_state": "completed",
            "uploaded_at": "2026-03-01T00:00:00+00:00",
            "extraction": {
                "invoice_number": number,
                "vendor_name": vendor,
                "total_amount": amount,
                "invoice_date": "2026-03-01",
            },
        }

    def test_the_lookback_only_returns_documents_from_one_workspace(self):
        ds = get_datastore()
        ds.save_document(self._invoice_document(
            "EXC-A", "user:uid-alice", number="INV-1", vendor="Acme", amount=1000))
        ds.save_document(self._invoice_document(
            "EXC-B", "user:uid-bob", number="INV-2", vendor="Acme", amount=1000))

        alice_view = ds.find_documents_by_type("vendor_invoice", workspace_id="user:uid-alice")
        assert [d["exception_id"] for d in alice_view] == ["EXC-A"]

        bob_view = ds.find_documents_by_type("vendor_invoice", workspace_id="user:uid-bob")
        assert [d["exception_id"] for d in bob_view] == ["EXC-B"]

    def test_no_workspace_means_no_scoping_for_the_loaders(self):
        """None is the eval harness and the BigQuery loader, which own the
        whole store. It is never what a request sends."""
        ds = get_datastore()
        ds.save_document(self._invoice_document(
            "EXC-A", "user:uid-alice", number="INV-1", vendor="Acme", amount=1000))
        ds.save_document(self._invoice_document(
            "EXC-B", "user:uid-bob", number="INV-2", vendor="Acme", amount=1000))
        found = {d["exception_id"] for d in ds.find_documents_by_type("vendor_invoice")}
        assert {"EXC-A", "EXC-B"} <= found

    def test_a_real_invoice_is_not_reported_as_a_duplicate_of_a_seeded_one(self):
        """The accusation this scoping exists to prevent.

        Alice uploads an invoice that is, field for field, identical to one in
        the seeded corpus. Same vendor, same number, same amount — which is
        exactly what a duplicate looks like. It is not one: it is the first
        invoice in her ledger, and she has never seen the other.
        """
        ds = get_datastore()
        seeded = self._invoice_document(
            "EXC-SEED", DEMO, number="INV-COLLIDE", vendor="Chennai Industrial Supplies Pvt. Ltd.",
            amount=265000)
        ds.save_document(seeded)

        alices = self._invoice_document(
            "EXC-ALICE", "user:uid-alice", number="INV-COLLIDE",
            vendor="Chennai Industrial Supplies Pvt. Ltd.", amount=265000)

        scoped, _ = ingestion_service.build_matching_input(
            [alices], ds, "EXC-ALICE", workspace_id="user:uid-alice")
        assert scoped["duplicate_of"] == []

        # And the same call without the scoping does find it — so the test
        # above is passing because of the workspace filter and not because the
        # duplicate rule failed to fire on identical documents.
        unscoped, _ = ingestion_service.build_matching_input(
            [alices], ds, "EXC-ALICE", workspace_id=None)
        assert unscoped["duplicate_of"], "the duplicate rule did not fire at all"

    def test_a_genuine_duplicate_inside_one_workspace_is_still_caught(self):
        """Scoping must narrow the lookback, not disable it."""
        ds = get_datastore()
        ds.save_document(self._invoice_document(
            "EXC-FIRST", "user:uid-alice", number="INV-777", vendor="Acme Parts", amount=90000))
        second = self._invoice_document(
            "EXC-SECOND", "user:uid-alice", number="INV-777", vendor="Acme Parts", amount=90000)

        matching_input, _ = ingestion_service.build_matching_input(
            [second], ds, "EXC-SECOND", workspace_id="user:uid-alice")
        assert matching_input["duplicate_of"]

    def test_analysis_reads_the_workspace_off_the_case_not_off_the_request(self, client):
        """A re-analysis triggered by a background job has no request
        identity, and the answer must not depend on who started it."""
        created = client.post("/api/exceptions", headers=ALICE, json={}).get_json()
        assert get_datastore().get_exception(
            created["exception_id"])["workspace_id"] == "user:uid-alice"
