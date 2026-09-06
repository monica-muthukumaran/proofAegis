"""
routes/dashboard.py — Document 4, Day 17: KPI cards + one exception-type
breakdown, computed only from data that's genuinely on hand (no invented
metrics).
"""
from __future__ import annotations

from collections import Counter, defaultdict

from flask import Blueprint, jsonify

from auth import require_auth
from datastore import get_datastore
from services import case_service

bp = Blueprint("dashboard", __name__, url_prefix="/api/dashboard")


@bp.get("/summary")
@require_auth
def summary():
    ds = get_datastore()
    exceptions = ds.list_exceptions()

    open_statuses = {"exception_detected", "assigned", "awaiting_procurement",
                      "awaiting_receiving", "awaiting_vendor"}
    open_exceptions = [e for e in exceptions if e["status"] in open_statuses]
    cleared = [e for e in exceptions if e.get("exception_type") == "no_exception"]

    match_scores = []
    value_on_hold = 0.0
    type_counter = Counter()
    # Financial impact per exception type, so the dashboard chart can be scaled
    # by money rather than by count. Three exceptions of three types is a
    # meaningless bar chart; "₹1.8L vs ₹50k vs ₹25k" is a priority order.
    type_value = defaultdict(float)

    for exc in exceptions:
        # summarize_exception returns stored outcomes untouched and only
        # computes for a case that has none. Recomputing a match for every
        # record on every dashboard load was fine at three cases and is not at
        # several hundred.
        summary_row = case_service.summarize_exception(exc)
        exception_type = summary_row.get("exception_type")
        if exception_type is None:
            continue

        if summary_row.get("match_score") is not None:
            match_scores.append(summary_row["match_score"])

        # Clean invoices are cases too, and they belong in the denominator of
        # the average match score — but they are not an "exception type" and
        # must not appear in the breakdown chart.
        if exception_type == "no_exception":
            continue

        impact = float(summary_row.get("financial_impact") or 0)
        type_counter[exception_type] += 1
        type_value[exception_type] += impact
        if exc["status"] in open_statuses:
            value_on_hold += impact

    awaiting_vendor_count = sum(1 for e in exceptions if e["status"] == "awaiting_vendor")

    return jsonify({
        "invoice_count": len(exceptions),
        "clean_count": len(cleared),
        "open_exceptions_count": len(open_exceptions),
        "value_on_hold": round(value_on_hold, 2),
        "average_match_score": round(sum(match_scores) / len(match_scores), 1) if match_scores else 0,
        "awaiting_vendor_count": awaiting_vendor_count,
        "exception_type_breakdown": dict(type_counter),
        "exception_type_value": {k: round(v, 2) for k, v in type_value.items()},
    })
