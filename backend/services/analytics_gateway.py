"""
analytics_gateway.py — which engine answers an analytics question.

This exists so `routes/analytics.py` does not have to know. The routes ask
for a portfolio summary; whether that is a Python aggregation over a
collection read or a BigQuery GROUP BY is a deployment decision, set by
`ANALYTICS_ENGINE`.

THE POINT OF THE SEAM

The Firestore path needs the cases in memory, so the caller must read them
first:

    cases = get_datastore().list_exceptions()      # the whole collection
    analytics_service.portfolio_summary(cases, days)

The BigQuery path must NOT do that. If this module fetched the cases and
then handed them to BigQuery, it would have performed the full-collection
scan the SQL exists to avoid, and the engine switch would be theatre. So the
read happens INSIDE the Firestore branch and nowhere else — on the BigQuery
path no case is ever loaded into the process.

That is also why these functions take `days`/`months` rather than `cases`.
The signature difference is the honest one: the engine fetches its own data.

FALLBACK

If BigQuery is selected but unreachable — missing library, missing table,
no credentials — the request FAILS. It does not quietly fall back to
Firestore and serve numbers computed a different way than the response
claims, for the same reason `USE_MOCK_DATA` never activates on an error:
a wrong answer delivered confidently is worse than an error message.
"""
from __future__ import annotations

from typing import Optional

from config import config
from datastore import get_datastore
from services import analytics_service

BIGQUERY = "bigquery"
FIRESTORE = "firestore"


def active_engine() -> str:
    """Whichever engine is configured. Anything unrecognised means Firestore —
    a typo in an environment variable should not take analytics down."""
    return BIGQUERY if config.ANALYTICS_ENGINE == BIGQUERY else FIRESTORE


def using_bigquery() -> bool:
    return active_engine() == BIGQUERY


def _executor():
    from services import bigquery_executor  # noqa: PLC0415

    return bigquery_executor


def _cases() -> list[dict]:
    """The full-collection read. Reached only on the Firestore path."""
    return get_datastore().list_exceptions()


def portfolio_summary(days: Optional[int] = 365) -> dict:
    if using_bigquery():
        return _executor().portfolio_summary(days)
    return analytics_service.portfolio_summary(_cases(), days)


def vendor_risk(days: Optional[int] = 365, limit: int = 25) -> dict:
    if using_bigquery():
        return _executor().vendor_risk(days, limit)
    return analytics_service.vendor_risk(_cases(), days, limit)


def monthly_trend(months: int = 12) -> dict:
    if using_bigquery():
        return _executor().monthly_trend(months)
    return analytics_service.monthly_trend(_cases(), months)


def ageing(days: Optional[int] = 365) -> dict:
    if using_bigquery():
        return _executor().ageing(days)
    return analytics_service.ageing(_cases(), days)


def cross_case_value(days: Optional[int] = 365) -> dict:
    if using_bigquery():
        return _executor().cross_case_value(days)
    return analytics_service.cross_case_value(_cases(), days)


# The five questions this gateway can answer, named once so the parity test
# and the MCP tool manifest cannot fall out of step with the module.
ANALYTIC_NAMES = (
    "portfolio_summary",
    "vendor_risk",
    "monthly_trend",
    "ageing",
    "cross_case_value",
)


def engine_status() -> dict:
    """What `/api/settings` reports, so the UI can say which engine served a
    figure rather than leaving a viewer to assume."""
    status = {
        "analytics_engine": active_engine(),
        "bigquery_configured": False,
        "bigquery_table": None,
    }
    if using_bigquery():
        try:
            status["bigquery_table"] = _executor().table_ref()
            status["bigquery_configured"] = bool(config.GOOGLE_CLOUD_PROJECT)
        except ImportError:
            status["bigquery_configured"] = False
    return status
