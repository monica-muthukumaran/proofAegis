"""
The guardrail, and the honesty of the figures that describe it.

The override itself was already covered — exception_agent has always replaced
the model's financial impact with the computed one. What was not covered, and
what these tests are actually about, is the REPORTING: a ledger that quietly
counted a Gemini outage as the model agreeing, or folded deliberately injected
faults into a live disagreement rate, would produce a flattering number out of
nothing. That is a worse failure than the guardrail not firing, because it
would be invisible and quotable.

So most of what is asserted here is about what the ledger refuses to count.
"""
import pytest

from schemas import ExceptionReasoning, ExceptionType, MatchResult, Severity
from services import trust_ledger


@pytest.fixture(autouse=True)
def clean_ledger():
    """The ledger is process-local state; tests must not inherit each other's."""
    trust_ledger.reset()
    yield
    trust_ledger.reset()


def record(exception_id, ai_value, computed, *, ai_source="ai", kind="live"):
    return trust_ledger.record(trust_ledger.compare(
        exception_id, ai_value, computed, ai_source=ai_source, kind=kind))


# ---------------------------------------------------------------------------
# The comparison itself
# ---------------------------------------------------------------------------
def test_a_material_difference_is_an_override():
    check = trust_ledger.compare("EXC-1", ai_value=31200.0, computed_value=25000.0)

    assert check.overridden is True
    assert check.difference == 6200.0
    assert check.difference_percent == pytest.approx(24.8)


def test_float_noise_is_not_a_disagreement():
    """A value round-tripped through JSON can move by a fraction of a paisa.
    Reporting that as the model getting the arithmetic wrong would make the
    ledger useless."""
    check = trust_ledger.compare("EXC-1", ai_value=25000.000001, computed_value=25000.0)

    assert check.overridden is False


def test_a_percentage_of_zero_is_absent_rather_than_wrong():
    """An override against a computed zero is real and material. Reporting it
    as 0% or as infinity would both be false, so the percentage is simply not
    stated and the absolute gap carries the meaning."""
    check = trust_ledger.compare("EXC-1", ai_value=900.0, computed_value=0.0)

    assert check.overridden is True
    assert check.difference == 900.0
    assert check.difference_percent is None


# ---------------------------------------------------------------------------
# What the ledger refuses to count
# ---------------------------------------------------------------------------
def test_a_fallback_run_is_not_counted_as_the_model_agreeing():
    """The model did not answer, so there is nothing for it to have agreed
    with. Counting these would manufacture a perfect record out of an outage."""
    record("EXC-1", 25000.0, 25000.0, ai_source="mock")

    summary = trust_ledger.summarize()

    assert summary["model_answered"] == 0
    assert summary["fallback_answered"] == 1
    assert summary["disagreement_rate"] is None


def test_an_injected_fault_never_enters_the_live_disagreement_rate():
    """Fault injections prove the mechanism fires. They are not evidence about
    how often a model is wrong, and adding them to the live totals would be
    exactly that claim."""
    record("EXC-1", 25000.0, 25000.0, ai_source="ai")
    record("EXC-2", 31200.0, 25000.0, ai_source="mock", kind="fault_injection")

    summary = trust_ledger.summarize()

    assert summary["model_answered"] == 1
    assert summary["disagreements"] == 0
    assert summary["disagreement_rate"] == 0.0
    assert summary["fault_injection"] == {"injected": 1, "caught": 1}


def test_an_override_from_any_source_is_still_reported_as_an_override():
    """The counts are kept apart, but the summary must not claim "no override
    required" while one sits in its own recent-overrides table."""
    record("EXC-2", 31200.0, 25000.0, ai_source="mock", kind="fault_injection")

    summary = trust_ledger.summarize()

    assert summary["overrides_applied"] == 1
    assert summary["outcome"] == "deterministic value used"
    assert summary["total_value_corrected"] == 6200.0


def test_the_rate_uses_only_runs_where_a_model_answered():
    record("EXC-1", 25000.0, 25000.0, ai_source="ai")
    record("EXC-2", 40000.0, 25000.0, ai_source="ai")
    record("EXC-3", 25000.0, 25000.0, ai_source="mock")

    summary = trust_ledger.summarize()

    assert summary["model_answered"] == 2
    assert summary["disagreements"] == 1
    assert summary["disagreement_rate"] == 0.5


# ---------------------------------------------------------------------------
# End to end through the agent's guardrail
# ---------------------------------------------------------------------------
def match_result(impact):
    return MatchResult(
        exception_type=ExceptionType.PRICE_VARIANCE,
        comparisons=[], match_score=83,
        financial_impact=impact,
        financial_impact_basis="Variance/unit (250) x quantity (100).",
        recommended_owner="Procurement", risk_level="high",
    )


def reasoning(impact):
    return ExceptionReasoning(
        exception_type=ExceptionType.PRICE_VARIANCE, severity=Severity.HIGH,
        description="…", financial_impact=impact,
        recommended_owner="Procurement", recommended_action="…", confidence=0.9,
    )


def test_the_guardrail_replaces_the_stated_value_and_records_why():
    from services.exception_agent import _enforce_guardrails

    corrected, check = _enforce_guardrails(
        reasoning(31200.0), match_result(25000.0), "EXC-2026-0001", "ai", "live")

    assert corrected.financial_impact == 25000.0
    assert check.overridden is True
    assert check.ai_value == 31200.0, "the record must keep what was STATED"


def test_human_review_is_forced_on_regardless_of_what_the_model_returned():
    from services.exception_agent import _enforce_guardrails

    stated = reasoning(25000.0)
    stated.requires_human_review = False

    corrected, _check = _enforce_guardrails(
        stated, match_result(25000.0), "EXC-2026-0001", "ai", "live")

    assert corrected.requires_human_review is True
