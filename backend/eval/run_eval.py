"""
run_eval.py — scores the exception pipeline against a labelled portfolio.

    python -m eval.run_eval --count 320
    python -m eval.run_eval --count 320 --json data/generated/eval_report.json

WHAT IS ACTUALLY BEING MEASURED

The fixtures in eval/fixtures.py are documents, not answers. This runner
hands them to the SAME code the product runs — ingestion_service's
build_matching_input, history_service's cross-case checks, and
matching_service's evaluate_exception — through a datastore stand-in that
serves the fixture's own prior invoices. Nothing is re-implemented for the
eval, so a score here is a score of the shipping pipeline rather than of a
convenient copy of it.

What it does NOT measure: extraction. These fixtures start from field values,
so the parser is not exercised. That is a separate question with a separate
harness, eval/extraction_eval.py, because mixing them would leave every
failure ambiguous between "read the document wrong" and "reasoned about it
wrong".

READING THE OUTPUT

Per exception type:
    precision   of the cases we called X, how many were X
    recall      of the cases that were X, how many did we call X
    support     how many cases were genuinely X

The confusion matrix is where the interesting failures live. A false negative
that lands in `no_exception` is a threshold that did not fire; one that lands
in another exception type is a precedence question, which is usually the more
interesting of the two.

Every disagreement is listed individually with the reason the fixture
expected what it did. That list is the point of the exercise: a clean number
with no failures shown is a claim, and a number next to four named failures
is a measurement.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Optional

# Run as a module from backend/: `python -m eval.run_eval`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from eval.fixtures import (  # noqa: E402
    PRICE_TOLERANCE_PERCENT,
    QUANTITY_TOLERANCE_PERCENT,
    Fixture,
    build_portfolio,
)
from services import history_service  # noqa: E402
from services.ingestion_service import build_matching_input  # noqa: E402
from services.matching_service import evaluate_exception  # noqa: E402


class FixtureDatastore:
    """
    The narrowest possible stand-in for a datastore: exactly the two methods
    build_matching_input reaches for.

    It exists so the eval can exercise the real cross-case code path. The
    alternative — calling history_service directly with a hand-assembled
    argument list — would skip the assembly logic that decides WHICH prior
    invoices are in scope, and that logic is a place bugs live.
    """

    def __init__(self, fixture: Fixture, tolerance: dict):
        self._priors = fixture.prior_invoices
        self._tolerance = tolerance

    def find_documents_by_type(self, document_type: str, exclude_exception_id=None) -> list[dict]:
        if document_type != "vendor_invoice":
            return []
        return [d for d in self._priors if d.get("exception_id") != exclude_exception_id]

    def get_tolerance_rules(self, vendor_name=None, category=None) -> dict:
        return dict(self._tolerance)


def _documents_for(fixture: Fixture) -> list[dict]:
    """The fixture's own documents, in the shape the ingestion pipeline reads."""
    stamp = fixture.created_at.isoformat()
    documents = [{
        "document_id": f"DOC-{fixture.case_id}-INV",
        "exception_id": fixture.case_id,
        "document_type": "vendor_invoice",
        "processing_state": "completed",
        "uploaded_at": stamp,
        "extraction": fixture.invoice,
    }]
    if fixture.purchase_order is not None:
        documents.append({
            "document_id": f"DOC-{fixture.case_id}-PO",
            "exception_id": fixture.case_id,
            "document_type": "purchase_order",
            "processing_state": "completed",
            "uploaded_at": stamp,
            "extraction": fixture.purchase_order,
        })
    if fixture.goods_receipt is not None:
        documents.append({
            "document_id": f"DOC-{fixture.case_id}-GRN",
            "exception_id": fixture.case_id,
            "document_type": "goods_receipt_note",
            "processing_state": "completed",
            "uploaded_at": stamp,
            "extraction": fixture.goods_receipt,
        })
    return documents


def predict(fixture: Fixture) -> dict:
    """Runs the shipping pipeline over one fixture and returns its verdict."""
    tolerance = {
        "price_variance_percent": PRICE_TOLERANCE_PERCENT,
        "quantity_variance_percent": QUANTITY_TOLERANCE_PERCENT,
        "tolerance_source": "eval harness default",
    }
    ds = FixtureDatastore(fixture, tolerance)
    matching_input, _sources = build_matching_input(
        _documents_for(fixture), ds, fixture.case_id)

    if matching_input is None:
        # No usable invoice. Not reachable from the current fixture set, and
        # recorded honestly rather than silently scored as something else if
        # it ever becomes reachable.
        return {"exception_type": "unprocessable", "financial_impact": 0.0,
                "match_score": 0, "cross_case": False}

    # build_matching_input resolves price drift through case_service, which
    # needs a real datastore. Running it here directly keeps the eval on the
    # same function the product uses without dragging in that dependency.
    matching_input["price_drift"] = history_service.detect_price_drift(
        _documents_for(fixture)[0], fixture.prior_invoices, PRICE_TOLERANCE_PERCENT)

    result = evaluate_exception(matching_input, tolerance)
    return {
        "exception_type": result.exception_type.value,
        "financial_impact": result.financial_impact,
        "match_score": result.match_score,
        "cross_case": result.cross_case,
    }


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------
def score(rows: list[dict]) -> dict:
    """Per-type precision/recall/F1, a confusion matrix, and every miss."""
    labels = sorted({r["expected"] for r in rows} | {r["predicted"] for r in rows})

    confusion: dict[str, Counter] = defaultdict(Counter)
    for row in rows:
        confusion[row["expected"]][row["predicted"]] += 1

    per_type = {}
    for label in labels:
        true_positive = sum(1 for r in rows if r["expected"] == label and r["predicted"] == label)
        predicted_count = sum(1 for r in rows if r["predicted"] == label)
        actual_count = sum(1 for r in rows if r["expected"] == label)

        # A type nobody predicted has undefined precision, not zero precision.
        # Reporting 0.0 would drag a macro average down with a number that
        # describes no event.
        precision = (true_positive / predicted_count) if predicted_count else None
        recall = (true_positive / actual_count) if actual_count else None
        f1 = None
        if precision and recall:
            f1 = 2 * precision * recall / (precision + recall)

        per_type[label] = {
            "support": actual_count,
            "predicted": predicted_count,
            "true_positive": true_positive,
            "false_positive": predicted_count - true_positive,
            "false_negative": actual_count - true_positive,
            "precision": None if precision is None else round(precision, 4),
            "recall": None if recall is None else round(recall, 4),
            "f1": None if f1 is None else round(f1, 4),
        }

    # Detection is the headline: did we raise an exception at all, on the
    # cases that had one. It is reported separately from per-type accuracy
    # because they fail differently — calling a quantity variance a price
    # variance is a misrouted case, and missing it entirely is an unpaid
    # control. Both matter; conflating them hides which one happened.
    def is_exception(label: str) -> bool:
        return label not in ("no_exception", "unprocessable")

    detected = sum(1 for r in rows if is_exception(r["expected"]) and is_exception(r["predicted"]))
    actual_exceptions = sum(1 for r in rows if is_exception(r["expected"]))
    flagged = sum(1 for r in rows if is_exception(r["predicted"]))
    correct_flags = sum(1 for r in rows if is_exception(r["predicted"]) and is_exception(r["expected"]))

    scored = [v for v in per_type.values() if v["precision"] is not None and v["recall"] is not None]

    return {
        "cases": len(rows),
        "exception_types": len([label for label in labels if is_exception(label)]),
        "exact_type_accuracy": round(
            sum(1 for r in rows if r["expected"] == r["predicted"]) / len(rows), 4) if rows else 0,
        "detection": {
            "recall": round(detected / actual_exceptions, 4) if actual_exceptions else None,
            "precision": round(correct_flags / flagged, 4) if flagged else None,
            "actual_exceptions": actual_exceptions,
            "flagged": flagged,
            "missed": actual_exceptions - detected,
            "false_alarms": flagged - correct_flags,
        },
        "macro_precision": round(sum(v["precision"] for v in scored) / len(scored), 4) if scored else None,
        "macro_recall": round(sum(v["recall"] for v in scored) / len(scored), 4) if scored else None,
        "per_type": per_type,
        "confusion": {expected: dict(counts) for expected, counts in sorted(confusion.items())},
        "misses": [r for r in rows if r["expected"] != r["predicted"]],
    }


def run(count: int, months: int) -> dict:
    fixtures = build_portfolio(count=count, months=months)
    rows = []
    for fixture in fixtures:
        outcome = predict(fixture)
        rows.append({
            "case_id": fixture.case_id,
            "vendor": fixture.vendor_name,
            "defect": fixture.defect,
            "defect_detail": fixture.defect_detail,
            "noise": fixture.noise,
            "expected": fixture.expected_type,
            "expected_because": fixture.expected_because,
            "predicted": outcome["exception_type"],
            "financial_impact": outcome["financial_impact"],
            "match_score": outcome["match_score"],
            "cross_case": outcome["cross_case"],
        })

    report = score(rows)

    # The split that stops the headline being a description of the fixture
    # set. On clean documents this pipeline is arithmetic and scores like
    # arithmetic; the number worth quoting is what happens when the vendor
    # name is spelled differently or the tax basis does not line up, because
    # that is what arrives in a real inbox.
    clean_rows = [r for r in rows if r["noise"] == "none"]
    noisy_rows = [r for r in rows if r["noise"] != "none"]
    report["by_condition"] = {
        "clean": score(clean_rows) if clean_rows else None,
        "degraded": score(noisy_rows) if noisy_rows else None,
    }
    # Which document condition costs the most, so the failures are actionable
    # rather than just counted.
    by_noise: dict[str, dict] = {}
    for row in noisy_rows:
        bucket = by_noise.setdefault(row["noise"], {"cases": 0, "wrong": 0})
        bucket["cases"] += 1
        if row["expected"] != row["predicted"]:
            bucket["wrong"] += 1
    for bucket in by_noise.values():
        bucket["accuracy"] = round(1 - bucket["wrong"] / bucket["cases"], 4)
    report["by_noise"] = dict(sorted(by_noise.items(), key=lambda kv: kv[1]["accuracy"]))

    report["tolerance"] = {
        "price_variance_percent": PRICE_TOLERANCE_PERCENT,
        "quantity_variance_percent": QUANTITY_TOLERANCE_PERCENT,
    }
    # The claim the product is actually making, measured on the same run:
    # how much of what was caught needed the rest of the workspace to see.
    cross_case_rows = [r for r in rows if r["cross_case"]]
    report["cross_case"] = {
        "exceptions_found": len(cross_case_rows),
        "value": round(sum(r["financial_impact"] for r in cross_case_rows), 2),
        "share_of_exceptions": round(
            len(cross_case_rows) / report["detection"]["flagged"], 4
        ) if report["detection"]["flagged"] else 0,
    }
    return report


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def print_report(report: dict) -> None:
    detection = report["detection"]
    print()
    print(f"  {report['cases']} cases · {report['exception_types']} exception types · "
          f"price tolerance {report['tolerance']['price_variance_percent']:g}%, "
          f"quantity {report['tolerance']['quantity_variance_percent']:g}%")
    print()
    print(f"  Detection      recall {detection['recall']:.3f}   precision {detection['precision']:.3f}"
          f"   ({detection['missed']} missed, {detection['false_alarms']} false alarms)")
    print(f"  Exact type     accuracy {report['exact_type_accuracy']:.3f}"
          f"   macro precision {report['macro_precision']:.3f}"
          f"   macro recall {report['macro_recall']:.3f}")
    print()

    print(f"  {'exception type':<26}{'support':>8}{'prec':>8}{'recall':>8}{'F1':>8}{'FN':>6}{'FP':>6}")
    print(f"  {'-' * 70}")
    for label, stats in sorted(report["per_type"].items(), key=lambda kv: -kv[1]["support"]):
        def fmt(value):
            return f"{value:.3f}" if value is not None else "   — "
        print(f"  {label:<26}{stats['support']:>8}{fmt(stats['precision']):>8}"
              f"{fmt(stats['recall']):>8}{fmt(stats['f1']):>8}"
              f"{stats['false_negative']:>6}{stats['false_positive']:>6}")

    print()
    print("  Confusion (rows = actual, columns = predicted)")
    for expected, counts in report["confusion"].items():
        rendered = ", ".join(f"{predicted} x{n}" for predicted, n in
                             sorted(counts.items(), key=lambda kv: -kv[1]))
        print(f"    {expected:<26} -> {rendered}")

    clean = report["by_condition"]["clean"]
    degraded = report["by_condition"]["degraded"]
    if clean and degraded:
        print()
        print("  Split by document condition — the headline above averages these two together")
        print(f"    clean documents        {clean['cases']:>4} cases   "
              f"exact-type accuracy {clean['exact_type_accuracy']:.3f}")
        print(f"    degraded documents     {degraded['cases']:>4} cases   "
              f"exact-type accuracy {degraded['exact_type_accuracy']:.3f}")
        print()
        print("  Cost of each document condition")
        for noise, stats in report["by_noise"].items():
            print(f"    {noise:<26}{stats['cases']:>4} cases   "
                  f"accuracy {stats['accuracy']:.3f}   ({stats['wrong']} wrong)")

    misses = report["misses"]
    print()
    if not misses:
        print("  No disagreements.")
    else:
        print(f"  {len(misses)} disagreement(s) — every one, with why the fixture expected what it did:")
        for row in misses:
            condition = "" if row["noise"] == "none" else f"  [{row['noise']}]"
            print(f"    {row['case_id']}  expected {row['expected']}, got {row['predicted']}{condition}")
            print(f"      {row['expected_because']}")

    cross = report["cross_case"]
    print()
    print(f"  Cross-case findings: {cross['exceptions_found']} of {detection['flagged']} exceptions "
          f"({cross['share_of_exceptions']:.0%}), INR {cross['value']:,.0f} — "
          f"none of them visible to a per-invoice check.")
    print()
    print("  Synthetic fixtures. Ground truth is the injected defect, labelled from the documented")
    print("  policy rather than from matching_service.py, so a disagreement is a real result.")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(description="Score the ProofAegis exception pipeline.")
    parser.add_argument("--count", type=int, default=320, help="Number of cases to generate.")
    parser.add_argument("--months", type=int, default=12, help="Months of history to spread across.")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="Also write the full report as JSON to this path.")
    args = parser.parse_args()

    report = run(args.count, args.months)
    print_report(report)

    if args.json_path:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_path)), exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
        print(f"  Wrote {args.json_path}\n")


if __name__ == "__main__":
    main()
