"""
firestore_client.py — one lazily-initialized Firestore client for the whole
app. Never imported by anything on the mock-mode code path, so a demo/dev
environment with no serviceAccountKey.json never touches this file at all.
"""
from __future__ import annotations

from firebase_admin import firestore

from firebase_app import get_firebase_app

_db = None


def get_db():
    global _db
    if _db is not None:
        return _db
    get_firebase_app()
    _db = firestore.client()
    return _db
