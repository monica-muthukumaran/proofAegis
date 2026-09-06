"""
extraction_eval.py — field-level extraction accuracy across document layouts.

    python -m eval.extraction_eval
    python -m eval.extraction_eval --json data/generated/extraction_report.json

WHAT THIS MEASURES, AND WHY IT IS SEPARATE FROM run_eval.py

eval/run_eval.py starts from field values and scores the decision. This
starts from PDF BYTES and scores the reading. Keeping them apart matters: a
combined number would leave every failure ambiguous between "read the
document wrong" and "reasoned about it wrong", and those have completely
different fixes.

The documents are rendered by scripts/generate_synthetic_pdfs.py in each of
the dialects in scripts/pdf_layouts.py — different label wording, value
placement, fonts, table structure, money formats and page clutter. Ground
truth is the spec the renderer was given, so it is known exactly.

The `baseline` layout is the one the parser was written against, and it is
reported separately from the rest for the same reason a control group exists.
The interesting figure is the drop.

WHAT IS SCORED

Per field, one of:
    correct    the parsed value equals the value that was printed
    wrong      a value was recovered and it is not the right one
    missed     the field was printed and nothing was recovered
    absent     this layout does not print the field, so there is nothing to
               recover and it counts neither for nor against

`wrong` is tracked separately from `missed` throughout, because they are not
equally bad. A missed field is reported to the user as "not stated" and the
matcher declines to compare it; a wrong field is a number that looks real and
flows into a variance calculation. One is a gap and the other is a lie.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.generate_synthetic_pdfs import (  # noqa: E402
    CASES,
    INVOICE_DATE,
    RECEIPT_DATE,
    REJECTED_DATE,
    build_case,
)
from scripts.pdf_layouts import LAYOUTS, Layout  # noqa: E402
from services import pdf_field_parser  # noqa: E402
from services.ingestion_service import extract_text_from_bytes  # noqa: E402

# Fields checked per document type, and how each is compared. "number" is
# compared numerically so "INR 2,400.00" and 2400.0 agree; "text" is compared
# on a loose key so punctuation and case differences do not count as errors —
# the matcher does not care about those either.
CHECKS = {
    "purchase_order": (
        ("po_number", "reference"), ("vendor_name", "text"),
        ("quantity", "number"), ("unit_price", "number"), ("total_amount", "number"),
    ),
    "vendor_invoice": (
        ("invoice_number", "reference"), ("vendor_name", "text"), ("po_number", "reference"),
        ("quantity", "number"), ("unit_price", "number"), ("total_amount", "number"),
        ("invoice_date", "date"),
    ),
    "goods_receipt_note": (
        ("po_number", "reference"), ("received_quantity", "number"),
        ("receipt_number", "reference"),
    ),
    "rejection_notice": (
        ("invoice_number", "reference"), ("rejection_reason", "text"),
    ),
}

# Values the parser writes when it found nothing. They are sentinels, not
# extractions, and scoring them as recovered values would report a document
# the parser could not read at all as fully extracted.
_NOT_FOUND = {"UNKNOWN", "Reason not stated in the rejection notice.", None, ""}

# What this number does not cover. Printed with every run and carried in the
# JSON report, because an extraction accuracy figure quoted without them would
# be read as a claim about real documents, and it is not one.
LIMITATIONS = (
    "Scope: these are digitally generated PDFs with embedded text, rendered by",
    "scripts/generate_synthetic_pdfs.py. The variation is real — label vocabulary,",
    "value placement, fonts, table vs. rows, money formats, page clutter, and an",
    "unlabelled supplier block — and it is variation this project authored. It does",
    "NOT cover scans, OCR noise, skew, handwriting, multi-page documents, or the",
    "layouts of vendors nobody here has seen. Treat this as a regression measure",
    "over a known population, not as an estimate of accuracy on a real inbox.",
)


def _truth_for(document_type: str, spec: dict) -> dict:
    """What the renderer actually printed on this document."""
    if document_type == "purchase_order":
        return {
            "po_number": spec["po_number"],
            "vendor_name": spec["vendor"],
            "quantity": spec["po_quantity"],
            "unit_price": spec["po_unit_price"],
            "total_amount": spec["po_quantity"] * spec["po_unit_price"],
        }
    if document_type == "vendor_invoice":
        return {
            "invoice_number": spec["invoice_number"],
            "vendor_name": spec["vendor"],
            "po_number": spec["po_number"],
            "quantity": spec["invoice_quantity"],
            "unit_price": spec["invoice_unit_price"],
            "total_amount": spec["invoice_quantity"] * spec["invoice_unit_price"],
            "invoice_date": INVOICE_DATE,
        }
    if document_type == "goods_receipt_note":
        return {
            "po_number": spec["po_number"],
            "received_quantity": spec["received_quantity"],
            "receipt_number": spec["receipt_number"],
        }
    return {
        "invoice_number": spec["invoice_number"],
        "rejection_reason": spec["rejection_reason"],
    }


# The renderer's canonical field name for each parser field, so the eval can
# tell "this layout does not print it" from "the parser did not find it".
_LAYOUT_FIELD = {
    "po_number": "po_number", "invoice_number": "invoice_number",
    "receipt_number": "receipt_number", "vendor_name": "vendor",
    "quantity": "quantity", "unit_price": "unit_price",
    "total_amount": "total_amount", "invoice_date": "invoice_date",
    "received_quantity": "received_quantity", "rejection_reason": "rejection_reason",
}


def _text_key(value) -> str:
    return "".join(ch for ch in str(value or "").lower() if ch.isalnum())


def _compare(kind: str, parsed, expected) -> str:
    """"correct" | "wrong" | "missed"."""
    if parsed in _NOT_FOUND:
        return "missed"
    if kind == "number":
        try:
            return "correct" if abs(float(parsed) - float(expected)) < 0.01 else "wrong"
        except (TypeError, ValueError):
            return "wrong"
    if kind == "date":
        # Any rendering of the same day is correct; the matcher parses these
        # through history_service's tolerant date reader, not by string match.
        return "correct" if _text_key(parsed)[-8:] == _text_key(expected)[-8:] else "wrong"
    if kind == "reference":
        # A reference is right if the printed one is recoverable from what was
        # parsed. Real extractions carry stray prefixes ("Ref: PO-2026-00421")
        # and the matcher normalizes those away before comparing.
        return "correct" if _text_key(expected) in _text_key(parsed) else "wrong"
    parsed_key, expected_key = _text_key(parsed), _text_key(expected)
    if parsed_key == expected_key or expected_key in parsed_key or parsed_key in expected_key:
        return "correct"
    return "wrong"


def evaluate_layout(layout: Layout, work_dir: str) -> list[dict]:
    """Renders every case in one layout, reads it back, and scores each field."""
    out_dir = os.path.join(work_dir, layout.name)
    rows: list[dict] = []

    for case_id, spec in CASES.items():
        written = build_case(case_id, spec, out_dir, layout)
        for file_name in written:
            document_type = file_name.replace(".pdf", "")
            path = os.path.join(out_dir, case_id, file_name)
            with open(path, "rb") as f:
                data = f.read()

            text = extract_text_from_bytes(data)
            classified, classify_confidence = pdf_field_parser.classify_document(text)
            # Parsing is done with the TRUE type rather than the classified
            # one, so a classification failure is reported once as itself
            # instead of cascading into every field on the document and being
            # counted a second time as an extraction failure.
            parsed = pdf_field_parser.parse_document(document_type, text, data)

            for field_name, kind in CHECKS[document_type]:
                expected = _truth_for(document_type, spec).get(field_name)
                layout_field = _LAYOUT_FIELD[field_name]
                # A field is only "absent" when this layout does not put it on
                # the page at all. The unlabelled identity block is the case
                # this distinction exists for: the vendor name IS printed
                # there, just under no label, so it must be scored — treating
                # it as absent would quietly excuse the parser from the
                # hardest field in the set.
                printed = layout_field in layout.labels or (
                    field_name == "vendor_name" and layout.identity_block)
                if expected is None or not printed:
                    outcome = "absent"
                    parsed_value = None
                else:
                    parsed_value = getattr(parsed, field_name, None)
                    outcome = _compare(kind, parsed_value, expected)

                rows.append({
                    "layout": layout.name,
                    "case": case_id,
                    "document_type": document_type,
                    "field": field_name,
                    "expected": expected,
                    "parsed": parsed_value,
                    "outcome": outcome,
                })

            rows.append({
                "layout": layout.name,
                "case": case_id,
                "document_type": document_type,
                "field": "__document_type__",
                "expected": document_type,
                "parsed": classified,
                "outcome": "correct" if classified == document_type else (
                    "missed" if classified is None else "wrong"),
                "confidence": classify_confidence,
            })
    return rows


def _tally(rows: list[dict]) -> dict:
    counts = defaultdict(int)
    for row in rows:
        counts[row["outcome"]] += 1
    scored = counts["correct"] + counts["wrong"] + counts["missed"]
    return {
        "scored": scored,
        "correct": counts["correct"],
        "wrong": counts["wrong"],
        "missed": counts["missed"],
        "absent": counts["absent"],
        "accuracy": round(counts["correct"] / scored, 4) if scored else None,
    }


def score(rows: list[dict]) -> dict:
    field_rows = [r for r in rows if r["field"] != "__document_type__"]
    type_rows = [r for r in rows if r["field"] == "__document_type__"]

    by_layout = {}
    for layout in {r["layout"] for r in rows}:
        by_layout[layout] = _tally([r for r in field_rows if r["layout"] == layout])

    by_field = {}
    for field_name in {r["field"] for r in field_rows}:
        by_field[field_name] = _tally([r for r in field_rows if r["field"] == field_name])

    # The control group and everything else, kept apart. An extractor scored
    # only on the template it was written for is confirming its assumptions.
    baseline_rows = [r for r in field_rows if r["layout"] == "baseline"]
    unseen_rows = [r for r in field_rows if r["layout"] != "baseline"]

    return {
        "layouts": len({r["layout"] for r in rows}),
        "documents": len({(r["layout"], r["case"], r["document_type"]) for r in rows}),
        "overall": _tally(field_rows),
        "baseline_layout": _tally(baseline_rows),
        "unseen_layouts": _tally(unseen_rows),
        "document_classification": _tally(type_rows),
        "by_layout": dict(sorted(by_layout.items(), key=lambda kv: kv[1]["accuracy"] or 0)),
        "by_field": dict(sorted(by_field.items(), key=lambda kv: kv[1]["accuracy"] or 0)),
        "failures": [r for r in rows if r["outcome"] in ("wrong", "missed")],
        "limitations": list(LIMITATIONS),
    }


def run() -> dict:
    work_dir = tempfile.mkdtemp(prefix="proofaegis_extraction_eval_")
    try:
        rows: list[dict] = []
        for layout in LAYOUTS:
            rows.extend(evaluate_layout(layout, work_dir))
        return score(rows)
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


def print_report(report: dict) -> None:
    overall = report["overall"]
    print()
    print(f"  {report['documents']} documents across {report['layouts']} layouts · "
          f"{overall['scored']} field comparisons")
    print()
    print(f"  Field accuracy overall        {overall['accuracy']:.3f}"
          f"   ({overall['wrong']} wrong, {overall['missed']} missed)")
    print(f"    on the baseline layout      {report['baseline_layout']['accuracy']:.3f}"
          f"   (the layout the parser was written against)")
    print(f"    on the four other layouts   {report['unseen_layouts']['accuracy']:.3f}"
          f"   ({report['unseen_layouts']['wrong']} wrong, "
          f"{report['unseen_layouts']['missed']} missed)")
    classification = report["document_classification"]
    print(f"  Document type classification  {classification['accuracy']:.3f}"
          f"   ({classification['scored']} documents)")

    print()
    print(f"  {'layout':<22}{'acc':>8}{'correct':>9}{'wrong':>7}{'missed':>8}")
    print(f"  {'-' * 54}")
    for name, stats in report["by_layout"].items():
        print(f"  {name:<22}{stats['accuracy']:>8.3f}{stats['correct']:>9}"
              f"{stats['wrong']:>7}{stats['missed']:>8}")

    print()
    print(f"  {'field':<22}{'acc':>8}{'correct':>9}{'wrong':>7}{'missed':>8}")
    print(f"  {'-' * 54}")
    for name, stats in report["by_field"].items():
        print(f"  {name:<22}{stats['accuracy']:>8.3f}{stats['correct']:>9}"
              f"{stats['wrong']:>7}{stats['missed']:>8}")

    failures = report["failures"]
    print()
    if not failures:
        print("  Every field recovered correctly in every layout.")
    else:
        print(f"  {len(failures)} failure(s):")
        for row in failures:
            print(f"    [{row['layout']}] {row['document_type']}.{row['field']}"
                  f"  {row['outcome']}: expected {row['expected']!r}, parsed {row['parsed']!r}")
    print()
    print("  A missed field is reported to the user as \"not stated\" and is never compared.")
    print("  A wrong field would flow into a variance, which is why the two are counted apart.")
    print()
    for line in LIMITATIONS:
        print(f"  {line}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Score ProofAegis field extraction across document layouts.")
    parser.add_argument("--json", dest="json_path", default=None,
                        help="Also write the full report as JSON to this path.")
    args = parser.parse_args()

    report = run()
    print_report(report)

    if args.json_path:
        os.makedirs(os.path.dirname(os.path.abspath(args.json_path)), exist_ok=True)
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        print(f"  Wrote {args.json_path}\n")


if __name__ == "__main__":
    main()
