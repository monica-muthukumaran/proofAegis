"""
app.py — Flask application factory for ProofAegis.

Run locally:
    python app.py

Deploy target (Document 4, Day 13/20): Cloud Run, behind Firebase Hosting
for the frontend. See scripts/seed_firestore.py for populating a real
Firestore project before switching USE_MOCK_DATA off.
"""
from __future__ import annotations

import logging

from flask import Flask, jsonify
from flask_cors import CORS

from config import config
from routes.analytics import bp as analytics_bp
from routes.auth import bp as auth_bp
from routes.dashboard import bp as dashboard_bp
from routes.intake import bp as intake_bp
from routes.exceptions import bp as exceptions_bp
from routes.settings import bp as settings_bp

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


def create_app() -> Flask:
    app = Flask(__name__)

    # Restricted CORS (Day 19 hardening note) — one explicit origin, not "*".
    # allow_headers must include Authorization or the browser's CORS
    # preflight strips it before the Firebase ID token ever reaches Flask.
    CORS(
        app,
        origins=list(config.ALLOWED_ORIGINS),
        supports_credentials=True,
        allow_headers=["Content-Type", "Authorization"],
    )

    app.register_blueprint(exceptions_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(analytics_bp)
    app.register_blueprint(intake_bp)

    @app.get("/api/health")
    def health():
        return jsonify({
            "status": "ok",
            "mock_mode": config.USE_MOCK_DATA,
            "auth_required": config.AUTH_REQUIRED,
            # Empty off Cloud Run. Present so a deploy can compare what the CDN
            # serves against what Cloud Run is actually running.
            "revision": config.REVISION,
        })

    @app.errorhandler(404)
    def not_found(_e):
        return jsonify({"error": "not_found"}), 404

    @app.errorhandler(Exception)
    def handle_uncaught(e):
        # Never leak stack traces or secrets to the client (Day 19).
        app.logger.exception("unhandled_exception")
        return jsonify({"error": "internal_error"}), 500

    return app


app = create_app()

if __name__ == "__main__":
    import os
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
