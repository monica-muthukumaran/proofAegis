"""
Tests for the thing that does the measuring.

An eval harness that silently stops measuring is worse than no harness: it
keeps printing a number, and the number keeps being quoted. Two failure modes
would do that here, and both are quiet.

  1. THE HARNESS BECOMES A TAUTOLOGY. Ground truth is computed by
     eval/fixtures.py:expected_outcome, which is an independent reading of the
     documented policy. If it ever started deferring to matching_service — a
     tempting refactor, since the two agree — a score of 1.000 would mean
     nothing at all, because the answer key would be a copy of the answers.

  2. THE FIXTURES STOP BEING HARD. The defect catalogue exists to exercise
     every branch, including the negatives: a boundary case inside tolerance
     that must NOT be flagged, and a recurring series that must NOT be called
     a duplicate. A catalogue of only blatant positives reports high recall
     and measures nothing about precision.

These are cheap to assert and they are the reason the reported figures can be
trusted between runs.
"""
import pytest

from eval import fixtures as F
from eval.run_eval import predict, run, score


def test_ground_truth_is_computed_from_the_policy_not_the_matcher():
    """expected_outcome must not import or call the code it grades."""
    import inspect

    source = inspect.getsource(F.expected_outcome)
    for forbidden in ("matching_service", "evaluate_exception", "history_service"):
        assert forbidden not in source, (
            f"expected_outcome references {forbidden} — the answer key must not be "
            f"derived from the thing being answered")


def test_a_variance_inside_tolerance_is_labelled_no_exception():
    """The cases that decide whether a threshold is implemented as documented.
    A generator whose every positive is a blatant 20% breach never reaches the
    boundary."""
    label, why = F.expected_outcome("price_variance", {"percent": 3.0})
    assert label == "no_exception"
    assert "inside" in why

    label, _why = F.expected_outcome("price_variance", {"percent": 7.0})
    assert label == "price_variance"


def test_the_quantity_boundary_uses_the_quantity_tolerance():
    """A 3% quantity variance breaches the 2% quantity tolerance even though
    it would sit inside the 5% price one. Sharing a threshold between the two
    would silently relabel a whole class of case."""
    assert F.expected_outcome("quantity_variance", {"percent": 3.0})[0] == "quantity_variance"
    assert F.expected_outcome("quantity_variance", {"percent": 1.5})[0] == "no_exception"


def test_the_defect_catalogue_carries_its_own_negatives():
    """`recurring_billing` is a NEGATIVE for the duplicate rule — everything it
    looks at matches, and the correct answer is not "duplicate". Without a
    defect like it in the mix, precision on duplicate_invoice is unmeasurable."""
    defects = {name for name, _weight in F.DEFECT_MIX}

    assert "recurring_billing" in defects
    assert F.expected_outcome("recurring_billing", {})[0] == "recurring_suspected"


def test_every_defect_in_the_mix_has_a_policy():
    for name, _weight in F.DEFECT_MIX:
        label, why = F.expected_outcome(name, {"percent": 12.0})
        assert label, name
        assert why, name


def test_an_unknown_defect_raises_rather_than_defaulting():
    """A silent default would label a whole class of case `no_exception` and
    report perfect recall on it."""
    with pytest.raises(ValueError):
        F.expected_outcome("not_a_real_defect", {})


def test_noise_never_changes_the_correct_answer():
    """A 12% price variance is still a price variance when the vendor's name
    is spelled differently. If a document condition could move the label, the
    harness would be scoring the noise instead of the pipeline."""
    portfolio = F.build_portfolio(count=200)
    for fixture in portfolio:
        expected, _why = F.expected_outcome(fixture.defect, fixture.defect_detail)
        assert fixture.expected_type == expected, fixture.case_id


def test_the_fixture_set_contains_both_classes_and_every_type():
    portfolio = F.build_portfolio(count=320)
    labels = {f.expected_type for f in portfolio}

    assert "no_exception" in labels, "precision needs negatives"
    assert len(labels) >= 10, f"too few exception types represented: {sorted(labels)}"
    # Clean invoices must be the majority — exception RATE is the headline
    # metric of the whole analytics story, and a rate needs a denominator.
    clean = sum(1 for f in portfolio if f.expected_type == "no_exception")
    assert clean > len(portfolio) / 2


def test_the_pipeline_scores_the_portfolio_end_to_end():
    """The regression guard. This runs the shipping code — ingestion's
    build_matching_input, the history checks, the matcher — over the labelled
    set, so a change that breaks detection fails here rather than in a demo."""
    report = run(count=200, months=12)

    assert report["cases"] == 200
    assert report["detection"]["recall"] >= 0.95, report["misses"]
    assert report["detection"]["precision"] >= 0.95, report["misses"]
    # The claim the product is making, measured on the same run.
    assert report["cross_case"]["exceptions_found"] > 0


def test_a_deliberately_broken_matcher_is_caught_by_the_harness():
    """The harness has to be able to FAIL. A scorer that reports 1.000 whatever
    the pipeline does is the one bug that would make every other number here
    worthless, so this feeds it a prediction it knows is wrong."""
    rows = [
        {"expected": "price_variance", "predicted": "no_exception",
         "noise": "none", "case_id": "X", "financial_impact": 0, "cross_case": False},
        {"expected": "no_exception", "predicted": "no_exception",
         "noise": "none", "case_id": "Y", "financial_impact": 0, "cross_case": False},
    ]

    report = score(rows)

    assert report["detection"]["recall"] == 0.0
    assert report["per_type"]["price_variance"]["false_negative"] == 1
    assert len(report["misses"]) == 1
