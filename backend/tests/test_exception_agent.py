"""
Validates services/exception_agent.py — both the normal mock-mode path and,
more importantly, the financial_impact guardrail: a reasoning result must
never be allowed to disagree with the deterministic MatchResult's number,
even if something (a bad mock, a bad live call) tries to.
"""
import asyncio
import json
import os

import pytest

from schemas import ExceptionReasoning, Severity
from services.exception_agent import generate_exception_reasoning
from services.matching_service import evaluate_exception

SEED_PATH = os.path.join(os.path.dirname(__file__), "..", "mock_data", "seed_cases.json")
with open(SEED_PATH) as f:
    SEED = json.load(f)
TOLERANCE = SEED["tolerance_rules"]
CASES = {c["exception_id"]: c["matching_input"] for c in SEED["cases"]}


def run(coro):
    return asyncio.run(coro)


def test_mock_reasoning_matches_deterministic_financial_impact_case_a():
    from mock_data.mock_extractions import mock_reasoning_0001

    match_result = evaluate_exception(CASES["EXC-2026-0001"], TOLERANCE)
    ai_result = run(generate_exception_reasoning(
        match_result, document_references=[], rejection_notice_text="", mock_fn=mock_reasoning_0001,
        label="EXC-2026-0001",
    ))
    assert ai_result.source == "mock"
    assert ai_result.data["financial_impact"] == pytest.approx(match_result.financial_impact, abs=0.01)
    assert ai_result.data["severity"] == "high"
    assert ai_result.data["requires_human_review"] is True


def test_guardrail_overrides_a_wrong_financial_impact():
    """The core regression test: even if the 'AI' (here, a deliberately wrong
    mock standing in for a bad live response) returns the wrong number, the
    deterministic MatchResult's financial_impact must win."""
    match_result = evaluate_exception(CASES["EXC-2026-0001"], TOLERANCE)  # true impact = 25000

    def bad_mock() -> ExceptionReasoning:
        return ExceptionReasoning(
            exception_type=match_result.exception_type,
            severity=Severity.LOW,  # also deliberately wrong, just checking the number here
            description="A deliberately wrong description for the regression test.",
            financial_impact=999999,  # WRONG on purpose
            recommended_owner="Nobody",
            recommended_action="N/A",
            confidence=0.5,
        )

    ai_result = run(generate_exception_reasoning(
        match_result, document_references=[], rejection_notice_text="", mock_fn=bad_mock,
        label="EXC-2026-0001",
    ))
    assert ai_result.data["financial_impact"] == pytest.approx(25000, abs=0.01)
    assert ai_result.data["financial_impact"] != 999999


def test_requires_human_review_is_always_forced_true():
    match_result = evaluate_exception(CASES["EXC-2026-0003"], TOLERANCE)

    def mock_claiming_no_review_needed() -> ExceptionReasoning:
        return ExceptionReasoning(
            exception_type=match_result.exception_type, severity=Severity.LOW,
            description="test", financial_impact=match_result.financial_impact,
            recommended_owner="Nobody", recommended_action="N/A", confidence=0.99,
            requires_human_review=False,  # a model should never get away with setting this
        )

    ai_result = run(generate_exception_reasoning(
        match_result, document_references=[], rejection_notice_text="",
        mock_fn=mock_claiming_no_review_needed, label="EXC-2026-0003",
    ))
    assert ai_result.data["requires_human_review"] is True


def test_all_three_seeded_cases_have_working_mocks():
    from mock_data.mock_extractions import REASONING_MOCKS

    for exception_id, matching_input in CASES.items():
        match_result = evaluate_exception(matching_input, TOLERANCE)
        mock_fn = REASONING_MOCKS[exception_id]
        ai_result = run(generate_exception_reasoning(
            match_result, document_references=[], rejection_notice_text="", mock_fn=mock_fn,
            label=exception_id,
        ))
        assert ai_result.data["financial_impact"] == pytest.approx(match_result.financial_impact, abs=0.01)
