"""
storage_service.py — where uploaded case PDFs actually live.

Two backends behind one interface, chosen the same way datastore.py chooses
between Firestore and in-memory:

  - GCSBackend: Firebase/Google Cloud Storage, used when a bucket name and
    credentials are both configured.
  - LocalBackend: the identical object paths written under
    config.LOCAL_STORAGE_DIR. This is what runs in mock mode, in the test
    suite, and on any laptop without a service account — so the whole
    ingestion pipeline is exercised for real, at zero cloud cost, and the
    only thing that changes on deploy is where the bytes land.

Object path (deterministic, workspace-scoped from the first byte written so
P2's tenant isolation is not a retrofit):

    workspaces/{workspace_id}/cases/{exception_id}/{document_id}.pdf

Nothing here ever returns a permanent public URL. Reads go through the
authenticated backend endpoint, or a short-lived signed URL when the caller
explicitly asks for one.
"""
from __future__ import annotations

import logging
import os
from datetime import timedelta
from typing import Optional

from config import config

logger = logging.getLogger("proofaegis.storage")

PDF_MAGIC = b"%PDF-"


class StorageError(Exception):
    """Raised when a file cannot be stored or read back."""


def build_object_path(workspace_id: str, exception_id: str, document_id: str) -> str:
    """The single definition of where a document lives. Used by both backends
    and asserted in tests, so a path change can never silently orphan files."""
    return f"workspaces/{workspace_id}/cases/{exception_id}/{document_id}.pdf"


def looks_like_pdf(data: bytes) -> bool:
    """Content-based check. An attacker (or an honest mistake) renaming
    invoice.exe to invoice.pdf gets caught here, not by the extension."""
    return data[:5] == PDF_MAGIC


class LocalBackend:
    """Filesystem mirror of the GCS layout."""

    kind = "local"

    def __init__(self, root: str):
        self._root = root

    def _full_path(self, object_path: str) -> str:
        return os.path.join(self._root, *object_path.split("/"))

    def upload(self, object_path: str, data: bytes, content_type: str = "application/pdf") -> str:
        full = self._full_path(object_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as f:
            f.write(data)
        return object_path

    def download(self, object_path: str) -> bytes:
        full = self._full_path(object_path)
        if not os.path.isfile(full):
            raise StorageError(f"Object not found: {object_path}")
        with open(full, "rb") as f:
            return f.read()

    def exists(self, object_path: str) -> bool:
        return os.path.isfile(self._full_path(object_path))

    def delete(self, object_path: str) -> None:
        full = self._full_path(object_path)
        if os.path.isfile(full):
            os.remove(full)

    def signed_url(self, object_path: str, ttl_minutes: int) -> Optional[str]:
        # No such thing locally — callers fall back to the authenticated
        # content endpoint, which is the safer path anyway.
        return None


class GCSBackend:
    """Google Cloud Storage / Firebase Storage."""

    kind = "gcs"

    def __init__(self, bucket_name: str):
        from google.cloud import storage  # imported lazily: never touched in mock mode

        self._bucket_name = bucket_name
        self._client = storage.Client(project=config.GOOGLE_CLOUD_PROJECT or None)
        self._bucket = self._client.bucket(bucket_name)

    def upload(self, object_path: str, data: bytes, content_type: str = "application/pdf") -> str:
        blob = self._bucket.blob(object_path)
        blob.upload_from_string(data, content_type=content_type)
        return object_path

    def download(self, object_path: str) -> bytes:
        blob = self._bucket.blob(object_path)
        if not blob.exists():
            raise StorageError(f"Object not found: {object_path}")
        return blob.download_as_bytes()

    def exists(self, object_path: str) -> bool:
        return self._bucket.blob(object_path).exists()

    def delete(self, object_path: str) -> None:
        blob = self._bucket.blob(object_path)
        if blob.exists():
            blob.delete()

    def signed_url(self, object_path: str, ttl_minutes: int) -> Optional[str]:
        """Short-lived, read-only. Never a permanent public URL, and never
        handed out without the caller having passed require_auth first."""
        try:
            blob = self._bucket.blob(object_path)
            return blob.generate_signed_url(expiration=timedelta(minutes=ttl_minutes), method="GET")
        except Exception as exc:  # noqa: BLE001 — signing needs a key the runtime may not have
            logger.warning("signed_url_unavailable object=%s error=%s", object_path, exc)
            return None


_backend = None


def get_storage():
    """Picks a backend once. GCS only when a bucket AND credentials exist —
    otherwise local, so a half-configured deploy degrades to something
    obvious and working rather than throwing on the first upload."""
    global _backend
    if _backend is None:
        if config.STORAGE_BACKEND == "local":
            _backend = LocalBackend(config.LOCAL_STORAGE_DIR)
            logger.info("storage_backend=local (forced) dir=%s", config.LOCAL_STORAGE_DIR)
        elif config.STORAGE_BUCKET and config.HAS_GOOGLE_CREDENTIALS:
            try:
                _backend = GCSBackend(config.STORAGE_BUCKET)
                logger.info("storage_backend=gcs bucket=%s", config.STORAGE_BUCKET)
            except Exception as exc:  # noqa: BLE001
                logger.error("gcs_init_failed_falling_back_to_local error=%s", exc)
                _backend = LocalBackend(config.LOCAL_STORAGE_DIR)
        else:
            _backend = LocalBackend(config.LOCAL_STORAGE_DIR)
            logger.info("storage_backend=local dir=%s", config.LOCAL_STORAGE_DIR)
    return _backend


def reset_storage_for_tests() -> None:
    global _backend
    _backend = None
