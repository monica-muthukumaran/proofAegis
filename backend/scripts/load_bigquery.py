"""
load_bigquery.py — create the analytics table and load the case portfolio.

    python -m scripts.load_bigquery --create
    python -m scripts.load_bigquery --from-firestore
    python -m scripts.load_bigquery --from-file data/generated/portfolio.json
    python -m scripts.load_bigquery --verify

WHY A BATCH LOAD AND NOT A STREAM

The honest answer is that this is a mirror, not a source of truth. Firestore
holds the case; BigQuery holds a projection of it for aggregation. Streaming
every write into BigQuery would add a second failure mode to the ingestion
path — an invoice that processed correctly but did not reach the analytics
table — for a freshness guarantee that portfolio analytics does not need.
A controller asking which vendors to audit this quarter is not harmed by an
hour-old table.

At production volume the right shape is a scheduled load or a Datastream
CDC pipeline. Both are the same idea as this script with an operator
attached, and neither changes a line of services/bigquery_executor.py.

WHAT IT REFUSES TO DO

`--from-file` truncates before loading, because a portfolio file is a whole
population and appending it twice would double every count in the analytics
screens. `--from-firestore` does the same. A load that silently doubled the
exception rate would be worse than no load at all.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import config  # noqa: E402
from services import bigquery_executor as bq  # noqa: E402


def _client(as_user: bool = False):
    """A BigQuery client, and a clear answer about WHO it authenticates as.

    This is the trip hazard. `config.py` calls `load_dotenv()`, which puts
    `GOOGLE_APPLICATION_CREDENTIALS` from backend/.env into the environment,
    so by default this script authenticates as the RUNTIME SERVICE ACCOUNT
    rather than as the human who typed the command. That account is
    provisioned for Firestore and Cloud Storage and holds no BigQuery roles,
    which surfaces as a 403 phrased as though the human lacked permission.

    `--as-user` drops that variable so google-auth falls back to gcloud
    application-default credentials. That is the right identity for a one-off
    administrative load: the serving account stays read-only, and nothing in
    the request path is granted the ability to write here.
    """
    try:
        from google.cloud import bigquery
    except ImportError:
        sys.exit(
            "google-cloud-bigquery is not installed.\n"
            "  pip install -r requirements.txt")
    if not config.GOOGLE_CLOUD_PROJECT:
        sys.exit("GOOGLE_CLOUD_PROJECT is not set. See backend/.env.example.")

    if as_user:
        key = os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
        if key:
            print("ignoring the service-account key ("
                  + os.path.basename(key) + "); using your gcloud credentials")
        try:
            import google.auth
            google.auth.default(
                scopes=["https://www.googleapis.com/auth/cloud-platform"])
        except Exception:
            sys.exit("No application-default credentials for your user account."
                     + os.linesep + "  gcloud auth application-default login")

    return bigquery.Client(project=config.GOOGLE_CLOUD_PROJECT)


def _explain_permission_error(exc) -> None:
    """Turn a 403 into the two commands that fix it.

    A stack trace ending in "User does not have bigquery.datasets.create"
    does not say WHICH user, and the answer is usually not the one who ran
    the command.
    """
    key = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    identity = ("the service account in GOOGLE_APPLICATION_CREDENTIALS"
                if key else "your gcloud credentials")
    lines = [
        "",
        "BigQuery refused the request, authenticating as " + identity + ".",
        "",
        "  " + str(exc),
        "",
        "Two ways forward:",
        "",
        "  1. Run this load as YOURSELF, leaving the serving account",
        "     read-only (preferred - nothing in the request path can then",
        "     write to BigQuery):",
        "",
        "       gcloud auth application-default login",
        "       python -m scripts.load_bigquery --as-user --create "
        "--from-firestore --verify",
        "",
        "  2. Or grant the service account write access, if you would",
        "     rather not switch identities:",
        "",
        "       gcloud projects add-iam-policy-binding PROJECT_ID \\",
        "         --member=serviceAccount:SA_EMAIL \\",
        "         --role=roles/bigquery.dataEditor",
        "",
        "See DEPLOYMENT_GUIDE.md section 13A.4.",
    ]
    sys.exit(os.linesep.join(lines))


def create(client) -> None:
    from google.cloud import bigquery

    dataset_id = f"{config.GOOGLE_CLOUD_PROJECT}.{config.BIGQUERY_DATASET}"
    dataset = bigquery.Dataset(dataset_id)
    dataset.location = config.BIGQUERY_LOCATION
    client.create_dataset(dataset, exists_ok=True)
    print(f"dataset ready: {dataset_id} ({config.BIGQUERY_LOCATION})")

    client.query(bq.create_table_ddl()).result()
    print(f"table ready:   {bq.table_ref()}")
    print(f"  partitioned by DATE({bq.PARTITION_FIELD})")
    print(f"  clustered by  {', '.join(bq.CLUSTER_FIELDS)}")


def _load(client, cases: list[dict], source: str) -> None:
    from google.cloud import bigquery

    rows = [bq.to_row(c) for c in cases]
    if not rows:
        sys.exit(f"{source}: no cases found — nothing to load.")

    schema = [bigquery.SchemaField(name, sql_type)
              for name, sql_type in bq.TABLE_SCHEMA]
    job = client.load_table_from_json(
        rows,
        bq.table_ref(),
        job_config=bigquery.LoadJobConfig(
            schema=schema,
            # Replace, never append. See the module docstring.
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        ),
    )
    job.result()
    print(f"loaded {len(rows):,} cases from {source} into {bq.table_ref()}")


def from_file(client, path: str) -> None:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    cases = data if isinstance(data, list) else list(data.values())
    _load(client, cases, path)


def from_firestore(client) -> None:
    from datastore import get_datastore

    _load(client, get_datastore().list_exceptions(), "Firestore")


def _bytes_scanned(client, sql: str) -> int:
    """What this query would cost, without running it.

    A dry run is billed at nothing and returns the bytes BigQuery would
    process. Reported so the partition pruning can be CHECKED rather than
    asserted — an unpartitioned table scanning all history for a 30-day
    question looks identical in the UI and different here.
    """
    from google.cloud import bigquery

    job = client.query(sql, job_config=bigquery.QueryJobConfig(
        dry_run=True, use_query_cache=False))
    return job.total_bytes_processed or 0


def verify(client) -> None:
    """Read back what the executor would read, so a load can be checked
    without opening the UI."""
    rows = list(client.query(
        f"SELECT COUNT(*) AS n, MIN(created_at) AS oldest, MAX(created_at) AS newest "
        f"FROM `{bq.table_ref()}`").result())
    row = rows[0]
    print(f"rows:   {row['n']:,}")
    print(f"window: {row['oldest']} .. {row['newest']}")

    summary = bq.portfolio_summary(days=365)
    print(f"invoices (365d):  {summary['invoice_count']:,}")
    print(f"exceptions:       {summary['exception_count']:,} "
          f"({summary['exception_rate']:.1%})")
    print(f"value at risk:    INR {summary['value_at_risk']:,.0f}")
    print()
    print(bq.cross_case_value(days=365)["headline"])

    # Cost, measured rather than claimed. The 30-day figure should be a
    # fraction of the 365-day one; if the two are equal, the partition is not
    # pruning and every query is scanning all history.
    print()
    full = f"SELECT * FROM `{bq.table_ref()}`"
    windowed = (f"SELECT * FROM `{bq.table_ref()}` WHERE created_at >= "
                f"TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)")
    whole = _bytes_scanned(client, full)
    pruned = _bytes_scanned(client, windowed)
    print(f"bytes scanned, whole table: {whole:,}")
    print(f"bytes scanned, 30-day window: {pruned:,}")
    if whole and pruned >= whole:
        print("  WARNING: the 30-day window scans the whole table — "
              "the partition is not pruning.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--create", action="store_true",
                        help="create the dataset and partitioned table")
    parser.add_argument("--from-firestore", action="store_true",
                        help="mirror the live Firestore case collection")
    parser.add_argument("--from-file", metavar="PATH",
                        help="load a generated portfolio JSON file")
    parser.add_argument("--verify", action="store_true",
                        help="read the table back through the executor")
    parser.add_argument("--as-user", action="store_true",
                        help="ignore GOOGLE_APPLICATION_CREDENTIALS and use "
                             "your own gcloud credentials, so the serving "
                             "service account stays read-only")
    args = parser.parse_args()

    if not any([args.create, args.from_firestore, args.from_file, args.verify]):
        parser.print_help()
        return

    from google.api_core import exceptions as gexc

    client = _client(as_user=args.as_user)
    try:
        if args.create:
            create(client)
        if args.from_file:
            from_file(client, args.from_file)
        if args.from_firestore:
            from_firestore(client)
        if args.verify:
            verify(client)
    except (gexc.Forbidden, gexc.PermissionDenied) as exc:
        _explain_permission_error(exc)


if __name__ == "__main__":
    main()
