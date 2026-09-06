"""
Minimal coverage for the P0 ingestion pipeline — the things that would be
expensive to get wrong, not an exhaustive suite:

  * upload validation rejects non-PDFs by CONTENT, not just extension
  * a real synthetic PDF produces real extracted fields
  * matching after extraction reproduces the documented case figures
  * a missing goods receipt is a FINDING, not an upload error
  * storage paths are workspace-scoped
  * dashboard/settings actually require auth when AUTH_REQUIRED is on

conftest.py pins STORAGE_BACKEND=local, so nothing here touches a bucket.
"""
import io
import os
import sys

import pytest

sys.path.insert(0, ".")

from config import config
from services import ingestion_service
from services.ingestion_service import UploadValidationError
from services.storage_service import build_object_path

PDF_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "data", "synthetic_cases")

pytestmark = pytest.mark.skipif(
    not os.path.isdir(PDF_DIR),
    reason="Run scripts/generate_synthetic_pdfs.py first.",
)


def read_pdf(case: str, name: str) -> bytes:
    with open(os.path.join(PDF_DIR, case, name), "rb") as f:
        return f.read()


@pytest.fixture
def client():
    from app import create_app
    return create_app().test_client()


def upload(client, case: str, names: list[str]):
    exception_id = client.post("/api/exceptions", json={}).get_json()["exception_id"]
    files = [(io.BytesIO(read_pdf(case, n)), n) for n in names]
    response = client.post(f"/api/exceptions/{exception_id}/documents",
                            data={"files": files}, content_type="multipart/form-data")
    return exception_id, response


# --- validation -----------------------------------------------------------
def test_rejects_non_pdf_content_despite_pdf_extension():
    with pytest.raises(UploadValidationError) as excinfo:
        ingestion_service.validate_upload("invoice.pdf", b"MZ\x90\x00 not a pdf", None)
    assert excinfo.value.code == "not_a_pdf"


def test_rejects_oversized_file():
    oversized = b"%PDF-" + b"0" * (config.MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 1)
    with pytest.raises(UploadValidationError) as excinfo:
        ingestion_service.validate_upload("big.pdf", oversized, None)
    assert excinfo.value.code == "file_too_large"


def test_rejects_unknown_document_type():
    with pytest.raises(UploadValidationError) as excinfo:
        ingestion_service.validate_upload("x.pdf", b"%PDF-1.4", "bank_statement")
    assert excinfo.value.code == "unsupported_document_type"


def test_storage_path_is_workspace_scoped():
    assert build_object_path("ws1", "EXC-1", "DOC-1") == "workspaces/ws1/cases/EXC-1/DOC-1.pdf"


# --- the hero workflow, end to end ---------------------------------------
def test_price_variance_case_is_computed_from_uploaded_pdfs(client):
    exception_id, response = upload(client, "price_variance_001", [
        "purchase_order.pdf", "vendor_invoice.pdf", "goods_receipt_note.pdf", "rejection_notice.pdf",
    ])
    assert response.status_code == 201
    documents = response.get_json()["documents"]
    assert {d["document_type"] for d in documents} == {
        "purchase_order", "vendor_invoice", "goods_receipt_note", "rejection_notice"
    }
    assert all(d["processing_state"] == "completed" for d in documents)

    match = client.get(f"/api/exceptions/{exception_id}/match").get_json()
    assert match["exception_type"] == "price_variance"
    assert match["financial_impact"] == 25000  # 250/unit x 100 units
    assert match["recommended_owner"] == "Procurement"

    # The identifying fields come from extraction, not from anything typed in.
    case = client.get(f"/api/exceptions/{exception_id}").get_json()
    assert case["invoice_id"] == "INV-2026-1187"
    assert case["vendor_name"] == "Chennai Industrial Supplies Pvt. Ltd."
    assert case["status"] == "exception_detected"


def test_quantity_variance_case_is_computed_from_uploaded_pdfs(client):
    exception_id, _ = upload(client, "quantity_variance_001", [
        "purchase_order.pdf", "vendor_invoice.pdf", "goods_receipt_note.pdf",
    ])
    match = client.get(f"/api/exceptions/{exception_id}/match").get_json()
    assert match["exception_type"] == "quantity_variance"
    assert match["financial_impact"] == 50400  # 80 unreceived x 630 implied
    assert match["recommended_owner"] == "Receiving"


def test_missing_goods_receipt_is_a_finding_not_an_upload_error(client):
    exception_id, response = upload(client, "missing_receipt_001", [
        "purchase_order.pdf", "vendor_invoice.pdf", "rejection_notice.pdf",
    ])
    assert response.status_code == 201
    assert response.get_json()["rejected"] == []

    match = client.get(f"/api/exceptions/{exception_id}/match").get_json()
    assert match["exception_type"] == "missing_goods_receipt"
    assert match["financial_impact"] == 180000  # whole invoice at risk

    readiness = client.get(f"/api/exceptions/{exception_id}/readiness").get_json()
    assert readiness["can_analyze"] is True
    assert "goods_receipt_note" in readiness["missing_document_types"]


def test_case_accepts_more_documents_later_and_reanalyzes(client):
    """A case is never closed to new evidence: uploading the goods receipt
    afterwards must turn the missing-receipt finding into a real comparison."""
    exception_id, _ = upload(client, "quantity_variance_001", ["vendor_invoice.pdf"])
    first = client.get(f"/api/exceptions/{exception_id}/match").get_json()
    # Invoice alone: no PO to price against either, and a missing PO
    # short-circuits ahead of a missing receipt in matching_service.py.
    assert first["exception_type"] == "missing_purchase_order"

    files = [(io.BytesIO(read_pdf("quantity_variance_001", n)), n)
             for n in ("purchase_order.pdf", "goods_receipt_note.pdf")]
    client.post(f"/api/exceptions/{exception_id}/documents",
                 data={"files": files}, content_type="multipart/form-data")

    second = client.get(f"/api/exceptions/{exception_id}/match").get_json()
    assert second["exception_type"] == "quantity_variance"
    assert second["financial_impact"] == 50400


def test_a_case_with_no_invoice_reports_why_instead_of_failing(client):
    exception_id, response = upload(client, "price_variance_001", ["purchase_order.pdf"])
    assert response.status_code == 201
    readiness = response.get_json()["analysis"]["readiness"]
    assert readiness["can_analyze"] is False
    assert "vendor invoice" in readiness["blocking_reason"]


def test_bad_file_in_a_batch_does_not_sink_the_good_ones(client):
    exception_id = client.post("/api/exceptions", json={}).get_json()["exception_id"]
    files = [
        (io.BytesIO(read_pdf("price_variance_001", "vendor_invoice.pdf")), "vendor_invoice.pdf"),
        (io.BytesIO(b"not a pdf at all"), "junk.pdf"),
    ]
    response = client.post(f"/api/exceptions/{exception_id}/documents",
                            data={"files": files}, content_type="multipart/form-data")
    assert response.status_code == 207  # partial success
    body = response.get_json()
    assert len(body["documents"]) == 1
    assert body["rejected"][0]["error"] == "not_a_pdf"


# --- authorization --------------------------------------------------------
@pytest.fixture
def strict_auth():
    original = config.AUTH_REQUIRED
    config.AUTH_REQUIRED = True
    yield
    config.AUTH_REQUIRED = original


@pytest.mark.parametrize("path", [
    "/api/dashboard/summary",
    "/api/settings/tolerance",
    "/api/settings/mode",
])
def test_previously_unauthenticated_routes_now_require_a_token(client, strict_auth, path):
    assert client.get(path).status_code == 401


def test_upload_requires_a_token_in_strict_mode(client, strict_auth):
    assert client.post("/api/exceptions", json={}).status_code == 401
