"""
bigquery_executor.py — the analytics engine, at volume.

WHY THIS EXISTS

At 320 cases, analytics_service.py is the right answer: it aggregates in
Python in microseconds and costs nothing. This module is not here because
that is slow. It is here because of how the cross-case layer reads its data.

Every cross-case check in history_service.py — duplicate detection,
cumulative over-billing, a changed bank account, price drift over a vendor's
last six invoices, cadence detection — answers a question about ONE invoice
by reading the vendor's WHOLE history. The datastore serves that with

    self._db.collection("invoice_exceptions").stream()

which is the entire collection, unfiltered, pulled into Python. Every
analytics route and the dashboard do the same. At a few hundred records that
is free. At the volume a mid-size AP function actually runs — hundreds of
thousands of invoices a year — it is a full-collection scan per request, and
it is a scan of exactly the feature that makes this product different from
a per-invoice matcher.

So BigQuery is not an analytics add-on here. Cross-case investigation is the
differentiator, cross-case questions are grouped aggregations over history,
and a document store cannot answer those at volume. This is where the
differentiator has to live.

WHAT THIS MODULE DOES AND DELIBERATELY DOES NOT DO

    BigQuery aggregates.   Python writes the sentence.

The GROUP BY — the part whose cost grows with the table — runs as SQL. What
comes back is one narrow row per vendor, per month, or per bucket. Turning
those rows into the response body then reuses the SAME helpers as the
Firestore path: `_risk_band`, `_why_at_risk`, `_cross_case_headline` are
imported from analytics_service rather than reimplemented in SQL.

That split is not laziness. It is what makes the two engines comparable:
formatting logic that existed twice would drift, and a parity test over
outputs would then be asserting that two copies of a bug agree. Only the
aggregation is duplicated, and tests/test_bigquery_parity.py asserts that
the duplicate produces identical numbers.

COST CONTROL

The table is partitioned on `created_at` and clustered on `vendor_id`. Every
query here carries the same bounded date predicate the Python path applies
in `_filter_cases`, so a window of 365 days prunes to 365 days of partitions
rather than scanning history. `routes/analytics.py` already clamps the window
and caps returned vendor rows; those limits were written for this.

Nothing in this module produces a number that a model touched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from config import config
from services.analytics_service import (
    AGE_BUCKETS,
    CLEAN_MATCH_SCORE,
    CLEAN_TYPE,
    OPEN_STATUSES,
    SLA_BREACH_DAYS,
    _cross_case_headline,
    _risk_band,
    _why_at_risk,
)

# --- Table definition ------------------------------------------------------
# Flat, because every case record already is. Nested fields would buy nothing
# and would make the parity test harder to read.
TABLE_SCHEMA: tuple[tuple[str, str], ...] = (
    ("exception_id", "STRING"),
    ("workspace_id", "STRING"),
    ("invoice_id", "STRING"),
    ("vendor_id", "STRING"),
    ("vendor_name", "STRING"),
    ("purchase_order_id", "STRING"),
    ("business_unit", "STRING"),
    ("currency", "STRING"),
    ("invoice_amount", "FLOAT64"),
    ("po_amount", "FLOAT64"),
    ("status", "STRING"),
    ("exception_type", "STRING"),
    ("match_score", "INT64"),
    ("financial_impact", "FLOAT64"),
    ("risk_level", "STRING"),
    ("assigned_team", "STRING"),
    ("origin", "STRING"),
    ("created_at", "TIMESTAMP"),
    ("updated_at", "TIMESTAMP"),
)

# Partition prunes the date window; cluster serves the per-vendor history
# read that every cross-case check performs.
PARTITION_FIELD = "created_at"
CLUSTER_FIELDS = ("vendor_id", "exception_type")


def table_ref() -> str:
    """Fully-qualified `project.dataset.table`, as SQL needs it."""
    return f"{config.GOOGLE_CLOUD_PROJECT}.{config.BIGQUERY_DATASET}.{config.BIGQUERY_TABLE}"


def create_table_ddl() -> str:
    """DDL for the analytics table. Idempotent, so seeding can re-run."""
    columns = ",\n  ".join(f"{name} {sql_type}" for name, sql_type in TABLE_SCHEMA)
    clustering = ", ".join(CLUSTER_FIELDS)
    return (
        f"CREATE TABLE IF NOT EXISTS `{table_ref()}` (\n  {columns}\n)\n"
        f"PARTITION BY DATE({PARTITION_FIELD})\n"
        f"CLUSTER BY {clustering}"
    )


# --- Record mapping --------------------------------------------------------
_FLOAT_FIELDS = {"invoice_amount", "po_amount", "financial_impact"}
_INT_FIELDS = {"match_score"}
_TIMESTAMP_FIELDS = {"created_at", "updated_at"}


def to_row(case: dict) -> dict:
    """One case record as one BigQuery row.

    Unknown keys are dropped rather than carried: the analytics table is a
    projection for aggregation, not a second copy of Firestore, and a schema
    that grows every time a case gains a field is a schema that breaks loads
    in production.
    """
    row: dict[str, Any] = {}
    for name, _ in TABLE_SCHEMA:
        value = case.get(name)
        if value is None or value == "":
            row[name] = None
        elif name in _FLOAT_FIELDS:
            row[name] = float(value)
        elif name in _INT_FIELDS:
            row[name] = int(value)
        elif name in _TIMESTAMP_FIELDS:
            row[name] = str(value)
        else:
            row[name] = str(value)
    return row


def _client():
    """Imported lazily so the package is only required when the engine is on.

    The Firestore path must keep working — and the test suite must keep
    running offline — on a machine with no BigQuery library and no
    credentials.
    """
    from google.cloud import bigquery  # noqa: PLC0415

    return bigquery.Client(project=config.GOOGLE_CLOUD_PROJECT)


def _cutoff(days: Optional[int]) -> Optional[datetime]:
    if not days:
        return None
    return datetime.now(timezone.utc) - timedelta(days=days)


def _run(sql: str, params: dict) -> list[dict]:
    """Execute with named parameters. Never string-interpolate a value into
    SQL here — `days` arrives from a query string."""
    from google.cloud import bigquery  # noqa: PLC0415

    types = {
        "cutoff": "TIMESTAMP",
        "months": "INT64",
        "sla_days": "INT64",
        "clean_type": "STRING",
        "clean_match_score": "INT64",
    }
    query_params = []
    for key, value in params.items():
        if isinstance(value, (list, tuple, set)):
            query_params.append(
                bigquery.ArrayQueryParameter(key, "STRING", sorted(value)))
        else:
            query_params.append(
                bigquery.ScalarQueryParameter(key, types.get(key, "STRING"), value))

    job = _client().query(
        sql, job_config=bigquery.QueryJobConfig(query_parameters=query_params))
    return [dict(row) for row in job.result()]


# The date predicate every query carries. A NULL created_at stays visible for
# the same reason the Python path keeps it: an undated seed case should not
# silently vanish from a count.
_WINDOW = "(@cutoff IS NULL OR created_at IS NULL OR created_at >= @cutoff)"
_IS_EXCEPTION = "(exception_type IS NOT NULL AND exception_type != @clean_type)"


# ---------------------------------------------------------------------------
# Vendor risk
# ---------------------------------------------------------------------------
VENDOR_RISK_SQL = f"""
WITH scoped AS (
  SELECT * FROM `{{table}}` WHERE {_WINDOW}
),
per_vendor AS (
  SELECT
    COALESCE(vendor_id, vendor_name, 'unknown')                    AS vendor_id,
    ANY_VALUE(COALESCE(vendor_name, 'Unknown vendor'))             AS vendor_name,
    ANY_VALUE(business_unit)                                       AS business_unit,
    COUNT(*)                                                       AS invoice_count,
    COUNTIF({_IS_EXCEPTION})                                       AS exception_count,
    SUM(IF({_IS_EXCEPTION} AND status IN UNNEST(@open_statuses),
           COALESCE(financial_impact, 0), 0))                      AS value_at_risk,
    SUM(COALESCE(invoice_amount, 0))                               AS invoiced_value,
    AVG(CAST(match_score AS FLOAT64))                              AS average_match_score,
    AVG(IF({_IS_EXCEPTION} AND status IN UNNEST(@open_statuses) AND created_at IS NOT NULL,
           TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, SECOND) / 86400.0,
           NULL))                                                  AS average_open_age_days
  FROM scoped
  GROUP BY vendor_id
),
per_type AS (
  SELECT
    COALESCE(vendor_id, vendor_name, 'unknown') AS vendor_id,
    exception_type,
    COUNT(*) AS type_count
  FROM scoped
  WHERE {_IS_EXCEPTION}
  GROUP BY vendor_id, exception_type
)
SELECT
  v.*,
  ARRAY(
    SELECT AS STRUCT t.exception_type, t.type_count
    FROM per_type t
    WHERE t.vendor_id = v.vendor_id
    ORDER BY t.type_count DESC, t.exception_type
  ) AS recurring_types
FROM per_vendor v
WHERE v.invoice_count > 0
ORDER BY v.value_at_risk DESC, SAFE_DIVIDE(v.exception_count, v.invoice_count) DESC
"""


def vendor_risk(days: Optional[int] = 365, limit: int = 25) -> dict:
    """Same contract as analytics_service.vendor_risk, one GROUP BY instead
    of a full read into Python."""
    rows = _run(
        VENDOR_RISK_SQL.format(table=table_ref()),
        {"cutoff": _cutoff(days), "clean_type": CLEAN_TYPE,
         "open_statuses": OPEN_STATUSES},
    )

    out = []
    for row in rows:
        invoices = int(row["invoice_count"])
        exceptions = int(row["exception_count"] or 0)
        exception_rate = exceptions / invoices
        value_at_risk = round(float(row["value_at_risk"] or 0), 2)

        type_counts = {
            entry["exception_type"]: int(entry["type_count"])
            for entry in (row.get("recurring_types") or [])
        }
        top_type = next(iter(type_counts), None)
        avg_age = round(float(row["average_open_age_days"] or 0), 1)
        avg_match = (round(float(row["average_match_score"]), 1)
                     if row["average_match_score"] is not None else None)

        # The same helpers the Firestore path uses, fed the same numbers.
        bucket = {
            "invoice_count": invoices,
            "exception_count": exceptions,
            "value_at_risk": value_at_risk,
            "type_counts": type_counts,
        }
        out.append({
            "vendor_id": row["vendor_id"],
            "vendor_name": row["vendor_name"],
            "business_unit": row["business_unit"],
            "invoice_count": invoices,
            "exception_count": exceptions,
            "exception_rate": round(exception_rate, 4),
            "value_at_risk": value_at_risk,
            "invoiced_value": round(float(row["invoiced_value"] or 0), 2),
            "top_exception_type": top_type,
            "recurring_types": type_counts,
            "average_match_score": avg_match,
            "average_open_age_days": avg_age,
            "risk_band": _risk_band(exception_rate, value_at_risk),
            "why_at_risk": _why_at_risk(bucket, exception_rate, top_type, avg_age),
        })

    return {"window_days": days, "vendor_count": len(out), "vendors": out[:limit]}


# ---------------------------------------------------------------------------
# Monthly trend
# ---------------------------------------------------------------------------
MONTHLY_TREND_SQL = f"""
SELECT
  FORMAT_TIMESTAMP('%Y-%m', created_at)                         AS month,
  COUNT(*)                                                      AS invoices,
  COUNTIF({_IS_EXCEPTION})                                      AS exceptions,
  COUNTIF(NOT ({_IS_EXCEPTION}))                                AS clean,
  SUM(IF({_IS_EXCEPTION}, COALESCE(financial_impact, 0), 0))    AS value_at_risk
FROM `{{table}}`
WHERE {_WINDOW} AND created_at IS NOT NULL
GROUP BY month
ORDER BY month
"""


def monthly_trend(months: int = 12) -> dict:
    rows = _run(
        MONTHLY_TREND_SQL.format(table=table_ref()),
        {"cutoff": _cutoff(months * 31), "clean_type": CLEAN_TYPE},
    )
    points = [{
        "month": row["month"],
        "invoices": int(row["invoices"]),
        "exceptions": int(row["exceptions"] or 0),
        "clean": int(row["clean"] or 0),
        "exception_rate": (round(int(row["exceptions"] or 0) / int(row["invoices"]), 4)
                           if row["invoices"] else 0),
        "value_at_risk": round(float(row["value_at_risk"] or 0), 2),
    } for row in rows]
    return {"months": months, "points": points[-months:]}


# ---------------------------------------------------------------------------
# Ageing / SLA
# ---------------------------------------------------------------------------
AGEING_SQL = f"""
WITH open_cases AS (
  SELECT
    COALESCE(financial_impact, 0) AS financial_impact,
    TIMESTAMP_DIFF(CURRENT_TIMESTAMP(), created_at, SECOND) / 86400.0 AS age_days
  FROM `{{table}}`
  WHERE {_WINDOW}
    AND {_IS_EXCEPTION}
    AND status IN UNNEST(@open_statuses)
    AND created_at IS NOT NULL
)
SELECT
  COUNT(*)                                            AS open_exceptions,
  COUNTIF(age_days > @sla_days)                       AS breaching_sla,
  COALESCE(MAX(age_days), 0)                          AS oldest_open_days,
  ARRAY_AGG(STRUCT(age_days, financial_impact))       AS rows_out
FROM open_cases
"""


def ageing(days: Optional[int] = 365) -> dict:
    rows = _run(
        AGEING_SQL.format(table=table_ref()),
        {"cutoff": _cutoff(days), "clean_type": CLEAN_TYPE,
         "open_statuses": OPEN_STATUSES, "sla_days": SLA_BREACH_DAYS},
    )
    row = rows[0] if rows else {}

    # Bucketing runs here rather than as a CASE expression so the boundaries
    # live in exactly one place — AGE_BUCKETS — for both engines. The rows
    # returned are already restricted to open exceptions in the window.
    buckets = {label: {"count": 0, "value_at_risk": 0.0} for label, _, _ in AGE_BUCKETS}
    for entry in (row.get("rows_out") or []):
        age = float(entry["age_days"])
        impact = float(entry["financial_impact"] or 0)
        for label, low, high in AGE_BUCKETS:
            if age >= low and (high is None or age <= high):
                buckets[label]["count"] += 1
                buckets[label]["value_at_risk"] += impact
                break

    return {
        "sla_days": SLA_BREACH_DAYS,
        "open_exceptions": int(row.get("open_exceptions") or 0),
        "breaching_sla": int(row.get("breaching_sla") or 0),
        "oldest_open_days": round(float(row.get("oldest_open_days") or 0), 1),
        "buckets": [
            {"label": label, "count": buckets[label]["count"],
             "value_at_risk": round(buckets[label]["value_at_risk"], 2)}
            for label, _, _ in AGE_BUCKETS
        ],
    }


# ---------------------------------------------------------------------------
# Portfolio headline
# ---------------------------------------------------------------------------
PORTFOLIO_SUMMARY_SQL = f"""
WITH scoped AS (
  SELECT * FROM `{{table}}` WHERE {_WINDOW}
),
totals AS (
  SELECT
    COUNT(*)                                      AS invoice_count,
    COUNTIF({_IS_EXCEPTION})                      AS exception_count,
    COUNTIF({_IS_EXCEPTION} AND status IN UNNEST(@open_statuses)) AS open_exception_count,
    SUM(COALESCE(invoice_amount, 0))              AS invoiced_value,
    SUM(IF({_IS_EXCEPTION} AND status IN UNNEST(@open_statuses),
           COALESCE(financial_impact, 0), 0))     AS value_at_risk
  FROM scoped
),
by_type AS (
  SELECT
    exception_type,
    COUNT(*)                              AS type_count,
    SUM(COALESCE(financial_impact, 0))    AS type_value
  FROM scoped
  WHERE {_IS_EXCEPTION}
  GROUP BY exception_type
)
SELECT
  t.*,
  ARRAY(SELECT AS STRUCT * FROM by_type ORDER BY type_count DESC, exception_type) AS types
FROM totals t
"""


def portfolio_summary(days: Optional[int] = 365) -> dict:
    rows = _run(
        PORTFOLIO_SUMMARY_SQL.format(table=table_ref()),
        {"cutoff": _cutoff(days), "clean_type": CLEAN_TYPE,
         "open_statuses": OPEN_STATUSES},
    )
    row = rows[0] if rows else {}

    total = int(row.get("invoice_count") or 0)
    exceptions = int(row.get("exception_count") or 0)
    invoiced = round(float(row.get("invoiced_value") or 0), 2)
    at_risk = round(float(row.get("value_at_risk") or 0), 2)
    types = row.get("types") or []

    return {
        "window_days": days,
        "invoice_count": total,
        "exception_count": exceptions,
        "clean_count": total - exceptions,
        "exception_rate": round(exceptions / total, 4) if total else 0,
        "clean_rate": round((total - exceptions) / total, 4) if total else 0,
        "open_exception_count": int(row.get("open_exception_count") or 0),
        "invoiced_value": invoiced,
        "value_at_risk": at_risk,
        "value_at_risk_share": round(at_risk / invoiced, 4) if invoiced else 0,
        "exception_type_counts": {
            t["exception_type"]: int(t["type_count"]) for t in types},
        "exception_type_value": {
            t["exception_type"]: round(float(t["type_value"] or 0), 2) for t in types},
    }


# ---------------------------------------------------------------------------
# The claim, measured
# ---------------------------------------------------------------------------
# The set of cross-case types is imported from schemas.py by the caller and
# passed in as a parameter rather than hard-coded here, for the same reason
# analytics_service.py imports it: this figure must not be able to drift away
# from what the matcher actually classifies as cross-case.
CROSS_CASE_SQL = f"""
WITH scoped AS (
  SELECT * FROM `{{table}}` WHERE {_WINDOW}
),
exceptions AS (
  SELECT *, exception_type IN UNNEST(@cross_types) AS is_cross
  FROM scoped WHERE {_IS_EXCEPTION}
)
SELECT
  (SELECT COUNT(*) FROM scoped)                                   AS invoice_count,
  COUNT(*)                                                        AS exception_count,
  COUNTIF(NOT is_cross)                                           AS single_count,
  SUM(IF(NOT is_cross, COALESCE(financial_impact, 0), 0))         AS single_value,
  COUNTIF(is_cross)                                               AS cross_count,
  SUM(IF(is_cross, COALESCE(financial_impact, 0), 0))             AS cross_value,
  COUNTIF(is_cross AND match_score >= @clean_match_score)         AS cleared_count,
  SUM(IF(is_cross AND match_score >= @clean_match_score,
         COALESCE(financial_impact, 0), 0))                       AS cleared_value,
  ARRAY(
    SELECT AS STRUCT exception_type,
           COUNT(*)                           AS type_count,
           SUM(COALESCE(financial_impact, 0)) AS type_value
    FROM exceptions WHERE is_cross
    GROUP BY exception_type
    ORDER BY type_value DESC, exception_type
  )                                                               AS cross_by_type
FROM exceptions
"""


def cross_case_value(days: Optional[int] = 365) -> dict:
    from schemas import CROSS_CASE_TYPE_VALUES  # noqa: PLC0415

    rows = _run(
        CROSS_CASE_SQL.format(table=table_ref()),
        {"cutoff": _cutoff(days), "clean_type": CLEAN_TYPE,
         "cross_types": CROSS_CASE_TYPE_VALUES,
         "clean_match_score": CLEAN_MATCH_SCORE},
    )
    row = rows[0] if rows else {}

    exception_count = int(row.get("exception_count") or 0)
    cross_count = int(row.get("cross_count") or 0)
    cross_value = round(float(row.get("cross_value") or 0), 2)
    cleared_count = int(row.get("cleared_count") or 0)

    # `_cross_case_headline` counts the lists it is handed; it never reads
    # their contents. Placeholders of the right length give the identical
    # sentence without shipping every row back from BigQuery to produce it.
    headline = _cross_case_headline(
        [None] * cross_count, [None] * cleared_count, cross_value)

    return {
        "window_days": days,
        "invoice_count": int(row.get("invoice_count") or 0),
        "exception_count": exception_count,
        "single_invoice": {
            "count": int(row.get("single_count") or 0),
            "value": round(float(row.get("single_value") or 0), 2),
        },
        "cross_case": {
            "count": cross_count,
            "value": cross_value,
            "share_of_exceptions": (round(cross_count / exception_count, 4)
                                    if exception_count else 0),
            "by_type": {
                t["exception_type"]: {
                    "count": int(t["type_count"]),
                    "value": round(float(t["type_value"] or 0), 2),
                }
                for t in (row.get("cross_by_type") or [])
            },
        },
        "would_have_cleared": {
            "count": cleared_count,
            "value": round(float(row.get("cleared_value") or 0), 2),
            "threshold_match_score": CLEAN_MATCH_SCORE,
        },
        "headline": headline,
        "basis": (
            "Partitioned on exception type. A cross-case type is one that cannot be reached "
            "from a single case's own documents — it needs a query across the rest of the "
            "workspace. Value is the financial impact matching_service.py computed for each "
            "case, not a claim of loss prevented."
        ),
    }
