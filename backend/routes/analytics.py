"""
routes/analytics.py — portfolio-level analytics (Preventive Control
Intelligence).

Firestore answers "what is happening with THIS case"; these endpoints answer
"where will the next exception come from". Every figure is deterministic
arithmetic over stored outcomes — see services/analytics_service.py.

Cost-aware by construction: every route takes a bounded `days` window,
aggregates rather than returning rows, and caps how many vendors it will
rank. Those constraints are what let the same surface be served by either
engine — see services/analytics_gateway.py. These routes no longer read the
case collection themselves, because on the BigQuery path nothing should:
the window and the row cap become the SQL predicate and the LIMIT.
"""
from __future__ import annotations

import json
import os

from flask import Blueprint, jsonify, request

from auth import require_auth
from services import analytics_gateway, portfolio_agent, trust_ledger

bp = Blueprint("analytics", __name__, url_prefix="/api/analytics")

MAX_WINDOW_DAYS = 730
DEFAULT_WINDOW_DAYS = 365
MAX_VENDOR_ROWS = 50

# Where the eval harness writes its reports. Read-only from here — this route
# never runs an eval, it publishes the result of one somebody ran.
_REPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "generated")


def _window() -> int:
    """Clamped so a client cannot ask for an unbounded scan."""
    try:
        days = int(request.args.get("days", DEFAULT_WINDOW_DAYS))
    except (TypeError, ValueError):
        days = DEFAULT_WINDOW_DAYS
    return max(1, min(days, MAX_WINDOW_DAYS))


@bp.get("/overview")
@require_auth
def overview():
    """Everything the analytics screen needs in one round trip — the page
    renders several linked views of the same population, and fetching them
    separately would let them disagree if a case changed in between."""
    days = _window()
    return jsonify({
        "summary": analytics_gateway.portfolio_summary(days),
        "vendor_risk": analytics_gateway.vendor_risk(days, limit=12),
        "trend": analytics_gateway.monthly_trend(months=12),
        "ageing": analytics_gateway.ageing(days),
        # The product's actual claim, measured on the same population as
        # everything above it: what a per-invoice check would not have found.
        "cross_case": analytics_gateway.cross_case_value(days),
        # How often the deterministic layer had to correct the model.
        "trust": trust_ledger.summarize(),
        # Which engine produced the figures above, so the screen can say so
        # rather than leaving a viewer to assume.
        "engine": analytics_gateway.engine_status(),
    })


@bp.get("/cross-case")
@require_auth
def cross_case():
    """What the cross-case checks caught that a per-invoice system could not.

    Separate from /overview so the demo can open on this one figure without
    waiting for the vendor ranking and the trend series to aggregate.
    """
    return jsonify(analytics_gateway.cross_case_value(_window()))


@bp.get("/accuracy")
@require_auth
def accuracy():
    """The last recorded eval run, if one has been written.

    Served from disk rather than computed on request, and that is the point:
    these figures come from `python -m eval.run_eval --json ...` and
    `python -m eval.extraction_eval --json ...`, which anyone can run and
    reproduce. An endpoint that recomputed a score on demand would be a
    self-report; this is a published result with a command behind it.

    404 when no run has been recorded, so the UI can say "not measured yet"
    instead of rendering an empty table as if it meant zero.
    """
    reports = {}
    for key, filename in (("pipeline", "eval_report.json"),
                          ("extraction", "extraction_report.json")):
        path = os.path.join(_REPORT_DIR, filename)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                reports[key] = json.load(f)
        except (OSError, ValueError):
            # A half-written report must not take the analytics screen down.
            continue

    if not reports:
        return jsonify({
            "error": "not_measured",
            "detail": "No eval run recorded. Run `python -m eval.run_eval --json "
                      "data/generated/eval_report.json` from the backend directory.",
        }), 404
    return jsonify(reports)


@bp.get("/trust")
@require_auth
def trust():
    """The disagreement ledger: every time the deterministic value was checked
    against the model's, and what happened.

    Process-local, and says so — see services/trust_ledger.py. It counts what
    this server instance has actually run rather than a stored history, which
    is the honest scope for a figure about model behaviour.
    """
    return jsonify(trust_ledger.summarize())


@bp.get("/vendor-risk")
@require_auth
def vendor_risk():
    try:
        limit = int(request.args.get("limit", 25))
    except (TypeError, ValueError):
        limit = 25
    return jsonify(analytics_gateway.vendor_risk(_window(), limit=min(limit, MAX_VENDOR_ROWS)))


@bp.get("/trends")
@require_auth
def trends():
    try:
        months = int(request.args.get("months", 12))
    except (TypeError, ValueError):
        months = 12
    return jsonify(analytics_gateway.monthly_trend(months=max(1, min(months, 24))))


@bp.get("/ageing")
@require_auth
def ageing():
    return jsonify(analytics_gateway.ageing(_window()))


@bp.post("/ask")
@require_auth
def ask():
    """A portfolio question, answered by an agent that reads the data itself.

    Every other AI surface in this product is handed its numbers. This one is
    given TOOLS — the five analytics in mcp/tools.yaml, served over MCP
    Toolbox for Databases against the same BigQuery table the analytics screen
    reads. See services/portfolio_agent.py.

    Answers 200 with `available: false` rather than 5xx when the Toolbox is
    down or unconfigured, because "the tools are unavailable" is a real answer
    the UI should render as itself. What it never returns is an answer
    composed without data.
    """
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        return jsonify({"error": "question is required"}), 400
    if len(question) > 500:
        return jsonify({"error": "question is too long"}), 400
    return jsonify(portfolio_agent.ask(question))
