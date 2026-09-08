"""
test_case_title.py — letting a person name a case.

`EXC-2026-A3F81B04` is a fine primary key and a poor thing to say out loud in
a stand-up. A title is optional, carries no authority, and is checked by
nothing: it is a label the product prints, and the identity every check
actually runs on stays the extracted invoice number and purchase order
reference, because those come from the documents and this comes from whoever
was typing.

That distinction is what most of this file asserts. A title must not reach a
matcher, must not move a case toward being paid, and must not become a way to
smuggle formatting into a queue row or an audit note.
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")

from datastore import get_datastore  # noqa: E402
from services import ingestion_service  # noqa: E402

ALICE = {"Authorization": "Bearer alice-token"}
BOB = {"Authorization": "Bearer bob-token"}


@pytest.fixture
def client():
    from app import create_app

    return create_app().test_client()


@pytest.fixture
def titled(client):
    return client.post("/api/exceptions", headers=ALICE,
                        json={"title": "Q3 pipe delivery dispute"}).get_json()


# ---------------------------------------------------------------------------
# Naming a case
# ---------------------------------------------------------------------------
class TestNamingOnCreate:
    def test_a_case_can_be_given_a_name(self, titled):
        assert titled["title"] == "Q3 pipe delivery dispute"

    def test_the_name_is_optional(self, client):
        """The point of the feature. Nothing in the product requires one, and
        a case without a title behaves exactly as every case did before."""
        untitled = client.post("/api/exceptions", headers=ALICE, json={}).get_json()
        assert untitled["title"] is None
        assert untitled["exception_id"].startswith("EXC-")

    def test_the_generated_reference_is_still_there_alongside_it(self, titled):
        """A title is a display label, not an identifier. Everything that
        addresses this case still addresses it by exception_id."""
        assert titled["exception_id"].startswith("EXC-")

    def test_the_name_appears_in_the_queue(self, client, titled):
        rows = client.get("/api/exceptions", headers=ALICE).get_json()
        row = next(r for r in rows if r["exception_id"] == titled["exception_id"])
        assert row["title"] == "Q3 pipe delivery dispute"

    def test_naming_is_recorded_in_the_audit_trail(self, client, titled):
        audit = client.get(f"/api/exceptions/{titled['exception_id']}/audit",
                           headers=ALICE).get_json()
        assert "Q3 pipe delivery dispute" in audit[0]["note"]


# ---------------------------------------------------------------------------
# Renaming
# ---------------------------------------------------------------------------
class TestRenaming:
    def test_a_case_can_be_renamed(self, client, titled):
        response = client.patch(f"/api/exceptions/{titled['exception_id']}",
                                headers=ALICE, json={"title": "Pipe dispute — settled"})
        assert response.status_code == 200
        assert response.get_json()["title"] == "Pipe dispute — settled"

    def test_an_untitled_case_can_be_named_later(self, client):
        """A case is usually opened before anyone knows what to call it."""
        case = client.post("/api/exceptions", headers=ALICE, json={}).get_json()
        response = client.patch(f"/api/exceptions/{case['exception_id']}",
                                headers=ALICE, json={"title": "Sigma overbilling"})
        assert response.get_json()["title"] == "Sigma overbilling"

    def test_a_name_can_be_cleared(self, client, titled):
        """Back to showing the reference, which is a real thing to want after
        naming a case by mistake."""
        response = client.patch(f"/api/exceptions/{titled['exception_id']}",
                                headers=ALICE, json={"title": None})
        assert response.get_json()["title"] is None

    def test_renaming_is_audited_with_both_names(self, client, titled):
        """A title matters to no control, but "the case I approved was called
        something else" is a question an auditor can ask."""
        client.patch(f"/api/exceptions/{titled['exception_id']}",
                     headers=ALICE, json={"title": "Renamed case"})
        audit = client.get(f"/api/exceptions/{titled['exception_id']}/audit",
                           headers=ALICE).get_json()
        event = next(e for e in audit if e["action"] == "case_renamed")
        assert "Q3 pipe delivery dispute" in event["note"]
        assert "Renamed case" in event["note"]
        assert event["actor"] == "alice@acme.example"

    def test_renaming_to_the_same_title_writes_no_audit_event(self, client, titled):
        """An idempotent call is not a change, and an audit trail padded with
        non-events is harder to read than one without them."""
        client.patch(f"/api/exceptions/{titled['exception_id']}",
                     headers=ALICE, json={"title": "Q3 pipe delivery dispute"})
        audit = client.get(f"/api/exceptions/{titled['exception_id']}/audit",
                           headers=ALICE).get_json()
        assert [e for e in audit if e["action"] == "case_renamed"] == []

    def test_a_request_with_no_title_field_is_rejected(self, client, titled):
        """Distinguished from `{"title": null}`, which deliberately clears it.
        An empty body is a caller mistake and silently doing nothing would
        hide it."""
        response = client.patch(f"/api/exceptions/{titled['exception_id']}",
                                headers=ALICE, json={})
        assert response.status_code == 400
        assert response.get_json()["error"] == "nothing_to_update"

    def test_nobody_can_rename_another_workspaces_case(self, client, titled):
        response = client.patch(f"/api/exceptions/{titled['exception_id']}",
                                headers=BOB, json={"title": "Mine now"})
        assert response.status_code == 404
        assert client.get(f"/api/exceptions/{titled['exception_id']}",
                          headers=ALICE).get_json()["title"] == "Q3 pipe delivery dispute"


# ---------------------------------------------------------------------------
# What a title is allowed to be
# ---------------------------------------------------------------------------
class TestTitleNormalization:
    def test_whitespace_only_is_no_title(self):
        """"   " and "" both mean unnamed, rather than a case that looks
        unnamed and sorts oddly."""
        assert ingestion_service.normalize_title("   ") is None
        assert ingestion_service.normalize_title("") is None
        assert ingestion_service.normalize_title(None) is None

    def test_surrounding_whitespace_is_trimmed(self):
        assert ingestion_service.normalize_title("  Pipe dispute  ") == "Pipe dispute"

    def test_control_characters_are_stripped(self):
        """A title is rendered in a queue row, a page heading and an audit
        note. A newline smuggled through any of those is a formatting bug."""
        assert ingestion_service.normalize_title("Pipe\ndispute\ttoday") == "Pipe dispute today"
        assert "\x00" not in (ingestion_service.normalize_title("Pipe\x00dispute") or "")

    def test_an_over_long_title_is_truncated_not_rejected(self):
        """Someone pasting a whole invoice line into the name field wants a
        name. Refusing the create call over it would lose the documents they
        were uploading."""
        long_title = "x" * 500
        result = ingestion_service.normalize_title(long_title)
        assert len(result) == ingestion_service.MAX_TITLE_LENGTH

    def test_ordinary_punctuation_and_non_ascii_survive(self):
        """Case names are written by people, in the languages people use."""
        assert ingestion_service.normalize_title("Sigma — ₹1.8L variance (Q3)") == \
            "Sigma — ₹1.8L variance (Q3)"
        assert ingestion_service.normalize_title("சென்னை supplies") == "சென்னை supplies"


# ---------------------------------------------------------------------------
# A title is a label and nothing more
# ---------------------------------------------------------------------------
class TestTitleCarriesNoAuthority:
    def test_a_title_does_not_change_the_analysis(self, client):
        """The identity every check runs on comes from the documents. If a
        typed label could move a finding, it would be an input to a control
        that nobody validates."""
        plain = client.post("/api/exceptions", headers=ALICE,
                            json={"vendor_name": "Acme"}).get_json()
        named = client.post("/api/exceptions", headers=ALICE,
                            json={"vendor_name": "Acme", "title": "APPROVED — pay immediately"}).get_json()

        ds = get_datastore()
        for case_id in (plain["exception_id"], named["exception_id"]):
            case = ds.get_exception(case_id)
            assert case["status"] == "received"
            # get_exception returns the public view, which withholds the
            # matching input; ask for it directly.
            assert ds.get_matching_input(case_id) is None

    def test_a_title_is_not_used_as_a_vendor_or_invoice_reference(self, client):
        case = client.post("/api/exceptions", headers=ALICE,
                            json={"title": "INV-2026-1187"}).get_json()
        assert case["invoice_id"] is None
        assert case["vendor_name"] is None

    def test_renaming_cannot_change_status(self, client, titled):
        client.patch(f"/api/exceptions/{titled['exception_id']}",
                     headers=ALICE, json={"title": "New name", "status": "approved_with_exception"})
        case = client.get(f"/api/exceptions/{titled['exception_id']}",
                          headers=ALICE).get_json()
        assert case["status"] == "received"
