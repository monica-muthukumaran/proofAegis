"""
routes/settings.py — the Settings screen's entire backend surface: a
read-only display of settings/tolerance_rules (FR-006, Document 1 §8).
"""
from __future__ import annotations

from flask import Blueprint, jsonify

from auth import current_workspace_id, is_demo_workspace, require_auth
from datastore import get_datastore
from config import config
from services import analytics_gateway, seed_context

bp = Blueprint("settings", __name__, url_prefix="/api/settings")

# The agents that actually call a model, and which model each one calls.
#
# Kept as one table here rather than discovered by import, because the point
# is to state a fact a reviewer can check: every entry names a real module,
# and the model attribute it names is the one that module passes to the SDK.
# If an agent is rewired to a different model, this list is wrong until it is
# updated — which is the correct failure mode for a disclosure surface. A
# reflective version that could never be wrong would also never be readable.
#
# `stage` is the step of the pipeline the agent belongs to, so the UI can
# order them the way the product actually runs.
AGENT_REGISTRY = (
    ("document", "Document extraction", "GEMINI_MODEL", "extract"),
    ("exception", "Exception reasoning", "GEMINI_REASONING_MODEL", "reason"),
    ("hypothesis", "Investigation hypotheses", "GEMINI_REASONING_MODEL", "investigate"),
    ("portfolio", "Cross-case portfolio", "GEMINI_REASONING_MODEL", "investigate"),
    ("resolution", "Resolution drafting", "GEMINI_REASONING_MODEL", "resolve"),
)


def _agent_status(live: bool) -> list[dict]:
    """One row per model-calling agent, for the UI's agent badge.

    `live` is passed in rather than recomputed so that every row agrees with
    the single `gemini_active` verdict above it. A per-agent "live" that could
    disagree with the banner beside it would be worse than no badge at all.
    """
    return [
        {
            "key": key,
            "label": label,
            "model": getattr(config, attr, None),
            "stage": stage,
            "live": live,
        }
        for key, label, attr, stage in AGENT_REGISTRY
    ]


@bp.get("/tolerance")
@require_auth
def get_tolerance():
    ds = get_datastore()
    return jsonify(ds.get_tolerance_rules())


@bp.get("/mode")
@require_auth
def get_mode():
    """The single source of truth for the frontend's mode banner (FR-013).

    The frontend must never infer its mode from a failed request — a 401 is
    not evidence of mock mode. It asks here instead, and this answers with
    what is actually configured on the server."""
    from services.storage_service import get_storage

    storage_kind = get_storage().kind
    workspace_id = current_workspace_id()
    # Computed once and shared by `gemini_active` and every per-agent row, so
    # the badge and the agent list can never contradict each other.
    gemini_active = bool(config.GEMINI_API_KEY) and not config.USE_MOCK_DATA
    return jsonify({
        "mock_mode": config.USE_MOCK_DATA,
        "auth_required": config.AUTH_REQUIRED,
        "datastore": "in_memory_seed" if config.USE_MOCK_DATA else "firestore",
        "storage_backend": storage_kind,
        # Only report a bucket when one is actually in use. Echoing a
        # configured-but-unused bucket name while writing to local disk is the
        # kind of half-truth this endpoint exists to prevent.
        "storage_bucket": config.STORAGE_BUCKET if storage_kind == "gcs" else None,
        "gemini_configured": bool(config.GEMINI_API_KEY),
        # Which engine served the analytics figures — see
        # services/analytics_gateway.py. Surfaced so the UI can name it
        # rather than leaving a viewer to assume which one ran.
        **analytics_gateway.engine_status(),
        # Configured is not the same as used: in mock mode the key is present
        # but no model is ever called, and the UI must say so.
        "gemini_active": gemini_active,
        # WHICH model, not just whether one is on. A deployment that says
        # "AI enabled" without naming the model is unauditable: the whole
        # premise of this product is that a reviewer can check what produced a
        # figure, and "some model did it" fails that test the same way an
        # uncited number does.
        #
        # Reported even when inactive, because "which model WOULD run" is the
        # thing an operator is checking when they look at this in mock mode.
        # `live` on each row is what says whether it is currently running.
        "extraction_model": config.GEMINI_MODEL,
        "reasoning_model": config.GEMINI_REASONING_MODEL,
        "agents": _agent_status(gemini_active),
        # Whether the cases on screen are the seeded synthetic corpus. False
        # in a real user's own workspace, where every case is one they
        # uploaded — the mode banner should stop saying "synthetic data" the
        # moment that stops being true.
        "synthetic_data": is_demo_workspace(workspace_id),
        "workspace_id": workspace_id,
        "demo_workspace": is_demo_workspace(workspace_id),
        "per_user_workspaces": config.PER_USER_WORKSPACES,
        # What the reasoning agent's severity scale is anchored on. Published
        # because a model being grounded on something is a fact a deployment
        # should be able to check rather than take on trust — see
        # services/seed_context.py for what does and does not cross the
        # workspace boundary.
        "model_calibration": seed_context.corpus_stats(),
    })
