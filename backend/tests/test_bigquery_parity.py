"""
test_bigquery_parity.py — the two engines must agree, or one of them is wrong.

There are now two implementations of the same five aggregations: Python over
a collection read, and SQL over a partitioned table. Two implementations of
one calculation is exactly the situation the eval harness caught us in once
already — `services/matching_service.py` and `services/history_service.py`
each had their own vendor-identity rule, they disagreed, and a duplicate
invoice went unreported because of it.

So the duplication is allowed here only because it is asserted. Three layers:

1. OFFLINE, ALWAYS RUNS — the contract. Both engines expose the same five
   analytics; the row mapping round-trips every schema field; the formatting
   helpers are IMPORTED by the BigQuery path rather than reimplemented, which
   is what keeps a parity assertion meaningful rather than an assertion that
   two copies of a bug agree.

2. OFFLINE, ALWAYS RUNS — the SQL itself, against a real SQL engine. Every
   query is executed by DuckDB over the same fixture population, and the
   aggregate numbers are compared to the Python path's. This is not the
   BigQuery dialect, so a small translation shim covers the handful of
   functions that differ by name; what it proves is that the SQL's LOGIC —
   its joins, its predicates, its GROUP BY, its treatment of NULLs — produces
   the same numbers as the Python. That is where a real bug would live.

3. LIVE, SKIPPED WITHOUT CREDENTIALS — the same comparison against actual
   BigQuery, which additionally proves the dialect and the schema are right.
   Run it with ANALYTICS_ENGINE=bigquery and a loaded table.

Layer 2 is the one that earns its place in CI: it runs on a laptop with no
GCP project and still fails if somebody breaks a predicate.
"""
from __future__ import annotations

import os
import random
from datetime import datetime, timedelta, timezone

import pytest

from config import config
from services import analytics_gateway, analytics_service
from services import bigquery_executor as bq

duckdb = pytest.importorskip(
    "duckdb", reason="duckdb backs the offline SQL parity test")


# ---------------------------------------------------------------------------
# A population with the awkward cases in it
# ---------------------------------------------------------------------------
def _population(n: int = 240, seed: int = 20260906) -> list[dict]:
    """Seeded, and deliberately includes the records that break naive SQL:
    a NULL created_at, a NULL financial_impact, a vendor with no id, a case
    with no match score, and clean invoices so a rate has a denominator."""
    rng = random.Random(seed)
    vendors = [(f"VEN-{i:04d}", f"Vendor {i}") for i in range(1, 13)]
    types = [
        "no_exception", "duplicate_invoice", "price_variance",
        "quantity_variance", "po_over_billed", "payment_details_changed",
        "vendor_price_drift", "missing_goods_receipt",
    ]
    statuses = [
        "exception_detected", "assigned", "awaiting_procurement",
        "resolved", "approved_with_exception", "awaiting_vendor",
    ]
    now = datetime.now(timezone.utc)

    cases = []
    for i in range(n):
        vendor_id, vendor_name = rng.choice(vendors)
        exception_type = rng.choice(types)
        created = now - timedelta(days=rng.randint(0, 400),
                                  hours=rng.randint(0, 23))
        case = {
            "exception_id": f"EXC-{i:05d}",
            "workspace_id": "test-workspace",
            "invoice_id": f"INV-{i:05d}",
            "vendor_id": vendor_id,
            "vendor_name": vendor_name,
            "purchase_order_id": f"PO-{i:05d}",
            "business_unit": rng.choice(["Logistics", "Plant", "IT"]),
            "currency": "INR",
            "invoice_amount": round(rng.uniform(5_000, 900_000), 2),
            "po_amount": round(rng.uniform(5_000, 900_000), 2),
            "status": rng.choice(statuses),
            "exception_type": exception_type,
            "match_score": rng.choice([100, 100, 92, 74, 48]),
            "financial_impact": round(rng.uniform(0, 250_000), 2),
            "risk_level": rng.choice(["low", "medium", "high"]),
            "assigned_team": "AP",
            "origin": "test",
            "created_at": created.isoformat(),
            "updated_at": created.isoformat(),
        }
        cases.append(case)

    # The awkward ones, appended so their indices are stable.
    cases[3]["created_at"] = None                 # undated: stays counted
    cases[7]["financial_impact"] = None           # NULL money: treated as 0
    cases[11]["vendor_id"] = None                 # falls back to vendor_name
    cases[13]["match_score"] = None               # excluded from the average
    cases[17]["exception_type"] = None            # not an exception at all
    return cases


@pytest.fixture(scope="module")
def population():
    return _population()


# ---------------------------------------------------------------------------
# DuckDB stand-in for BigQuery
# ---------------------------------------------------------------------------
_DIALECT = (
    # (BigQuery, DuckDB) — only the functions whose NAMES differ. No predicate,
    # no join and no grouping is rewritten, because those are what is on trial.
    ("CURRENT_TIMESTAMP()", "CURRENT_TIMESTAMP"),
    ("FORMAT_TIMESTAMP('%Y-%m', created_at)", "strftime(created_at, '%Y-%m')"),
    ("TIMESTAMP_DIFF(CURRENT_TIMESTAMP, created_at, SECOND)",
     "date_diff('second', created_at, CURRENT_TIMESTAMP)"),
    ("SAFE_DIVIDE(v.exception_count, v.invoice_count)",
     "TRY_CAST(v.exception_count AS DOUBLE) / NULLIF(v.invoice_count, 0)"),
    ("IN UNNEST(@open_statuses)", "IN (SELECT * FROM open_statuses)"),
    ("IN UNNEST(@cross_types)", "IN (SELECT * FROM cross_types)"),
    ("CAST(match_score AS FLOAT64)", "CAST(match_score AS DOUBLE)"),
    # BigQuery resolves a GROUP BY against SELECT aliases; DuckDB binds it to
    # the base column and rejects the query. GROUP BY ALL groups by exactly
    # the non-aggregated projections, which is the same set of keys.
    ("GROUP BY vendor_id, exception_type", "GROUP BY ALL"),
    ("GROUP BY vendor_id", "GROUP BY ALL"),
)


def _drop_array_projection(sql: str, tail: str) -> str:
    """Cut a BigQuery `ARRAY(SELECT AS STRUCT ...)` projection.

    DuckDB has no equivalent, and the nested array is not where a parity bug
    would hide — it is a second GROUP BY whose counts are compared directly
    in `test_recurring_types_agree`. What must be identical, and is compared
    here, are the scalar aggregates around it.

    Asserts it actually cut something, so a rewritten query cannot silently
    turn this into a no-op that tests nothing.
    """
    head, marker, _ = sql.partition("  ARRAY(")
    assert marker, "expected an ARRAY( projection to cut"
    return head.rstrip().rstrip(",") + chr(10) + tail


def _translate(sql: str, table: str) -> str:
    sql = sql.format(table=table).replace(f"`{table}`", table).replace("`", "")
    for bigquery_form, duckdb_form in _DIALECT:
        sql = sql.replace(bigquery_form, duckdb_form)
    return sql


@pytest.fixture(scope="module")
def con(population):
    """A DuckDB table holding the same rows the loader would send BigQuery —
    built through `bq.to_row`, so the mapping is on trial too."""
    connection = duckdb.connect(":memory:")
    # UTC, and TIMESTAMPTZ columns. A naive TIMESTAMP silently drops the
    # +00:00 offset the fixtures carry, which shifts every computed age by
    # the runner's local offset — a parity failure that is really a test bug,
    # and one that would pass in London and fail in Chennai.
    connection.execute("SET TimeZone='UTC'")
    _DUCK_TYPES = {"FLOAT64": "DOUBLE", "INT64": "BIGINT", "TIMESTAMP": "TIMESTAMPTZ"}
    columns = ", ".join(
        f"{name} {_DUCK_TYPES.get(t, 'VARCHAR')}" for name, t in bq.TABLE_SCHEMA)
    connection.execute(f"CREATE TABLE cases ({columns})")

    names = [name for name, _ in bq.TABLE_SCHEMA]
    placeholders = ", ".join("?" for _ in names)
    for case in population:
        row = bq.to_row(case)
        connection.execute(
            f"INSERT INTO cases VALUES ({placeholders})",
            [row[name] for name in names])

    connection.execute(
        "CREATE TABLE open_statuses AS SELECT * FROM (VALUES "
        + ", ".join(f"('{s}')" for s in sorted(analytics_service.OPEN_STATUSES))
        + ") t(status)")
    from schemas import CROSS_CASE_TYPE_VALUES
    connection.execute(
        "CREATE TABLE cross_types AS SELECT * FROM (VALUES "
        + ", ".join(f"('{t}')" for t in sorted(CROSS_CASE_TYPE_VALUES))
        + ") t(exception_type)")
    return connection


def _query(con, sql: str, cutoff_days: int | None):
    cutoff = None
    if cutoff_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=cutoff_days)
    translated = _translate(sql, "cases")
    translated = translated.replace(
        "@cutoff", "NULL" if cutoff is None else f"TIMESTAMPTZ '{cutoff.isoformat()}'")
    translated = translated.replace("@clean_type", f"'{analytics_service.CLEAN_TYPE}'")
    translated = translated.replace("@sla_days", str(analytics_service.SLA_BREACH_DAYS))
    translated = translated.replace(
        "@clean_match_score", str(analytics_service.CLEAN_MATCH_SCORE))
    # NULL: the fixture population is one workspace, and the comparison is
    # against the Python path reading the same rows unscoped. The predicate
    # itself is on trial in test_the_workspace_predicate_scopes_every_query.
    translated = translated.replace("@workspace_id", "NULL")
    cursor = con.execute(translated)
    names = [d[0] for d in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


# ---------------------------------------------------------------------------
# 1. Contract — always runs, no SQL engine needed
# ---------------------------------------------------------------------------
def test_both_engines_expose_the_same_analytics():
    for name in analytics_gateway.ANALYTIC_NAMES:
        assert hasattr(analytics_service, name), f"analytics_service lacks {name}"
        assert hasattr(bq, name), f"bigquery_executor lacks {name}"
        assert hasattr(analytics_gateway, name), f"gateway lacks {name}"


def test_bigquery_path_imports_the_formatting_helpers_rather_than_copying_them():
    """The parity assertions below are only worth something because the
    sentence-building is shared. If somebody reimplements `_why_at_risk` in
    the BigQuery module, the outputs can drift while every numeric assertion
    still passes — so assert the sharing itself, by identity."""
    assert bq._risk_band is analytics_service._risk_band
    assert bq._why_at_risk is analytics_service._why_at_risk
    assert bq._cross_case_headline is analytics_service._cross_case_headline
    assert bq.AGE_BUCKETS is analytics_service.AGE_BUCKETS
    assert bq.OPEN_STATUSES is analytics_service.OPEN_STATUSES


def test_row_mapping_round_trips_every_schema_field(population):
    for case in population[:40]:
        row = bq.to_row(case)
        assert set(row) == {name for name, _ in bq.TABLE_SCHEMA}
        for name, sql_type in bq.TABLE_SCHEMA:
            if row[name] is None:
                continue
            if sql_type == "FLOAT64":
                assert isinstance(row[name], float)
            elif sql_type == "INT64":
                assert isinstance(row[name], int)
            else:
                assert isinstance(row[name], str)


def test_unknown_fields_are_dropped_rather_than_carried():
    row = bq.to_row({"exception_id": "EXC-1", "some_new_field": "x"})
    assert "some_new_field" not in row
    assert row["exception_id"] == "EXC-1"


def test_the_workspace_predicate_scopes_every_query():
    """The tenancy control on the SQL path, asserted per query.

    A workspace filter present in four of five queries is not a weaker
    control than one present in five — it is a leak with four places that
    look like it was handled. So this asserts the predicate on each SQL
    constant by name rather than trusting the shared `_SCOPE` string to have
    been used everywhere.
    """
    queries = {
        "vendor_risk": bq.VENDOR_RISK_SQL,
        "monthly_trend": bq.MONTHLY_TREND_SQL,
        "ageing": bq.AGEING_SQL,
        "portfolio_summary": bq.PORTFOLIO_SUMMARY_SQL,
        "cross_case_value": bq.CROSS_CASE_SQL,
    }
    for name, sql in queries.items():
        assert "@workspace_id" in sql, f"{name} has no workspace predicate"
        assert "workspace_id = @workspace_id" in sql, f"{name} does not compare it"


def test_the_workspace_predicate_is_bound_as_a_parameter_not_interpolated(monkeypatch):
    """A workspace id arrives from a verified token, but the rule is the same
    one that governs `days`: nothing reaches this SQL by string substitution."""
    captured = {}
    monkeypatch.setattr(bq, "_run", lambda sql, params: captured.update(params) or [])

    bq.portfolio_summary(365, workspace_id="user:uid-alice")
    assert captured["workspace_id"] == "user:uid-alice"

    for fn, args in ((bq.vendor_risk, (365, 10)), (bq.monthly_trend, (12,)),
                     (bq.ageing, (365,)), (bq.cross_case_value, (365,))):
        captured.clear()
        fn(*args, workspace_id="user:uid-bob")
        assert captured["workspace_id"] == "user:uid-bob", fn.__name__


def test_the_workspace_filter_actually_filters(con):
    """Executed, not just inspected. The predicate is run against DuckDB with
    a real value to prove it excludes rows — a predicate that is present and
    always true would satisfy the two tests above."""
    con.execute("CREATE TABLE IF NOT EXISTS scoped_probe AS SELECT * FROM cases LIMIT 0")
    all_rows = con.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
    mine = con.execute(
        f"SELECT COUNT(*) FROM cases WHERE {bq._WORKSPACE}".replace(
            "@workspace_id", "'test-workspace'")).fetchone()[0]
    someone_else = con.execute(
        f"SELECT COUNT(*) FROM cases WHERE {bq._WORKSPACE}".replace(
            "@workspace_id", "'user:uid-alice'")).fetchone()[0]
    unscoped = con.execute(
        f"SELECT COUNT(*) FROM cases WHERE {bq._WORKSPACE}".replace(
            "@workspace_id", "NULL")).fetchone()[0]

    assert all_rows > 0
    assert mine == all_rows           # the fixture population's own workspace
    assert someone_else == 0          # and nobody else sees any of it
    assert unscoped == all_rows       # NULL means every workspace, for loaders


def test_table_is_partitioned_and_clustered():
    """The cost control is the reason this is defensible at volume. An
    unpartitioned table scans all history for a 30-day question."""
    ddl = bq.create_table_ddl()
    assert "PARTITION BY DATE(created_at)" in ddl
    assert "CLUSTER BY vendor_id, exception_type" in ddl


def test_every_query_carries_the_date_predicate():
    """A query without the window predicate is a full-table scan wearing the
    costume of a bounded one."""
    for sql in (bq.VENDOR_RISK_SQL, bq.MONTHLY_TREND_SQL, bq.AGEING_SQL,
                bq.PORTFOLIO_SUMMARY_SQL, bq.CROSS_CASE_SQL):
        assert "@cutoff" in sql


def test_gateway_does_not_read_the_collection_on_the_bigquery_path(monkeypatch):
    """The whole point of the seam. If the gateway fetched cases and then
    called BigQuery, it would have done the scan the SQL exists to avoid."""
    called = []
    monkeypatch.setattr(analytics_gateway, "_cases",
                        lambda workspace_id=None: called.append(1) or [])
    monkeypatch.setattr(config, "ANALYTICS_ENGINE", "bigquery")
    monkeypatch.setattr(analytics_gateway, "_executor",
                        lambda: _StubExecutor())

    analytics_gateway.portfolio_summary(365, workspace_id="ws-1")
    analytics_gateway.vendor_risk(365, 10, workspace_id="ws-1")
    analytics_gateway.cross_case_value(365, workspace_id="ws-1")
    assert called == [], "the BigQuery path read the case collection"


class _StubExecutor:
    """Signatures match the real executor's, workspace argument included —
    the gateway must pass the workspace down on the BigQuery path too, and a
    stub that shrugged it off would hide the day it stops."""

    def portfolio_summary(self, days, workspace_id=None):
        return {}

    def vendor_risk(self, days, limit, workspace_id=None):
        return {}

    def cross_case_value(self, days, workspace_id=None):
        return {}


def test_gateway_falls_back_to_firestore_for_an_unrecognised_engine(monkeypatch):
    monkeypatch.setattr(config, "ANALYTICS_ENGINE", "postgres-probably")
    assert analytics_gateway.active_engine() == "firestore"


# ---------------------------------------------------------------------------
# 2. SQL logic parity — always runs, DuckDB executes the real queries
# ---------------------------------------------------------------------------
WINDOWS = [30, 90, 365, None]


@pytest.mark.parametrize("days", WINDOWS)
def test_portfolio_summary_agrees(con, population, days):
    expected = analytics_service.portfolio_summary(population, days)
    sql = _drop_array_projection(bq.PORTFOLIO_SUMMARY_SQL, "FROM totals t")
    row = _query(con, sql, days)[0]

    assert int(row["invoice_count"]) == expected["invoice_count"]
    assert int(row["exception_count"] or 0) == expected["exception_count"]
    assert int(row["open_exception_count"] or 0) == expected["open_exception_count"]
    assert round(float(row["invoiced_value"] or 0), 2) == expected["invoiced_value"]
    assert round(float(row["value_at_risk"] or 0), 2) == expected["value_at_risk"]


@pytest.mark.parametrize("days", WINDOWS)
def test_vendor_risk_agrees(con, population, days):
    expected = analytics_service.vendor_risk(population, days, limit=1000)
    sql = _drop_array_projection(
        bq.VENDOR_RISK_SQL, "FROM per_vendor v WHERE v.invoice_count > 0")
    rows = {r["vendor_id"]: r for r in _query(con, sql, days)}
    assert len(rows) == expected["vendor_count"]

    for vendor in expected["vendors"]:
        row = rows[vendor["vendor_id"]]
        assert int(row["invoice_count"]) == vendor["invoice_count"]
        assert int(row["exception_count"] or 0) == vendor["exception_count"]
        assert round(float(row["value_at_risk"] or 0), 2) == vendor["value_at_risk"]
        assert round(float(row["invoiced_value"] or 0), 2) == vendor["invoiced_value"]
        if vendor["average_match_score"] is not None:
            assert round(float(row["average_match_score"]), 1) == vendor["average_match_score"]


@pytest.mark.parametrize("months", [3, 12])
def test_monthly_trend_agrees(con, population, months):
    expected = analytics_service.monthly_trend(population, months)
    rows = {r["month"]: r for r in _query(con, bq.MONTHLY_TREND_SQL, months * 31)}

    for point in expected["points"]:
        row = rows[point["month"]]
        assert int(row["invoices"]) == point["invoices"]
        assert int(row["exceptions"] or 0) == point["exceptions"]
        assert int(row["clean"] or 0) == point["clean"]
        assert round(float(row["value_at_risk"] or 0), 2) == point["value_at_risk"]


@pytest.mark.parametrize("days", WINDOWS)
def test_ageing_agrees(con, population, days):
    expected = analytics_service.ageing(population, days)
    # DuckDB has no ARRAY_AGG(STRUCT(...)) in the BigQuery shape, so the
    # bucketing input is selected directly. The bucket boundaries themselves
    # are shared code (AGE_BUCKETS), asserted above.
    sql = bq.AGEING_SQL.split("SELECT\n  COUNT(*)")[0] + "SELECT * FROM open_cases"
    rows = _query(con, sql, days)

    assert len(rows) == expected["open_exceptions"]
    if rows:
        assert round(max(float(r["age_days"]) for r in rows), 1) == \
            expected["oldest_open_days"]
        breached = sum(1 for r in rows
                       if float(r["age_days"]) > analytics_service.SLA_BREACH_DAYS)
        assert breached == expected["breaching_sla"]


@pytest.mark.parametrize("days", WINDOWS)
def test_cross_case_value_agrees(con, population, days):
    expected = analytics_service.cross_case_value(population, days)
    sql = bq.CROSS_CASE_SQL.split("  ARRAY(")[0].rstrip().rstrip(",") + "\nFROM exceptions"
    row = _query(con, sql, days)[0]

    assert int(row["invoice_count"]) == expected["invoice_count"]
    assert int(row["exception_count"] or 0) == expected["exception_count"]
    assert int(row["cross_count"] or 0) == expected["cross_case"]["count"]
    assert round(float(row["cross_value"] or 0), 2) == expected["cross_case"]["value"]
    assert int(row["single_count"] or 0) == expected["single_invoice"]["count"]
    assert round(float(row["single_value"] or 0), 2) == expected["single_invoice"]["value"]
    # The headline claim of the entire product, computed twice, in two
    # languages, over the same population.
    assert int(row["cleared_count"] or 0) == expected["would_have_cleared"]["count"]
    assert round(float(row["cleared_value"] or 0), 2) == \
        expected["would_have_cleared"]["value"]


# ---------------------------------------------------------------------------
# 3. Live BigQuery — skipped without credentials and a loaded table
# ---------------------------------------------------------------------------
_LIVE = os.environ.get("BIGQUERY_PARITY_TEST") == "1"


@pytest.mark.skipif(not _LIVE, reason="set BIGQUERY_PARITY_TEST=1 with a loaded table")
def test_live_bigquery_matches_python_over_the_same_table():
    """The dialect and schema check the DuckDB layer cannot make.

    Reads the loaded table back row by row, runs the Python engine over those
    exact rows, and compares. Any difference is BigQuery's SQL disagreeing
    with the Python — which is the failure this whole file exists to catch.
    """
    from google.cloud import bigquery

    client = bigquery.Client(project=config.GOOGLE_CLOUD_PROJECT)
    cases = [dict(r) for r in client.query(
        f"SELECT * FROM `{bq.table_ref()}`").result()]
    for case in cases:
        for key in ("created_at", "updated_at"):
            if case.get(key) is not None:
                case[key] = case[key].isoformat()

    for days in (30, 365):
        assert bq.portfolio_summary(days) == \
            analytics_service.portfolio_summary(cases, days)
        assert bq.cross_case_value(days) == \
            analytics_service.cross_case_value(cases, days)
        assert bq.monthly_trend(12) == analytics_service.monthly_trend(cases, 12)


def test_recurring_types_agree(con, population):
    """The per-vendor failure-mode breakdown — the second GROUP BY that
    `_drop_array_projection` cuts out of the query above, compared here on
    its own so nothing in that query goes unasserted.

    This is also what decides `top_exception_type`, which is the phrase a
    controller reads first on the vendor risk table.
    """
    days = 365
    expected = analytics_service.vendor_risk(population, days, limit=1000)
    rows = _query(con, """
        SELECT COALESCE(vendor_id, vendor_name, 'unknown') AS vendor_id,
               exception_type,
               COUNT(*) AS type_count
        FROM cases
        WHERE (@cutoff IS NULL OR created_at IS NULL OR created_at >= @cutoff)
          AND (exception_type IS NOT NULL AND exception_type != @clean_type)
        GROUP BY ALL
    """, days)

    from collections import defaultdict
    actual = defaultdict(dict)
    for row in rows:
        actual[row["vendor_id"]][row["exception_type"]] = int(row["type_count"])

    for vendor in expected["vendors"]:
        assert actual[vendor["vendor_id"]] == vendor["recurring_types"]


@pytest.mark.parametrize("days", [90, 365])
def test_portfolio_type_breakdown_agrees(con, population, days):
    """The other array projection `_drop_array_projection` cuts: counts and
    value per exception type across the portfolio. This is what fills the
    exception-mix chart, so a disagreement here is visible on the screen."""
    expected = analytics_service.portfolio_summary(population, days)
    rows = _query(con, """
        SELECT exception_type,
               COUNT(*) AS type_count,
               SUM(COALESCE(financial_impact, 0)) AS type_value
        FROM cases
        WHERE (@cutoff IS NULL OR created_at IS NULL OR created_at >= @cutoff)
          AND (exception_type IS NOT NULL AND exception_type != @clean_type)
        GROUP BY ALL
    """, days)

    assert {r["exception_type"]: int(r["type_count"]) for r in rows} == \
        expected["exception_type_counts"]
    assert {r["exception_type"]: round(float(r["type_value"] or 0), 2) for r in rows} == \
        expected["exception_type_value"]


# ---------------------------------------------------------------------------
# Parameter binding — the layer the DuckDB tests above do not touch
# ---------------------------------------------------------------------------
def test_every_query_parameter_binds_to_a_real_bigquery_parameter():
    """The gap the DuckDB parity tests leave open.

    Those tests translate the SQL and substitute literals themselves, so they
    never execute `_run` — and `_run` is where the parameters are built. A
    real defect lived in exactly that gap: `CROSS_CASE_TYPE_VALUES` is a
    FROZENSET, `isinstance(frozenset(), set)` is False, so it missed the
    array branch and was sent as a scalar. Two of the five queries bound
    correctly (OPEN_STATUSES is a plain set) and the third died against live
    BigQuery with "Object of type frozenset is not JSON serializable".

    This builds the parameters for every query the way `_run` does and asserts
    each one is a type the client can actually serialise.
    """
    from google.cloud import bigquery

    from schemas import CROSS_CASE_TYPE_VALUES

    # A list, not a dict keyed on the SQL: three of the five queries open with
    # the same `WITH scoped AS (SELECT * FROM ...` prefix, so keying on a
    # truncated statement silently collapses five calls into three.
    captured = []

    def fake_run(sql, params):
        captured.append((sql, params))
        # No rows: every reader handles an empty result, and this test is
        # about what goes IN to the query, not what comes back.
        return []

    import services.bigquery_executor as module
    original = module._run
    module._run = fake_run
    try:
        module.portfolio_summary(365)
        module.vendor_risk(365, 10)
        module.monthly_trend(12)
        module.ageing(365)
        module.cross_case_value(365)
    finally:
        module._run = original

    assert len(captured) == 5, "not every query was exercised"

    # Build them through the REAL builder, not a re-implementation of its type
    # check. A test that repeats the classification it is meant to be testing
    # passes just as happily with the bug reintroduced — the first version of
    # this test did exactly that, and proved nothing.
    for sql, params in captured:
        built = bq.build_query_parameters(params)
        assert len(built) == len(params)
        for param in built:
            value = params[param.name]
            if bq._is_collection(value):
                assert isinstance(param, bigquery.ArrayQueryParameter), \
                    f"{sql[:40]!r}: {param.name} is a " \
                    f"{type(value).__name__} but did not bind as an array"
                assert param.values
            else:
                assert isinstance(param, bigquery.ScalarQueryParameter)
                # The scalar branch must only ever receive things BigQuery can
                # serialise. This is the assertion the frozenset defect failed.
                assert isinstance(param.value, (str, int, float, datetime)) \
                    or param.value is None, \
                    f"{sql[:40]!r}: {param.name} is a " \
                    f"{type(param.value).__name__}, which is not JSON serialisable"

    # And the specific collection that broke, by identity of its type.
    assert isinstance(CROSS_CASE_TYPE_VALUES, frozenset)
    assert isinstance(analytics_service.OPEN_STATUSES, set)
