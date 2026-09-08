"""
Approval authority, per-vendor tolerances, upload grouping and email intake.

`approved_with_exception` releases money the match called questionable. Before
this, any signed-in user could set it on any case at any value; the audit
trail then recorded who did it, which is a log of a control failure rather
than a control.
"""
import pytest

from datastore import resolve_tolerance
from services import approval_service as A
from services import email_intake as E
from services import ingestion_service as I

CASE = {"exception_id": "EXC-1", "created_by": "clerk@example.com"}
DOCUMENTS = [{"document_id": "D1", "uploaded_by": "clerk@example.com"}]
POLICY = {
    "segregation_of_duties": True,
    "limits": [
        {"role": "ap_clerk", "max_value": 50000},
        {"role": "ap_manager", "max_value": 500000},
        {"role": "controller", "max_value": None},
    ],
}


# --- segregation of duties ------------------------------------------------
def test_the_person_who_prepared_a_case_cannot_approve_it():
    with pytest.raises(A.ApprovalDenied) as raised:
        A.check_approval("approved_with_exception", actor="clerk@example.com",
                         actor_role="controller", case=CASE, documents=DOCUMENTS,
                         amount=1000.0, policy=POLICY)
    assert raised.value.code == "segregation_of_duties"


def test_a_second_reviewer_may_approve_the_same_case():
    A.check_approval("approved_with_exception", actor="manager@example.com",
                     actor_role="ap_manager", case=CASE, documents=DOCUMENTS,
                     amount=1000.0, policy=POLICY)


def test_an_uploader_who_did_not_create_the_case_still_cannot_approve_it():
    documents = [{"document_id": "D1", "uploaded_by": "other@example.com"}]
    with pytest.raises(A.ApprovalDenied):
        A.check_approval("approved_with_exception", actor="other@example.com",
                         actor_role="controller", case=CASE, documents=documents,
                         amount=1000.0, policy=POLICY)


def test_identity_comparison_ignores_case_and_spacing():
    with pytest.raises(A.ApprovalDenied):
        A.check_approval("approved_with_exception", actor="  Clerk@Example.com ",
                         actor_role="controller", case=CASE, documents=DOCUMENTS,
                         amount=1000.0, policy=POLICY)


# --- approval limits ------------------------------------------------------
def test_a_clerk_cannot_release_more_than_their_band():
    with pytest.raises(A.ApprovalDenied) as raised:
        A.check_approval("approved_with_exception", actor="manager@example.com",
                         actor_role="ap_clerk", case=CASE, documents=DOCUMENTS,
                         amount=62540.0, policy=POLICY)
    assert raised.value.code == "approval_limit_exceeded"
    assert raised.value.context["limit"] == 50000


def test_a_manager_can_release_what_a_clerk_cannot():
    A.check_approval("approved_with_exception", actor="manager@example.com",
                     actor_role="ap_manager", case=CASE, documents=DOCUMENTS,
                     amount=62540.0, policy=POLICY)


def test_a_null_limit_means_no_limit():
    A.check_approval("approved_with_exception", actor="controller@example.com",
                     actor_role="controller", case=CASE, documents=DOCUMENTS,
                     amount=99000000.0, policy=POLICY)


def test_an_unlisted_role_carries_no_authority():
    """The safe reading of a role nobody granted anything to."""
    with pytest.raises(A.ApprovalDenied) as raised:
        A.check_approval("approved_with_exception", actor="stranger@example.com",
                         actor_role="intern", case=CASE, documents=DOCUMENTS,
                         amount=1.0, policy=POLICY)
    assert raised.value.code == "role_not_authorized"


def test_statuses_that_do_not_release_money_are_unrestricted():
    A.check_approval("awaiting_vendor", actor="clerk@example.com", actor_role=None,
                     case=CASE, documents=DOCUMENTS, amount=99000000.0, policy=POLICY)


def test_an_unconfigured_workspace_behaves_exactly_as_before():
    """An absent policy must not become an implicit denial — the demo flow
    has no roles at all."""
    A.check_approval("approved_with_exception", actor="anyone@example.com",
                     actor_role=None, case=CASE, documents=DOCUMENTS,
                     amount=99000000.0, policy={"segregation_of_duties": False})


# --- tolerance resolution -------------------------------------------------
BASE = {
    "price_variance_percent": 5, "quantity_variance_percent": 2,
    "by_vendor": {"SIGMA ENGINEERING SOLUTIONS": {"price_variance_percent": 1}},
    "by_category": {"services": {"price_variance_percent": 3}},
}


def test_the_workspace_default_applies_when_nothing_more_specific_matches():
    resolved = resolve_tolerance(BASE, vendor_name="OTHER", category="goods")
    assert resolved["price_variance_percent"] == 5
    assert resolved["tolerance_source"] == "workspace default"


def test_a_category_rule_beats_the_default():
    resolved = resolve_tolerance(BASE, vendor_name="OTHER", category="services")
    assert resolved["price_variance_percent"] == 3
    assert "category" in resolved["tolerance_source"]


def test_a_vendor_rule_beats_a_category_rule():
    resolved = resolve_tolerance(BASE, vendor_name="Sigma Engineering Solutions",
                                 category="services")
    assert resolved["price_variance_percent"] == 1
    assert "vendor" in resolved["tolerance_source"]


def test_an_override_does_not_blank_the_settings_it_omits():
    resolved = resolve_tolerance(BASE, vendor_name="SIGMA ENGINEERING SOLUTIONS")
    assert resolved["quantity_variance_percent"] == 2


def test_the_resolved_rule_reports_where_it_came_from():
    """A reviewer asking "why was this within tolerance?" needs the answer."""
    assert resolve_tolerance(BASE)["tolerance_source"] == "workspace default"


# --- upload grouping ------------------------------------------------------
def _doc(document_id, po, file_name):
    return {"document_id": document_id, "file_name": file_name,
            "document_type": "purchase_order", "extraction": {"po_number": po}}


def test_documents_from_two_different_orders_are_flagged_at_upload():
    grouping = I.group_by_reference([
        _doc("D1", "PO/SRPL/26/19451", "po-a.pdf"),
        _doc("D2", "PO/SRPL/26/19451", "invoice-a.pdf"),
        _doc("D3", "PO/SMPL/26/19596", "po-b.pdf"),
    ])

    assert grouping["is_mixed"] is True
    assert len(grouping["groups"]) == 2
    assert "different orders" in grouping["detail"]


def test_one_order_is_not_flagged():
    grouping = I.group_by_reference([
        _doc("D1", "PO/SRPL/26/19451", "po.pdf"),
        _doc("D2", "PO-SRPL-26-19451", "invoice.pdf"),  # same order, written differently
    ])

    assert grouping["is_mixed"] is False
    assert grouping["detail"] is None


def test_a_document_stating_no_reference_is_unassigned_not_misfiled():
    grouping = I.group_by_reference([
        _doc("D1", "PO/1", "po.pdf"),
        {"document_id": "D2", "file_name": "grn.pdf",
         "document_type": "goods_receipt_note", "extraction": {}},
    ])

    assert [d["document_id"] for d in grouping["unassigned"]] == ["D2"]
    assert grouping["is_mixed"] is False


# --- email intake ---------------------------------------------------------
def test_only_allowed_senders_are_processed():
    assert E.sender_allowed("Billing <billing@sigmaengsol.com>", ["billing@sigmaengsol.com"])
    assert E.sender_allowed("Anyone <ap@sigmaengsol.com>", ["@sigmaengsol.com"])
    assert not E.sender_allowed("Someone <x@evil.com>", ["@sigmaengsol.com"])


def test_a_display_name_cannot_impersonate_an_allowed_sender():
    """Any sender can set a display name; only the parsed address counts."""
    assert not E.sender_allowed('"billing@sigmaengsol.com" <attacker@evil.com>',
                                ["billing@sigmaengsol.com"])


def test_an_empty_allow_list_accepts_nobody():
    """An inbox that takes documents from anyone is an open door into an
    approval queue."""
    assert not E.sender_allowed("billing@sigmaengsol.com", [])


def test_intake_is_inert_until_it_is_configured():
    result = E.poll_once(lambda message: "EXC-1")
    assert result["enabled"] is False
    assert result["processed"] == 0


def test_non_pdf_attachments_are_ignored():
    import email.message

    message = email.message.EmailMessage()
    message["From"] = "billing@sigmaengsol.com"
    message.set_content("See attached")
    message.add_attachment(b"not a pdf", maintype="application", subtype="zip",
                           filename="invoice.zip")

    assert E.extract_pdf_attachments(message) == []


def test_a_pdf_attachment_that_is_not_really_a_pdf_is_rejected():
    """Validated exactly as an upload is — extension AND magic bytes."""
    import email.message

    message = email.message.EmailMessage()
    message["From"] = "billing@sigmaengsol.com"
    message.set_content("See attached")
    message.add_attachment(b"MZ this is an executable", maintype="application",
                           subtype="pdf", filename="invoice.pdf")

    assert E.extract_pdf_attachments(message) == []


def test_a_genuine_pdf_attachment_is_accepted():
    import email.message

    import fitz

    document = fitz.open()
    document.new_page()
    data = document.tobytes()
    document.close()

    message = email.message.EmailMessage()
    message["From"] = "billing@sigmaengsol.com"
    message.set_content("See attached")
    message.add_attachment(data, maintype="application", subtype="pdf",
                           filename="invoice.pdf")

    attachments = E.extract_pdf_attachments(message)
    assert len(attachments) == 1
    assert attachments[0]["file_name"] == "invoice.pdf"


def test_a_case_from_the_mailbox_records_where_it_came_from():
    """routes/intake.py hands create_case the sender, subject and message id;
    create_case read none of them and hard-coded origin="upload", so an
    emailed case was stored claiming it had been keyed in by hand with no
    trace of which message produced it."""
    from datastore import get_datastore

    case = I.create_case(get_datastore(), "demo-workspace", "email-intake", {
        "source": "email",
        "source_sender": "billing@sigmaengsol.com",
        "source_subject": "Invoice INV-2026-1187",
        "source_message_id": "<a1b2@sigmaengsol.com>",
    })

    assert case["origin"] == "email"
    assert case["source_sender"] == "billing@sigmaengsol.com"
    assert case["source_subject"] == "Invoice INV-2026-1187"
    assert case["source_message_id"] == "<a1b2@sigmaengsol.com>"


def test_a_hand_uploaded_case_is_still_recorded_as_an_upload():
    from datastore import get_datastore

    case = I.create_case(get_datastore(), "demo-workspace", "me@example.com",
                         {"vendor_name": "Acme"})
    assert case["origin"] == "upload"
    assert "source_sender" not in case
