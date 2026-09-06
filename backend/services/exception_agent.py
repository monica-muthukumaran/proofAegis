"""
exception_agent.py — FR-007, Document 5 "Component 2 — Exception Reasoning
Agent". This is the piece that was missing from the first build pass: it's
the AI layer that sits between the deterministic Matching Service and the
Resolution Copilot, turning a MatchResult into the severity/description/
recommended_action a human reviewer actually reads in the exception detail
view — the earlier build only produced the raw deterministic MatchResult and
skipped straight to drafting a resolution message from it.

Input (per the doc, verbatim): matching_results, document_references,
rejection_notice_text.
Output: exception_type, severity, description, financial_impact,
recommended_owner, recommended_action, confidence, requires_human_review.

Two guardrails enforce the doc's "Do not use AI alone for arithmetic" rule
even though financial_impact is part of this agent's output schema:

  1. After the agent responds, financial_impact is compared against the
     MatchResult's own value (the actual source of truth). Any mismatch
     beyond float rounding is corrected in place — the agent's number never
     wins over the deterministic one.
  2. requires_human_review is force-set to True regardless of what the model
     returns, same as resolution_agent.py's draft.

Guardrail (1) used to do its work and write a log line, which meant the
single most defensible property of this architecture was invisible to anyone
who was not tailing stderr. Every comparison now produces a TrustCheck —
agreements included, since a fire rate needs a denominator — which is stored
on the case and aggregated into the portfolio disagreement ledger. See
services/trust_ledger.py for what is counted and what is deliberately kept
apart from it.
"""
from __future__ import annotations

import logging
import uuid

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from schemas import AIResult, ExceptionReasoning, MatchResult, TrustCheck
from config import config
from services import trust_ledger
from services.ai_fallback import call_gemini_with_fallback

APP_NAME = "proofaegis-exception-reasoning"
logger = logging.getLogger("proofaegis.exception_agent")

INSTRUCTION = """You are the Exception Reasoning Agent for an Accounts Payable exception-resolution tool.

You are given a deterministic matching_results object (already computed — you must not recompute or
adjust any of its numbers), a list of document_references, and rejection_notice_text.

Your job is judgment and language, not arithmetic:
- severity: low / medium / high / critical, based on the size and nature of the discrepancy.
- description: 1-3 plain-language sentences explaining what's wrong, for a non-technical reviewer.
- recommended_action: one concrete next step.
- confidence: your confidence (0-1) in this classification.
- financial_impact: copy this VALUE EXACTLY from matching_results — do not recalculate it.
- exception_type and recommended_owner: copy from matching_results unless the rejection notice text
  gives a clear, specific reason to refine recommended_owner.
- requires_human_review: always true. This is never used to auto-approve or auto-reject anything.

Return ONLY the structured fields requested.
"""


def _build_agent() -> LlmAgent:
    return LlmAgent(
        name="exception_reasoning_agent",
        model=config.GEMINI_REASONING_MODEL,
        description="Adds severity, plain-language description, and recommended action to a computed match result.",
        instruction=INSTRUCTION,
        output_schema=ExceptionReasoning,
        output_key="exception_reasoning",
    )


async def _run_exception_agent(match_result: MatchResult, document_references: list[dict],
                                rejection_notice_text: str) -> ExceptionReasoning:
    import json

    agent = _build_agent()
    session_service = InMemorySessionService()
    user_id, session_id = "backend", str(uuid.uuid4())
    await session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)

    prompt_payload = {
        "matching_results": match_result.model_dump(),
        "document_references": document_references,
        "rejection_notice_text": rejection_notice_text,
    }
    message = types.Content(role="user", parts=[types.Part(text=json.dumps(prompt_payload))])
    async for _event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        pass

    session = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    raw = session.state["exception_reasoning"]
    return ExceptionReasoning.model_validate(raw)


# The wrong-but-plausible figure used for the guardrail demonstration. It is
# derived from the correct one rather than hard-coded so that it stays wrong
# no matter which case is designated, and it is deliberately in the right
# order of magnitude: a value of 999,999,999 would prove only that the check
# catches absurdities, and a reviewer's real worry is the number that looks
# like it could be right. 25,000 becomes 31,200.
_FAULT_MULTIPLIER = 1.248


def _corrupt(correct_value: float) -> float:
    return round(float(correct_value) * _FAULT_MULTIPLIER, 2)


def _enforce_guardrails(reasoning: ExceptionReasoning, match_result: MatchResult, label: str,
                        ai_source: str, kind: str) -> tuple[ExceptionReasoning, TrustCheck]:
    """
    Runs on EVERY result — AI or mock — so the guardrail is real, not
    decorative, and returns the record of what it found so the check itself
    becomes something the product can show rather than a log line.

    The comparison is made against the value the model stated BEFORE any
    correction, which is why the check is built first and the field assigned
    second. Reading it back afterwards would only ever report agreement.
    """
    check = trust_ledger.compare(
        exception_id=label,
        ai_value=reasoning.financial_impact,
        computed_value=match_result.financial_impact,
        ai_source=ai_source,
        kind=kind,
        note=match_result.financial_impact_basis,
    )
    if check.overridden:
        reasoning.financial_impact = match_result.financial_impact
    reasoning.requires_human_review = True
    return reasoning, trust_ledger.record(check)


async def generate_exception_reasoning(match_result: MatchResult, document_references: list[dict],
                                        rejection_notice_text: str, mock_fn, *, label: str,
                                        fault_injected: bool = False) -> AIResult:
    """
    mock_fn: zero-arg callable returning the mock ExceptionReasoning for this
    exact case (see mock_data/mock_extractions.py).

    fault_injected: this case is a designated guardrail demonstration. Its
    stated financial impact is replaced with a knowingly wrong figure before
    the check runs, so the override fires every time rather than only on the
    rare occasion a live model gets the arithmetic wrong while somebody is
    watching. The resulting check is stamped `fault_injection` and is excluded
    from every statistic about model behaviour — see services/trust_ledger.py.

    The returned AIResult carries the guardrail's own record under
    `trust_check`, so the caller can store it on the case and the UI can show
    what the model said next to what the code computed.
    """
    async def ai_call():
        return await _run_exception_agent(match_result, document_references, rejection_notice_text)

    ai_result = await call_gemini_with_fallback(ai_call, mock_fn, label=f"exception_reasoning:{label}")

    reasoning = ExceptionReasoning.model_validate(ai_result.data)

    kind = "live"
    if fault_injected and config.DEMO_FAULT_INJECTION:
        kind = "fault_injection"
        reasoning.financial_impact = _corrupt(match_result.financial_impact)

    reasoning, check = _enforce_guardrails(reasoning, match_result, label, ai_result.source, kind)
    ai_result.data = reasoning.model_dump()
    ai_result.data["trust_check"] = check.model_dump()
    return ai_result
