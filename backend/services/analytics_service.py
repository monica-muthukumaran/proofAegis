"""
analytics_service.py — Preventive Control Intelligence.

Resolving one blocked invoice is the workflow. Telling a controller *where
the next ten will come from* is the argument for the product. This is that
second thing: vendor-level exception rates, value at risk, recurring failure
modes, ageing against SLA, and month-over-month trend.

Three rules this module holds to:

1. **Every metric is deterministic arithmetic.** No model is consulted. A
   number a controller might act on — a vendor's exception rate, money at
   risk — is computed here in plain Python, exactly like matching_service.py
   computes financial impact. Gemini may later narrate these figures; it may
   never produce one.

2. **The denominator is real.** Exception *rate* requires knowing how many
   invoices did NOT fail, which is why clean invoices are stored as cases
   with `no_exception` rather than discarded. A system that keeps only
   failures can report counts but never rates, and rates are what make a
   vendor comparable to another vendor.

3. **The shape is BigQuery-ready.** Each function is one grouped aggregation
   over a date-filtered set — the same shape as the SQL that would replace it
   at real volume. Swapping in a BigQuery executor later is a change of
   engine behind these same signatures, not a redesign. At a few hundred
   records this runs in microseconds and costs nothing.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

# Statuses that mean "still consuming somebody's attention".
OPEN_STATUSES = {
    "exception_detected", "assigned", "awaiting_procurement",
    "awaiting_receiving", "awaiting_vendor",
}

CLEAN_TYPE = "no_exception"

# Ageing buckets, in days open. The last one is the one a controller cares
# about: anything sitting past a fortnight has usually stopped being an
# exception and started being a write-off risk.
AGE_BUCKETS = [
    ("0-3 days", 0, 3),
    ("4-7 days", 4, 7),
    ("8-14 days", 8, 14),
    ("15-30 days", 15, 30),
    ("31+ days", 31, None),
]

SLA_BREACH_DAYS = 14


def _parse(timestamp: Optional[str]) -> Optional[datetime]:
    """Tolerant ISO parse. A record with an unreadable date is excluded from
    time-based metrics rather than silently counted as 'now', which would
    quietly flatter the ageing numbers."""
    if not timestamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _within_window(case: dict, cutoff: Optional[datetime]) -> bool:
    if cutoff is None:
        return True
    created = _parse(case.get("created_at"))
    if created is None:
        return True  # undated seed cases stay visible rather than vanishing
    return created >= cutoff


def _filter_cases(cases: Iterable[dict], days: Optional[int]) -> list[dict]:
    """The cost-aware bit: every analytic runs over a bounded window, never
    the whole table. Mirrors the date predicate a BigQuery version would need
    to keep scans small."""
    cutoff = None
    if days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return [c for c in cases if _within_window(c, cutoff)]


def _is_exception(case: dict) -> bool:
    exception_type = case.get("exception_type")
    return bool(exception_type) and exception_type != CLEAN_TYPE


def _age_days(case: dict, now: datetime) -> Optional[float]:
    created = _parse(case.get("created_at"))
    if created is None:
        return None
    return max(0.0, (now - created).total_seconds() / 86400)


# ---------------------------------------------------------------------------
# Vendor risk — the differentiator
# ---------------------------------------------------------------------------
def vendor_risk(cases: Iterable[dict], days: Optional[int] = 365, limit: int = 25) -> dict:
    """
    Per vendor: how often they produce an exception, how much money that puts
    at risk, what they fail at most, and how slow those cases are to clear.

    `why_at_risk` is assembled from those computed figures — it is a sentence
    about arithmetic, not a judgement. If Gemini later rewrites it into
    smoother prose, it will be handed these numbers and forbidden from
    inventing others.
    """
    scoped = _filter_cases(cases, days)
    now = datetime.now(timezone.utc)

    grouped: dict[str, dict] = defaultdict(lambda: {
        "invoice_count": 0,
        "exception_count": 0,
        "value_at_risk": 0.0,
        "invoiced_value": 0.0,
        "type_counts": defaultdict(int),
        "match_scores": [],
        "open_ages": [],
        "vendor_name": None,
        "business_unit": None,
    })

    for case in scoped:
        vendor_id = case.get("vendor_id") or case.get("vendor_name") or "unknown"
        bucket = grouped[vendor_id]
        bucket["vendor_name"] = bucket["vendor_name"] or case.get("vendor_name") or "Unknown vendor"
        bucket["business_unit"] = bucket["business_unit"] or case.get("business_unit")
        bucket["invoice_count"] += 1
        bucket["invoiced_value"] += float(case.get("invoice_amount") or 0)

        if case.get("match_score") is not None:
            bucket["match_scores"].append(float(case["match_score"]))

        if _is_exception(case):
            bucket["exception_count"] += 1
            bucket["type_counts"][case["exception_type"]] += 1
            if case.get("status") in OPEN_STATUSES:
                bucket["value_at_risk"] += float(case.get("financial_impact") or 0)
                age = _age_days(case, now)
                if age is not None:
                    bucket["open_ages"].append(age)

    rows = []
    for vendor_id, bucket in grouped.items():
        invoices = bucket["invoice_count"]
        if invoices == 0:
            continue
        exception_rate = bucket["exception_count"] / invoices
        top_type = None
        if bucket["type_counts"]:
            top_type = max(bucket["type_counts"].items(), key=lambda kv: kv[1])[0]
        avg_age = round(sum(bucket["open_ages"]) / len(bucket["open_ages"]), 1) if bucket["open_ages"] else 0.0
        avg_match = round(sum(bucket["match_scores"]) / len(bucket["match_scores"]), 1) if bucket["match_scores"] else None

        rows.append({
            "vendor_id": vendor_id,
            "vendor_name": bucket["vendor_name"],
            "business_unit": bucket["business_unit"],
            "invoice_count": invoices,
            "exception_count": bucket["exception_count"],
            "exception_rate": round(exception_rate, 4),
            "value_at_risk": round(bucket["value_at_risk"], 2),
            "invoiced_value": round(bucket["invoiced_value"], 2),
            "top_exception_type": top_type,
            "recurring_types": dict(sorted(bucket["type_counts"].items(), key=lambda kv: -kv[1])),
            "average_match_score": avg_match,
            "average_open_age_days": avg_age,
            "risk_band": _risk_band(exception_rate, bucket["value_at_risk"]),
            "why_at_risk": _why_at_risk(bucket, exception_rate, top_type, avg_age),
        })

    # Ranked by money first, then by how often they fail — a vendor with two
    # huge exceptions matters more than one with ten trivial ones.
    rows.sort(key=lambda r: (-r["value_at_risk"], -r["exception_rate"]))
    return {
        "window_days": days,
        "vendor_count": len(rows),
        "vendors": rows[:limit],
    }


def _risk_band(exception_rate: float, value_at_risk: float) -> str:
    if exception_rate >= 0.40 or value_at_risk >= 1_000_000:
        return "high"
    if exception_rate >= 0.20 or value_at_risk >= 250_000:
        return "medium"
    return "low"


def _why_at_risk(bucket: dict, exception_rate: float, top_type: Optional[str], avg_age: float) -> str:
    """Deterministic explanation, citing only figures computed above."""
    if bucket["exception_count"] == 0:
        return (
            f"No exceptions across {bucket['invoice_count']} invoices in this window."
        )
    parts = [
        f"{bucket['exception_count']} of {bucket['invoice_count']} invoices raised an exception "
        f"({exception_rate:.0%})."
    ]
    if top_type:
        share = bucket["type_counts"][top_type] / bucket["exception_count"]
        parts.append(
            f"Most common failure: {top_type.replace('_', ' ')} ({share:.0%} of their exceptions)."
        )
    if bucket["value_at_risk"] > 0:
        parts.append(f"INR {bucket['value_at_risk']:,.0f} is currently open and unpaid.")
    if avg_age >= SLA_BREACH_DAYS:
        parts.append(f"Open cases are averaging {avg_age:.0f} days, past the {SLA_BREACH_DAYS}-day SLA.")
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------
def monthly_trend(cases: Iterable[dict], months: int = 12) -> dict:
    """Exceptions, clean invoices, and value at risk per calendar month."""
    scoped = _filter_cases(cases, months * 31)
    buckets: dict[str, dict] = defaultdict(
        lambda: {"exceptions": 0, "clean": 0, "invoices": 0, "value_at_risk": 0.0}
    )

    for case in scoped:
        created = _parse(case.get("created_at"))
        if created is None:
            continue
        key = f"{created.year}-{created.month:02d}"
        bucket = buckets[key]
        bucket["invoices"] += 1
        if _is_exception(case):
            bucket["exceptions"] += 1
            bucket["value_at_risk"] += float(case.get("financial_impact") or 0)
        else:
            bucket["clean"] += 1

    points = []
    for key in sorted(buckets):
        bucket = buckets[key]
        points.append({
            "month": key,
            "invoices": bucket["invoices"],
            "exceptions": bucket["exceptions"],
            "clean": bucket["clean"],
            "exception_rate": round(bucket["exceptions"] / bucket["invoices"], 4) if bucket["invoices"] else 0,
            "value_at_risk": round(bucket["value_at_risk"], 2),
        })
    return {"months": months, "points": points[-months:]}


# ---------------------------------------------------------------------------
# Ageing / SLA
# ---------------------------------------------------------------------------
def ageing(cases: Iterable[dict], days: Optional[int] = 365) -> dict:
    """How long open exceptions have been sitting, bucketed. Only OPEN cases
    count — a resolved case has no age worth worrying about."""
    scoped = _filter_cases(cases, days)
    now = datetime.now(timezone.utc)

    buckets = {label: {"count": 0, "value_at_risk": 0.0} for label, _, _ in AGE_BUCKETS}
    breached = 0
    total_open = 0
    oldest = 0.0

    for case in scoped:
        if not _is_exception(case) or case.get("status") not in OPEN_STATUSES:
            continue
        age = _age_days(case, now)
        if age is None:
            continue
        total_open += 1
        oldest = max(oldest, age)
        impact = float(case.get("financial_impact") or 0)
        if age > SLA_BREACH_DAYS:
            breached += 1
        for label, low, high in AGE_BUCKETS:
            if age >= low and (high is None or age <= high):
                buckets[label]["count"] += 1
                buckets[label]["value_at_risk"] += impact
                break

    return {
        "sla_days": SLA_BREACH_DAYS,
        "open_exceptions": total_open,
        "breaching_sla": breached,
        "oldest_open_days": round(oldest, 1),
        "buckets": [
            {"label": label, "count": buckets[label]["count"],
             "value_at_risk": round(buckets[label]["value_at_risk"], 2)}
            for label, _, _ in AGE_BUCKETS
        ],
    }


# ---------------------------------------------------------------------------
# Portfolio headline
# ---------------------------------------------------------------------------
def portfolio_summary(cases: Iterable[dict], days: Optional[int] = 365) -> dict:
    scoped = _filter_cases(cases, days)
    total = len(scoped)
    exceptions = [c for c in scoped if _is_exception(c)]
    open_exceptions = [c for c in exceptions if c.get("status") in OPEN_STATUSES]

    type_counts: dict[str, int] = defaultdict(int)
    type_value: dict[str, float] = defaultdict(float)
    for case in exceptions:
        type_counts[case["exception_type"]] += 1
        type_value[case["exception_type"]] += float(case.get("financial_impact") or 0)

    invoiced = sum(float(c.get("invoice_amount") or 0) for c in scoped)
    at_risk = sum(float(c.get("financial_impact") or 0) for c in open_exceptions)

    return {
        "window_days": days,
        "invoice_count": total,
        "exception_count": len(exceptions),
        "clean_count": total - len(exceptions),
        "exception_rate": round(len(exceptions) / total, 4) if total else 0,
        "clean_rate": round((total - len(exceptions)) / total, 4) if total else 0,
        "open_exception_count": len(open_exceptions),
        "invoiced_value": round(invoiced, 2),
        "value_at_risk": round(at_risk, 2),
        # The headline a controller repeats in a meeting: of everything we
        # were billed, this share is currently unverifiable.
        "value_at_risk_share": round(at_risk / invoiced, 4) if invoiced else 0,
        "exception_type_counts": dict(sorted(type_counts.items(), key=lambda kv: -kv[1])),
        "exception_type_value": {k: round(v, 2) for k, v in sorted(type_value.items(), key=lambda kv: -kv[1])},
    }


# ---------------------------------------------------------------------------
# The claim, measured
# ---------------------------------------------------------------------------
def cross_case_value(cases: Iterable[dict], days: Optional[int] = 365) -> dict:
    """
    What a per-invoice system would not have found.

    Commercial AP automation is good at the three-way match. Given an invoice,
    a purchase order and a goods receipt, it will tell you whether the three
    agree, and so will this — that part is table stakes and this function
    counts it as such.

    What it cannot do is look sideways. A duplicate is only a duplicate
    relative to an invoice in a different case. Cumulative over-billing needs
    every invoice raised against one order. A changed bank account needs the
    vendor's last invoice. Price drift needs their last six. Every one of
    those fires on an invoice whose own three-way match is CLEAN — which is
    the uncomfortable part, and the actual product: what passed is scarier
    than what failed.

    So this partitions the portfolio on exactly that boundary and reports the
    delta in cases and in rupees. The set of types that count as cross-case is
    declared once in schemas.py and imported, not re-listed here, so this
    figure cannot drift away from what the matcher actually does.

    A note on the money. `financial_impact` for a cross-case finding is the
    exposure that finding carries, computed by matching_service.py under the
    same rules as any other case. It is NOT a claim of loss prevented: a
    duplicate flagged and then confirmed legitimate had no money at stake at
    all. It is what was put in front of a human that otherwise would not have
    been.
    """
    from schemas import CROSS_CASE_TYPE_VALUES

    scoped = _filter_cases(cases, days)
    exceptions = [c for c in scoped if _is_exception(c)]

    cross = [c for c in exceptions if c.get("exception_type") in CROSS_CASE_TYPE_VALUES]
    single = [c for c in exceptions if c.get("exception_type") not in CROSS_CASE_TYPE_VALUES]

    def total(rows):
        return round(sum(float(r.get("financial_impact") or 0) for r in rows), 2)

    by_type: dict[str, dict] = defaultdict(lambda: {"count": 0, "value": 0.0})
    for case in cross:
        bucket = by_type[case["exception_type"]]
        bucket["count"] += 1
        bucket["value"] = round(bucket["value"] + float(case.get("financial_impact") or 0), 2)

    # Cases the cross-case layer caught whose own documents agreed on
    # everything. These are the ones that make the point, because a
    # per-invoice system would not merely have ranked them lower — it would
    # have paid them.
    would_have_cleared = [
        c for c in cross
        if c.get("match_score") is not None and int(c["match_score"]) >= CLEAN_MATCH_SCORE
    ]

    return {
        "window_days": days,
        "invoice_count": len(scoped),
        "exception_count": len(exceptions),
        "single_invoice": {
            "count": len(single),
            "value": total(single),
        },
        "cross_case": {
            "count": len(cross),
            "value": total(cross),
            "share_of_exceptions": round(len(cross) / len(exceptions), 4) if exceptions else 0,
            "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1]["value"])),
        },
        "would_have_cleared": {
            "count": len(would_have_cleared),
            "value": total(would_have_cleared),
            "threshold_match_score": CLEAN_MATCH_SCORE,
        },
        "headline": _cross_case_headline(cross, would_have_cleared, total(cross)),
        "basis": (
            "Partitioned on exception type. A cross-case type is one that cannot be reached "
            "from a single case's own documents — it needs a query across the rest of the "
            "workspace. Value is the financial impact matching_service.py computed for each "
            "case, not a claim of loss prevented."
        ),
    }


# A match score at or above this means every comparison the case could make
# agreed. An invoice like that is what a three-way match calls payable.
CLEAN_MATCH_SCORE = 100


def _cross_case_headline(cross: list[dict], would_have_cleared: list[dict], value: float) -> str:
    """The sentence, assembled from the figures just computed."""
    if not cross:
        return "No cross-case findings in this window."
    clean = len(would_have_cleared)
    sentence = (
        f"{len(cross)} exception{'' if len(cross) == 1 else 's'} worth INR {value:,.0f} "
        f"came from checks that read the rest of the workspace, not this invoice."
    )
    if clean:
        sentence += (
            f" {clean} of them scored a full three-way match on their own documents — "
            f"a per-invoice system would have passed them for payment."
        )
    return sentence
