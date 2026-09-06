"""
generate_synthetic_data.py — builds a synthetic AP portfolio.

Three demo cases prove the workflow. They cannot prove a *pattern*: you
cannot say "this vendor fails 18% of the time" from three records, and a
dashboard built on them looks empty no matter how it is styled. This
generates a few hundred invoices across a realistic vendor population so the
analytics screens have something true to say.

Two things make the output worth analysing rather than just voluminous:

  1. **Clean invoices are the majority.** Roughly 60% pass three-way match
     with nothing outside tolerance. Exception RATE is the headline metric of
     the whole analytics story, and a rate needs a denominator. A dataset of
     only failures would make every vendor look 100% bad.

  2. **Risk is concentrated, not uniform.** A handful of vendors are given a
     genuinely elevated exception profile, the rest behave. Uniform random
     noise produces a scatter plot with no signal, which would make the
     "which vendors will fail next" claim hollow.

Everything is fabricated. No real company, contract, invoice, or payment is
represented. The RNG is seeded, so the same command always produces the same
portfolio — a demo that reshuffles itself between rehearsal and judging is
not a demo.

    python scripts/generate_synthetic_data.py --count 320 --out data/generated

Writes:
    portfolio.json    operational records for Firestore / the mock datastore
    portfolio.ndjson  one record per line, ready for a BigQuery load
    vendors.json      the vendor dimension
"""
from __future__ import annotations

import argparse
import json
import os
import random
from datetime import datetime, timedelta, timezone

SEED = 20260905  # the submission date; arbitrary but fixed

# --- Vendor population -----------------------------------------------------
# Names are invented. `risk` is the probability that any given invoice from
# this vendor carries an exception — deliberately skewed so the analytics have
# a real signal to find rather than uniform noise.
VENDORS = [
    ("VEN-0042", "Chennai Industrial Supplies Pvt. Ltd.", "Operations", 0.34),
    ("VEN-0107", "Southern Office Systems", "Facilities", 0.41),
    ("VEN-0219", "BlueWave IT Services", "IT", 0.29),
    ("VEN-0311", "Deccan Logistics Partners", "Logistics", 0.62),   # problem vendor
    ("VEN-0347", "Kaveri Packaging Works", "Operations", 0.18),
    ("VEN-0402", "Meridian Facility Care", "Facilities", 0.55),     # problem vendor
    ("VEN-0455", "Nilgiri Components Ltd.", "Manufacturing", 0.12),
    ("VEN-0508", "Sarvodaya Print House", "Marketing", 0.22),
    ("VEN-0561", "Trident Electricals", "Maintenance", 0.47),
    ("VEN-0604", "Anantha Chemicals", "Manufacturing", 0.09),
    ("VEN-0657", "Vayu Air Systems", "Maintenance", 0.31),
    ("VEN-0703", "Pallava Steel Traders", "Manufacturing", 0.15),
    ("VEN-0748", "Coromandel Freight", "Logistics", 0.38),
    ("VEN-0791", "Ashwin Software Labs", "IT", 0.11),
    ("VEN-0834", "Bharat Safety Equipment", "Operations", 0.26),
    ("VEN-0877", "Marina Catering Services", "Facilities", 0.44),
    ("VEN-0910", "Vellore Textiles", "Manufacturing", 0.07),
    ("VEN-0953", "Konark Instruments", "Maintenance", 0.20),
    ("VEN-0996", "Sagar Marine Supplies", "Logistics", 0.16),
    ("VEN-1024", "Highfield Consulting", "Corporate", 0.13),
]

LINE_ITEMS = [
    "Industrial bearings, grade B", "Office desk units", "Managed IT support",
    "Corrugated packaging, 5-ply", "HVAC servicing contract", "Safety helmets, ISI",
    "Freight — regional haul", "Cleaning consumables", "LED luminaires, 18W",
    "Stainless fasteners, M8", "Printer toner cartridges", "Uniform textiles",
    "Calibration services", "Marine rope, 12mm", "Advisory retainer",
]

# Distribution across exception types, once an invoice IS an exception.
# Weighted toward the three the pipeline handles deeply, with a realistic
# tail of the rest.
#
# The last five are the CROSS-CASE types — the ones a per-invoice check cannot
# reach, which are the product's actual claim. They were missing from this mix
# entirely, so the analytics screen partitioned a portfolio in which the
# interesting half did not exist and reported the delta as almost nothing.
# Their weights are deliberately modest: these are rarer than a price variance
# in any real ledger, and inflating them to make the headline bigger would be
# writing the answer into the data.
EXCEPTION_MIX = [
    ("price_variance", 28),
    ("quantity_variance", 22),
    ("missing_goods_receipt", 16),
    ("missing_purchase_order", 8),
    ("vendor_mismatch", 5),
    ("tax_total_mismatch", 4),
    ("duplicate_invoice", 6),
    ("po_over_billed", 5),
    ("payment_details_changed", 2),
    ("recurring_suspected", 3),
    ("vendor_price_drift", 3),
]

OWNER_BY_TYPE = {
    "price_variance": "Procurement",
    "quantity_variance": "Receiving",
    "missing_goods_receipt": "Requesting business unit",
    "missing_purchase_order": "Procurement",
    "duplicate_invoice": "Accounts Payable",
    "vendor_mismatch": "Vendor Management",
    "tax_total_mismatch": "Accounts Payable",
    "po_over_billed": "Procurement",
    "payment_details_changed": "Accounts Payable",
    "recurring_suspected": "Accounts Payable",
    "vendor_price_drift": "Procurement",
}

# Exception types that came from a check reading the rest of the workspace.
# Mirrors schemas.CROSS_CASE_TYPE_VALUES; this script is standalone by design
# (it runs without the app importable) so the list is restated rather than
# imported, and tests/test_analytics_cross_case.py asserts the two agree.
CROSS_CASE_TYPES = {
    "duplicate_invoice", "po_over_billed", "payment_details_changed",
    "recurring_suspected", "vendor_price_drift",
}

# Where an exception sits once a human has triaged it. Split by whether the
# case is still open, because status has to depend on AGE: teams work their
# backlog down, so most old cases are resolved and most open cases are
# recent. Drawing status independently of age produced an ageing chart where
# 92% of open work was 31+ days old — visually dramatic and obviously false.
OPEN_STATUS_MIX = [
    ("exception_detected", 30),
    ("assigned", 16),
    ("awaiting_procurement", 20),
    ("awaiting_receiving", 18),
    ("awaiting_vendor", 16),
]

CLOSED_STATUS_MIX = [
    ("resolved", 46),
    ("closed", 30),
    ("approved_with_exception", 24),
]

# Probability a case of a given age is still open. A realistic AP backlog is
# a pyramid: fat at the recent end, thin tail of genuinely stuck cases.
def _still_open_probability(age_days: float) -> float:
    # Calibrated for EXCEPTIONS specifically, not invoices generally. An
    # exception waits on somebody outside AP — a vendor to reply, receiving to
    # confirm a delivery, procurement to approve a price — so it clears far
    # more slowly than a straight-through invoice. A fortnight is the SLA;
    # a meaningful tail routinely blows through it, which is the whole reason
    # an ageing report is worth looking at.
    if age_days <= 3:
        return 0.92
    if age_days <= 7:
        return 0.85
    if age_days <= 14:
        return 0.70
    if age_days <= 30:
        return 0.45
    if age_days <= 90:
        return 0.18
    return 0.06

OPEN_STATUSES = {
    "exception_detected", "assigned", "awaiting_procurement",
    "awaiting_receiving", "awaiting_vendor",
}


def weighted_choice(rng: random.Random, pairs):
    total = sum(w for _, w in pairs)
    roll = rng.uniform(0, total)
    upto = 0
    for value, weight in pairs:
        upto += weight
        if roll <= upto:
            return value
    return pairs[-1][0]


def _impact_for(rng: random.Random, exception_type: str, invoice_amount: float) -> tuple[float, str]:
    """Financial impact follows the same rules matching_service.py applies:
    a variance exposes the size of the gap, a missing document exposes the
    whole invoice. Keeping the two consistent matters — a judge who compares
    the portfolio to a live case should not find two different definitions."""
    if exception_type in ("missing_goods_receipt", "missing_purchase_order",
                          "duplicate_invoice", "payment_details_changed"):
        return round(invoice_amount, 2), "Full invoice amount at risk pending verification."
    if exception_type == "price_variance":
        pct = rng.uniform(0.055, 0.24)
        return round(invoice_amount * pct, 2), "Unit-price variance x quantity."
    if exception_type == "quantity_variance":
        pct = rng.uniform(0.04, 0.30)
        return round(invoice_amount * pct, 2), "Unreceived units x implied unit price."
    if exception_type == "tax_total_mismatch":
        pct = rng.uniform(0.01, 0.06)
        return round(invoice_amount * pct, 2), "Tax and total inconsistency."
    if exception_type == "po_over_billed":
        # Only the excess over the order, not the whole invoice — the earlier
        # instalments were legitimately billed.
        pct = rng.uniform(0.08, 0.35)
        return round(invoice_amount * pct, 2), "Billed above the order value across several invoices."
    if exception_type == "vendor_price_drift":
        pct = rng.uniform(0.04, 0.18)
        return round(invoice_amount * pct, 2), "Cumulative rate rise above the original price."
    if exception_type == "recurring_suspected":
        # Nothing is booked as at risk for a recognised billing pattern. This
        # is the same rule matching_service.py applies, and it matters: a
        # portfolio that counted every month's rent as exposure would report a
        # value-at-risk figure nobody could act on.
        return 0.0, "Recognised billing pattern — no amount at risk unless a duplicate is confirmed."
    return round(invoice_amount * rng.uniform(0.02, 0.10), 2), "Vendor record inconsistency."


def _risk_level(exception_type: str, impact: float) -> str:
    if exception_type == "no_exception":
        return "low"
    # A recognised billing pattern carries no money and is not a risk band —
    # it is a note. Ranking every month's rent as anything else is exactly the
    # false positive the recurring check exists to prevent.
    if exception_type == "recurring_suspected":
        return "low"
    if impact >= 150000 or exception_type in (
            "missing_purchase_order", "duplicate_invoice", "payment_details_changed"):
        return "high"
    if impact >= 40000:
        return "medium"
    return "low"


def generate(count: int, months: int = 12) -> tuple[list[dict], list[dict]]:
    rng = random.Random(SEED)
    now = datetime.now(timezone.utc)
    window_days = months * 30

    records: list[dict] = []
    for index in range(count):
        vendor_id, vendor_name, business_unit, vendor_risk = rng.choice(VENDORS)

        # Invoice dates are weighted toward the present rather than spread
        # evenly across the year. A live AP workspace looks like that: a full
        # year of history for trend, but most activity in recent weeks. Spread
        # uniformly, the realistic resolution decay left almost nothing open,
        # and a dashboard reporting a near-empty backlog is as unrepresentative
        # as one reporting a year of untouched work.
        age_fraction = rng.random() ** 1.7
        created = now - timedelta(
            days=age_fraction * window_days,
            hours=rng.randint(0, 23),
            minutes=rng.randint(0, 59),
        )

        # Quantity and unit price are drawn together, not independently: a
        # ₹1.8L service line is billed once, not 250 times. Drawing them
        # separately produced ₹4.5 crore invoices that made every chart a
        # single spike.
        tier = weighted_choice(rng, [("consumable", 45), ("equipment", 35), ("service", 20)])
        if tier == "consumable":
            quantity = rng.choice([50, 100, 120, 200, 250, 500])
            unit_price = rng.choice([45, 120, 315, 630])
        elif tier == "equipment":
            quantity = rng.choice([5, 10, 25, 40, 50])
            unit_price = rng.choice([850, 1200, 2400, 4500, 9000])
        else:
            quantity = rng.choice([1, 1, 1, 2, 3])
            unit_price = rng.choice([45000, 90000, 180000, 240000])
        invoice_amount = float(quantity * unit_price)

        age_days = (now - created).total_seconds() / 86400

        is_exception = rng.random() < vendor_risk
        if is_exception:
            exception_type = weighted_choice(rng, EXCEPTION_MIX)
            impact, basis = _impact_for(rng, exception_type, invoice_amount)
            still_open = rng.random() < _still_open_probability(age_days)
            status = weighted_choice(rng, OPEN_STATUS_MIX if still_open else CLOSED_STATUS_MIX)
            # A cross-case finding sits on an invoice whose OWN documents
            # agree — that is the entire point of it, and it is why a
            # per-invoice system would have paid it. Giving these the same
            # 40-88 match score as a price variance would have contradicted
            # the finding on the same row: a duplicate invoice does not fail
            # its three-way match, it passes and is still a duplicate.
            if exception_type in CROSS_CASE_TYPES:
                match_score = rng.choice([94, 96, 100, 100, 100])
            else:
                match_score = rng.randint(40, 88)
            owner = OWNER_BY_TYPE[exception_type]
        else:
            exception_type = "no_exception"
            impact, basis = 0.0, "Every comparison matched or fell within tolerance."
            status = "cleared"
            match_score = rng.choice([94, 96, 98, 100, 100, 100])
            owner = "No action required"

        # Resolved work carries a later updated_at; open work has been sitting
        # since it was created, which is what makes the ageing chart real.
        if status in OPEN_STATUSES:
            updated = created + timedelta(hours=rng.randint(1, 72))
        else:
            updated = created + timedelta(days=rng.randint(1, 21))
        if updated > now:
            updated = now

        serial = 5000 + index
        records.append({
            "exception_id": f"EXC-2026-{serial:05d}",
            "workspace_id": "demo-workspace",
            "invoice_id": f"INV-2026-{serial:05d}",
            "vendor_id": vendor_id,
            "vendor_name": vendor_name,
            "purchase_order_id": f"PO-2026-{serial:05d}",
            "business_unit": business_unit,
            "currency": "INR",
            "invoice_amount": invoice_amount,
            "po_amount": invoice_amount,
            "line_item_description": rng.choice(LINE_ITEMS),
            "status": status,
            # Derived fields stored rather than recomputed per read: at this
            # volume, recomputing a match for every row of every queue and
            # dashboard request is the difference between an instant page and
            # a visibly slow one. run_analysis remains the only writer for
            # real cases, so the two can never disagree.
            "exception_type": exception_type,
            "match_score": match_score,
            "financial_impact": impact,
            "financial_impact_basis": basis,
            "risk_level": _risk_level(exception_type, impact),
            "assigned_team": owner,
            "origin": "synthetic_portfolio",
            "created_at": created.isoformat(),
            "updated_at": updated.isoformat(),
        })

    vendors = [
        {"vendor_id": v[0], "vendor_name": v[1], "business_unit": v[2], "workspace_id": "demo-workspace"}
        for v in VENDORS
    ]
    return records, vendors


def summarize(records: list[dict]) -> None:
    total = len(records)
    clean = sum(1 for r in records if r["exception_type"] == "no_exception")
    exceptions = total - clean
    at_risk = sum(r["financial_impact"] for r in records if r["status"] in OPEN_STATUSES)

    print(f"\n  {total} invoices across {len({r['vendor_id'] for r in records})} vendors")
    print(f"  {clean} clean ({clean / total:.0%})  ·  {exceptions} exceptions ({exceptions / total:.0%})")
    print(f"  Open value at risk: INR {at_risk:,.0f}\n")

    counts: dict[str, int] = {}
    for r in records:
        if r["exception_type"] != "no_exception":
            counts[r["exception_type"]] = counts.get(r["exception_type"], 0) + 1
    for exception_type, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"    {exception_type:<24} {n:>4}  ({n / exceptions:.0%} of exceptions)")


def main() -> None:
    default_out = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "generated"
    )
    parser = argparse.ArgumentParser(description="Generate a synthetic ProofAegis portfolio.")
    parser.add_argument("--count", type=int, default=420, help="Number of invoices (100-500 recommended).")
    parser.add_argument("--months", type=int, default=12, help="Months of history to spread across.")
    parser.add_argument("--out", default=default_out, help="Output directory.")
    args = parser.parse_args()

    records, vendors = generate(args.count, args.months)
    os.makedirs(args.out, exist_ok=True)

    portfolio_path = os.path.join(args.out, "portfolio.json")
    with open(portfolio_path, "w", encoding="utf-8") as f:
        json.dump({"cases": records}, f, indent=2)

    # One JSON object per line: what `bq load --source_format=NEWLINE_DELIMITED_JSON`
    # expects, so the same data can back a BigQuery executor later without
    # being regenerated in a different shape.
    ndjson_path = os.path.join(args.out, "portfolio.ndjson")
    with open(ndjson_path, "w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")

    vendors_path = os.path.join(args.out, "vendors.json")
    with open(vendors_path, "w", encoding="utf-8") as f:
        json.dump({"vendors": vendors}, f, indent=2)

    summarize(records)
    print(f"  Wrote {portfolio_path}")
    print(f"        {ndjson_path}")
    print(f"        {vendors_path}")
    print("\n  Synthetic data only. No real company, contract, or payment is represented.")


if __name__ == "__main__":
    main()
