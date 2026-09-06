"""
firebase_app.py — the ONE place that calls firebase_admin.initialize_app().

Both firestore_client.py (Firestore reads/writes) and services/auth_service.py
(ID token verification) need an initialized Firebase Admin app. Before this
module existed they'd each try to initialize it independently, and the
second call would raise ValueError("The default Firebase app already
exists"). get_firebase_app() is idempotent and safe to call from both.
"""
from __future__ import annotations

import json

import firebase_admin
from firebase_admin import credentials

from config import config

_app = None


def get_firebase_app():
    global _app
    if _app is not None:
        return _app

    if firebase_admin._apps:
        _app = firebase_admin.get_app()
        return _app

    if config.FIREBASE_SERVICE_ACCOUNT_JSON:
        try:
            cred = credentials.Certificate(json.loads(config.FIREBASE_SERVICE_ACCOUNT_JSON))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("FIREBASE_SERVICE_ACCOUNT_JSON must contain valid service-account JSON") from exc
    elif config.GOOGLE_APPLICATION_CREDENTIALS:
        cred = credentials.Certificate(config.GOOGLE_APPLICATION_CREDENTIALS)
    else:
        # Falls back to Application Default Credentials — e.g. when running
        # on Cloud Run with a service account attached, rather than a local
        # serviceAccountKey.json file.
        cred = credentials.ApplicationDefault()

    options = {"storageBucket": config.FIREBASE_STORAGE_BUCKET} if config.FIREBASE_STORAGE_BUCKET else None
    _app = firebase_admin.initialize_app(cred, options)
    return _app
