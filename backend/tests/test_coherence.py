"""
test_coherence.py — do these documents describe the same transaction?

The bug this covers was not a missing finding. It was a CONFIDENT WRONG ONE:
an invoice for 100 steel pipes matched against a purchase order for 12 office
chairs was reported as a 211,200 quantity variance at high risk, basis "88
unreceived units x implied unit price". 88 is 100 pipes minus 12 chairs.

`test_the_original_fabricated_finding` is that exact case, and it is the
reason the module exists.

WHAT MOST OF THIS FILE IS ABOUT

Detecting the mismatch is the easy half. The hard half is not detecting one
that is not there, because the two mistakes cost different amounts:

  * A missed mismatch leaves things as they were. The reviewer sees a variance
    and, being a person looking at two documents, notices they are unrelated.
  * A false one sends them to re-upload files that were fine, and the second
    time it happens they stop believing the check.

So `TestItDoesNotCryWolf` is the larger class, and every case in it is a real
shape from accounts payable — partial billing, a rewording, a terse purchase
order, an ordinary overcharge. All of them must come back `consistent` or, at
worst, `unverified`. None may be asserted as contradicted.
"""
from __future__ import annotations

import sys

import pytest

sys.path.insert(0, ".")

from schemas import ExceptionType, MatchClassification  # noqa: E402
from services import coherence_service  # noqa: E402
from services.matching_service import evaluate_exception  # noqa: E402

TOLERANCE = {"price_variance_percent": 5, "quantity_variance_percent": 2}


def case(**overrides) -> dict:
    """A clean, coherent case: one vendor, one order, matching goods.

    Every test below is this case with one thing changed, so a failure names
    the thing that changed rather than leaving a whole fixture to be read.
    """
    base = {
        "vendor_name": "Chennai Industrial Supplies Pvt. Ltd.",
        "po_vendor_name": "Chennai Industrial Supplies Pvt. Ltd.",
        "po_number": "PO-2026-00421",
        "invoice_po_number": "PO-2026-00421",
        "purchase_order_exists": True,
        "goods_receipt_exists": True,
        "po_unit_price": 2400, "invoice_unit_price": 2400,
        "po_quantity": 100, "received_quantity": 100, "invoice_quantity": 100,
        "invoice_amount": 240000, "invoice_total": 240000, "po_total": 240000,
        "invoice_line_items": [
            {"description": "MS steel pipe 50mm", "quantity": 100, "unit_price": 2400, "amount": 240000}],
        "po_line_items": [
            {"description": "MS steel pipe 50mm", "quantity": 100, "unit_price": 2400, "amount": 240000}],
    }
    base.update(overrides)
    return base


OFFICE_CHAIRS = [
    {"description": "Ergonomic office chair, mesh back", "quantity": 12,
     "unit_price": 4500, "amount": 54000}]


# ---------------------------------------------------------------------------
# The bug
# ---------------------------------------------------------------------------
class TestTheFabricatedFinding:
    @pytest.fixture
    def mismatched(self):
        """An invoice for steel pipe beside a purchase order for office
        chairs. Same vendor — a supplier can sell both — and the invoice cites
        the order it was uploaded with, so nothing but the goods themselves
        gives it away."""
        return case(po_line_items=OFFICE_CHAIRS, po_unit_price=4500,
                    po_quantity=12, received_quantity=12, po_total=54000)

    def test_the_original_fabricated_finding(self, mismatched):
        """Before the coherence check this returned quantity_variance,
        211,200, high risk, "88 unreceived units" — 100 pipes minus 12
        chairs."""
        result = evaluate_exception(mismatched, TOLERANCE)
        assert result.exception_type == ExceptionType.UNRELATED_DOCUMENTS
        assert result.exception_type != ExceptionType.QUANTITY_VARIANCE
        assert "88" not in result.financial_impact_basis

    def test_the_impact_is_the_unverified_invoice_not_an_invented_variance(self, mismatched):
        """The whole invoice is unconfirmed, which is a different claim from
        "211,200 was overcharged" — and the only one that is true."""
        result = evaluate_exception(mismatched, TOLERANCE)
        assert result.financial_impact == 240000.0
        assert "nothing on it has been verified" in result.financial_impact_basis

    def test_it_says_what_each_document_is_for(self, mismatched):
        """A reviewer must be able to settle this without opening either
        file."""
        result = evaluate_exception(mismatched, TOLERANCE)
        assert "office chair" in result.outstanding.lower()
        assert "steel pipe" in result.outstanding.lower()

    def test_no_comparison_is_reported_as_a_variance(self, mismatched):
        """The finding would still be undermined if the workspace below it
        showed "unit price: 4,500 vs 2,400, OUTSIDE TOLERANCE" — a precise
        variance between a chair and a pipe."""
        result = evaluate_exception(mismatched, TOLERANCE)
        assert not any(c.classification == MatchClassification.OUTSIDE_TOLERANCE
                       for c in result.comparisons)

    def test_but_the_figures_are_still_shown(self, mismatched):
        """Withdrawn verdict, not withdrawn evidence. Whoever settles this
        needs to see what each document actually said."""
        result = evaluate_exception(mismatched, TOLERANCE)
        price = next(c for c in result.comparisons if c.field.value == "unit_price")
        assert price.expected_value == 4500
        assert price.actual_value == 2400
        assert price.classification == MatchClassification.UNABLE_TO_VERIFY

    def test_the_match_score_does_not_claim_agreement(self, mismatched):
        """This was 100% at one point: with the price and quantity rows
        demoted, the vendor and PO number still matched and scored full marks.
        A case whose headline is "nothing could be compared" cannot show a
        100% match."""
        result = evaluate_exception(mismatched, TOLERANCE)
        assert result.match_score == 0

    def test_a_self_consistent_invoice_does_not_rescue_the_score(self):
        """The second way this reached 100, found by running real PDFs
        through the API rather than a fixture.

        The invoice's own subtotal-plus-tax row survives demotion, correctly:
        it is a statement about one document and it is still true. It is also
        not agreement with anything, so an invoice that adds up beside an
        order for different goods scored a perfect match. A match score is
        about agreement BETWEEN documents, and there is none here.
        """
        result = evaluate_exception(case(
            invoice_po_number="PO-2026-00999",
            invoice_subtotal=203390, tax_amount=36610, invoice_total=240000,
        ), TOLERANCE)
        assert result.exception_type == ExceptionType.UNRELATED_DOCUMENTS
        assert result.match_score == 0
        # And the row itself is still there, still true, still evaluable.
        arithmetic = next(c for c in result.comparisons
                          if c.field.value == "tax_arithmetic")
        assert arithmetic.classification == MatchClassification.MATCHED


    def test_a_stale_variance_does_not_survive_in_a_quiet_column(self, mismatched):
        """Found by reading the rendered page rather than the API response.

        `po_billed_total` is built NON-evaluable when the two sides are on
        different tax bases, and it keeps its computed percentage. The first
        demotion skipped already-non-evaluable rows on the reasoning that they
        had nothing left to withdraw, so the comparison table went on printing
        "Billed against this order — variance 2844.44%" on a case whose
        headline was that nothing could be compared.
        """
        mismatched = dict(mismatched, po_billing={
            "po_number": "PO-2026-00421", "order_value": 9000.0,
            "total_billed": 265000.0, "over_billed_by": 256000.0,
            "invoice_count": 1, "is_over_billed": True,
        })
        result = evaluate_exception(mismatched, TOLERANCE)
        assert result.exception_type == ExceptionType.UNRELATED_DOCUMENTS
        for comparison in result.comparisons:
            if comparison.field.value == "tax_arithmetic":
                continue
            assert comparison.percentage_variance is None, comparison.field
            assert comparison.absolute_variance is None, comparison.field

    def test_the_cumulative_billing_figure_is_withdrawn_too(self, mismatched):
        """It rendered as "Billed against PO-2026-00733, order 9,000, over by
        2,56,000" beside an invoice citing PO-2026-00421. Every figure in that
        sentence was real and none of them were about each other."""
        mismatched = dict(mismatched, po_billing={
            "po_number": "PO-2026-00733", "order_value": 9000.0,
            "total_billed": 265000.0, "over_billed_by": 256000.0,
            "invoice_count": 1, "is_over_billed": True,
        })
        assert evaluate_exception(mismatched, TOLERANCE).po_billing is None

    def test_the_per_line_table_is_withdrawn_too(self, mismatched):
        """A line-by-line comparison of steel pipe against office chairs is a
        list of variances between things that were never comparable."""
        assert evaluate_exception(mismatched, TOLERANCE).line_comparisons == []


# ---------------------------------------------------------------------------
# Not crying wolf — the larger half
# ---------------------------------------------------------------------------
class TestItDoesNotCryWolf:
    def test_a_clean_case_is_consistent(self):
        result = evaluate_exception(case(), TOLERANCE)
        assert result.coherence["verdict"] == coherence_service.CONSISTENT
        assert result.exception_type == ExceptionType.NO_EXCEPTION

    def test_a_partial_billing_worded_differently_is_not_contradicted(self):
        """The case that rules out judging on text alone.

        A purchase order for an "Annual maintenance contract" billed as "AMC
        renewal Q1 FY26" shares no word with its own order. It is the same
        transaction, and the money says so: 30,000 drawn against 120,000 is
        what a quarterly billing looks like.
        """
        result = evaluate_exception(case(
            po_line_items=[{"description": "Annual maintenance contract",
                            "quantity": 1, "unit_price": 120000, "amount": 120000}],
            invoice_line_items=[{"description": "AMC renewal Q1 FY26",
                                 "quantity": 1, "unit_price": 30000, "amount": 30000}],
            po_total=120000, invoice_total=30000, invoice_amount=30000,
            po_unit_price=120000, invoice_unit_price=30000,
            po_quantity=1, received_quantity=1, invoice_quantity=1,
        ), TOLERANCE)
        assert result.coherence["verdict"] != coherence_service.CONTRADICTED
        assert result.exception_type != ExceptionType.UNRELATED_DOCUMENTS

    def test_but_the_rewording_is_still_reported(self):
        """Not contradicted is not the same as unremarked. The reviewer is
        told the descriptions do not match and why it was not asserted."""
        result = evaluate_exception(case(
            po_line_items=[{"description": "Annual maintenance contract",
                            "quantity": 1, "unit_price": 120000, "amount": 120000}],
            invoice_line_items=[{"description": "AMC renewal Q1 FY26",
                                 "quantity": 1, "unit_price": 30000, "amount": 30000}],
            po_total=120000, invoice_total=30000, invoice_amount=30000,
        ), TOLERANCE)
        assert result.coherence["verdict"] == coherence_service.UNVERIFIED
        codes = {s["code"] for s in result.coherence["signals"]}
        assert "no_descriptive_overlap" in codes

    def test_a_terse_purchase_order_raises_nothing(self):
        """"Item A / SKU 4471" against "Mild steel pipe 50mm" has nothing to
        compare. No signal is available, and an unavailable signal must not be
        reported as an absent overlap."""
        result = evaluate_exception(case(
            po_line_items=[{"description": "SKU 4471", "quantity": 100,
                            "unit_price": 2400, "amount": 240000}],
        ), TOLERANCE)
        codes = {s["code"] for s in result.coherence["signals"]}
        assert "unrelated_line_items" not in codes
        assert "no_descriptive_overlap" not in codes

    def test_an_ordinary_overcharge_is_still_an_overcharge(self):
        """Same goods, billed above the ordered rate. A coherence check that
        swallowed this would have removed a real finding to fix a fake one."""
        result = evaluate_exception(case(
            invoice_unit_price=2650, invoice_amount=265000, invoice_total=265000,
            invoice_line_items=[{"description": "MS steel pipe 50mm", "quantity": 100,
                                 "unit_price": 2650, "amount": 265000}],
        ), TOLERANCE)
        assert result.exception_type == ExceptionType.PRICE_VARIANCE
        assert result.coherence["verdict"] == coherence_service.CONSISTENT

    def test_a_large_overcharge_on_matching_goods_is_not_called_unrelated(self):
        """The money test alone would flag this: 4x the order value. The
        descriptions agree, so it is over-billing and is reported as such."""
        result = evaluate_exception(case(
            invoice_unit_price=9600, invoice_amount=960000, invoice_total=960000,
            invoice_line_items=[{"description": "MS steel pipe 50mm", "quantity": 100,
                                 "unit_price": 9600, "amount": 960000}],
        ), TOLERANCE)
        assert result.exception_type != ExceptionType.UNRELATED_DOCUMENTS

    def test_a_document_with_no_line_items_raises_nothing(self):
        result = evaluate_exception(case(po_line_items=[], invoice_line_items=[]), TOLERANCE)
        assert result.coherence["verdict"] == coherence_service.CONSISTENT

    def test_a_missing_purchase_order_has_no_coherence_question(self):
        """Nothing to cross-check against, so the answer is "not checked"
        rather than a verdict dressed up as one."""
        result = evaluate_exception(
            case(purchase_order_exists=False, po_line_items=[]), TOLERANCE)
        assert result.exception_type == ExceptionType.MISSING_PURCHASE_ORDER
        assert result.coherence["checked"] is False

    def test_shared_wording_is_enough_even_when_it_is_partial(self):
        """"Water tank &Plumbing Pipeline work" against "Water tank &Plumbing
        Pipeline" — the real spelling drift this pairing already handles."""
        result = evaluate_exception(case(
            po_line_items=[{"description": "Water tank &Plumbing Pipeline work",
                            "quantity": 100, "unit_price": 2400, "amount": 240000}],
            invoice_line_items=[{"description": "Water tank &Plumbing Pipeline",
                                 "quantity": 100, "unit_price": 2400, "amount": 240000}],
        ), TOLERANCE)
        assert result.coherence["verdict"] == coherence_service.CONSISTENT

    def test_stopwords_alone_do_not_establish_a_relationship(self):
        """Two documents sharing only "supply of" and "charges" share
        nothing. Without the stopword list they would look related."""
        assert coherence_service._tokens("Supply of services and delivery charges") == set()


# ---------------------------------------------------------------------------
# Reference conflicts
# ---------------------------------------------------------------------------
class TestReferenceConflicts:
    def test_an_invoice_citing_a_different_order_is_contradicted(self):
        """The strongest signal there is: both documents state a number and
        the numbers differ. This was already computed during document
        selection and thrown away."""
        result = evaluate_exception(case(invoice_po_number="PO-2026-00999"), TOLERANCE)
        assert result.exception_type == ExceptionType.UNRELATED_DOCUMENTS
        codes = {s["code"] for s in result.coherence["signals"]}
        assert "po_reference_conflict" in codes

    def test_formatting_differences_are_not_conflicts(self):
        """The same order is written three ways across three documents from
        one vendor."""
        for written in ("po 2026 00421", "PO/2026/00421", "po-2026-00421"):
            result = evaluate_exception(case(invoice_po_number=written), TOLERANCE)
            assert result.coherence["verdict"] == coherence_service.CONSISTENT, written

    def test_a_digit_difference_is_a_conflict(self):
        """Punctuation is dropped, digits never are — 00421 and 00422 are
        different orders."""
        result = evaluate_exception(case(invoice_po_number="PO-2026-00422"), TOLERANCE)
        assert result.coherence["verdict"] == coherence_service.CONTRADICTED

    def test_a_goods_receipt_against_another_order_is_contradicted(self):
        result = evaluate_exception(case(receipt_po_number="PO-2026-00777"), TOLERANCE)
        assert result.exception_type == ExceptionType.UNRELATED_DOCUMENTS
        codes = {s["code"] for s in result.coherence["signals"]}
        assert "receipt_reference_conflict" in codes

    def test_an_absent_reference_is_not_a_conflict(self):
        """Absence is not evidence. Plenty of invoices never state an order
        number, and none of them are thereby unrelated to it."""
        result = evaluate_exception(case(invoice_po_number=None), TOLERANCE)
        assert result.coherence["verdict"] != coherence_service.CONTRADICTED

    def test_an_unverified_pairing_is_reported_but_not_asserted(self):
        """ingestion_service pairs on upload recency when nothing carries a
        matching reference. That is worth saying and is not proof."""
        result = evaluate_exception(case(invoice_po_number=None, link_warnings=[{
            "code": "unverified_link", "role": "purchase_order",
            "detail": "The invoice does not state a purchase order number.",
        }]), TOLERANCE)
        assert result.coherence["verdict"] == coherence_service.UNVERIFIED
        assert result.exception_type != ExceptionType.UNRELATED_DOCUMENTS

    def test_one_problem_is_not_counted_twice(self):
        """A reference_mismatch link warning describes the same fact as
        po_reference_conflict, from the selection side. Listing both would
        make one problem look like two pieces of evidence."""
        result = evaluate_exception(case(invoice_po_number="PO-2026-00999", link_warnings=[{
            "code": "reference_mismatch", "role": "purchase_order",
            "detail": "The invoice cites PO-2026-00999 but no uploaded purchase order carries it.",
        }]), TOLERANCE)
        codes = [s["code"] for s in result.coherence["signals"]]
        assert codes.count("reference_mismatch") == 0
        assert codes.count("po_reference_conflict") == 1


# ---------------------------------------------------------------------------
# What still outranks it
# ---------------------------------------------------------------------------
class TestFindingsThatSurvive:
    """Every finding that is a statement about the INVOICE — checked against
    the vendor's history or against itself — is still true when the wrong
    purchase order is sitting beside it. Telling a reviewer to check their
    uploads instead of stopping a duplicate payment would be a worse answer,
    not a more precise one."""

    def test_a_duplicate_invoice_still_outranks_it(self):
        result = evaluate_exception(case(
            invoice_po_number="PO-2026-00999",
            duplicate_of=[{"confidence": "exact", "reason": "Same vendor and invoice number.",
                           "exception_id": "EXC-2026-0009"}],
        ), TOLERANCE)
        assert result.exception_type == ExceptionType.DUPLICATE_INVOICE

    def test_but_a_surviving_finding_does_not_keep_the_fabricated_figures(self):
        """Two separate questions, and running them as one was a bug.

        "Is this arithmetic trustworthy" and "which finding do we report" have
        different answers here. A duplicate outranks an incoherence — it is
        true whichever order sits beside it — and that says nothing about the
        comparison table underneath, which is still measuring this invoice
        against the wrong order. The duplicate finding was reported correctly
        above a panel reading "Billed against PO-2026-00733, over by
        2,56,000" for an invoice citing PO-2026-00421.
        """
        result = evaluate_exception(case(
            invoice_po_number="PO-2026-00999",
            duplicate_of=[{"confidence": "exact", "reason": "Same vendor and invoice number.",
                           "exception_id": "EXC-2026-0009"}],
            po_billing={"po_number": "PO-2026-00421", "order_value": 9000.0,
                        "total_billed": 265000.0, "over_billed_by": 256000.0,
                        "invoice_count": 1, "is_over_billed": True},
        ), TOLERANCE)
        # The finding stands...
        assert result.exception_type == ExceptionType.DUPLICATE_INVOICE
        # ...and every cross-document figure under it is withdrawn.
        assert result.po_billing is None
        assert result.line_comparisons == []
        assert result.match_score == 0
        assert not any(c.classification == MatchClassification.OUTSIDE_TOLERANCE
                       for c in result.comparisons)
        # And the reviewer is still told why, on a finding that is not itself
        # about the documents disagreeing.
        assert result.coherence["verdict"] == coherence_service.CONTRADICTED

    def test_changed_payment_details_still_outrank_it(self):
        result = evaluate_exception(case(
            invoice_po_number="PO-2026-00999",
            payment_detail_changes=[{"detail": "Bank account differs from this vendor's last invoice."}],
        ), TOLERANCE)
        assert result.exception_type == ExceptionType.PAYMENT_DETAILS_CHANGED

    def test_an_invoice_that_does_not_add_up_still_outranks_it(self):
        """Broken arithmetic on the invoice is true whatever sits next to
        it, and has to be fixed before anything can be compared anyway."""
        result = evaluate_exception(case(
            invoice_po_number="PO-2026-00999",
            invoice_subtotal=200000, tax_amount=36000, invoice_total=300000,
        ), TOLERANCE)
        assert result.exception_type == ExceptionType.TAX_TOTAL_MISMATCH

    def test_but_a_clean_result_does_not_survive(self):
        """The most dangerous sentence in the product: "every comparison
        passed, this invoice is payable", said about two documents that
        describe different orders."""
        result = evaluate_exception(case(invoice_po_number="PO-2026-00999"), TOLERANCE)
        assert result.exception_type == ExceptionType.UNRELATED_DOCUMENTS
        assert result.exception_type != ExceptionType.NO_EXCEPTION

    def test_and_neither_does_a_vendor_mismatch(self):
        """A vendor difference on documents that otherwise agree is a
        possible payment diversion and stays VENDOR_MISMATCH. On documents
        already shown to describe different orders, "confirm these two
        businesses are the same" sends the reviewer down a fraud path when
        the answer is that the wrong file was uploaded."""
        mixed = case(invoice_po_number="PO-2026-00999",
                     po_vendor_name="Southern Office Systems")
        assert evaluate_exception(mixed, TOLERANCE).exception_type == \
            ExceptionType.UNRELATED_DOCUMENTS

        coherent = case(po_vendor_name="Southern Office Systems")
        assert evaluate_exception(coherent, TOLERANCE).exception_type == \
            ExceptionType.VENDOR_MISMATCH

    def test_the_vendor_difference_is_still_in_the_evidence(self):
        """Outranked is not discarded — it is the reviewer's next question."""
        result = evaluate_exception(case(invoice_po_number="PO-2026-00999",
                                          po_vendor_name="Southern Office Systems"), TOLERANCE)
        codes = {s["code"] for s in result.coherence["signals"]}
        assert "different_vendor" in codes


# ---------------------------------------------------------------------------
# Every result carries the answer
# ---------------------------------------------------------------------------
class TestCoherenceIsAlwaysReported:
    def test_a_clean_result_says_the_documents_were_checked(self):
        """"We checked that these belong together and they do" is what makes
        the variance beneath it trustworthy, and it is exactly the fact that
        was missing before."""
        result = evaluate_exception(case(), TOLERANCE)
        assert result.coherence["checked"] is True
        assert result.coherence["summary"]

    @pytest.mark.parametrize("variant,expected", [
        ({}, ExceptionType.NO_EXCEPTION),
        ({"invoice_unit_price": 2650, "invoice_amount": 265000,
          "invoice_line_items": [{"description": "MS steel pipe 50mm", "quantity": 100,
                                  "unit_price": 2650, "amount": 265000}]},
         ExceptionType.PRICE_VARIANCE),
        ({"goods_receipt_exists": False, "received_quantity": None},
         ExceptionType.MISSING_GOODS_RECEIPT),
        ({"invoice_po_number": "PO-2026-00999"}, ExceptionType.UNRELATED_DOCUMENTS),
    ])
    def test_every_outcome_carries_a_verdict(self, variant, expected):
        """Applied at the exit rather than as one more branch in a cascade of
        fourteen returns, so no result can be produced without it."""
        result = evaluate_exception(case(**variant), TOLERANCE)
        assert result.exception_type == expected
        assert result.coherence is not None
        assert result.coherence["verdict"] in (
            coherence_service.CONSISTENT, coherence_service.UNVERIFIED,
            coherence_service.CONTRADICTED)
