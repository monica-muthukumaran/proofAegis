"""
resolution_agent.py — FR-010 (Resolution Copilot).

Drafts vendor/procurement/receiving correction messages. Critically, this
agent never computes numbers itself — the match_result and evidence graph
passed into the prompt already contain the deterministic financial impact,
variance percentages, and classifications from matching_service.py /
graph_service.py. The agent's job is language, not arithmetic, and the
output_schema (ResolutionDraft) forces every draft to carry structured
citations rather than freeform prose that merely claims to be cited.
"""
from __future__ import annotations

import json
import uuid

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from config import config
from schemas import AIResult, EvidenceGraph, MatchResult, ResolutionDraft
from services.ai_fallback import call_gemini_with_fallback

APP_NAME = "proofaegis-resolution-copilot"

INSTRUCTION = """You are the Resolution Copilot for an Accounts Payable exception-resolution tool.
You draft a short, professional message (vendor correction request, or an internal note to
Procurement/Receiving, depending on recommended_owner) that explains the discrepancy in plain
language and proposes next steps.

Rules:
- Every factual claim in the body (amounts, quantities, variance percentages) MUST correspond to
  a citation in the `citations` list, pointing at the source_document_id and source_field it came from.
- Never state a number that isn't present in the match result you were given.
- Keep the tone factual and non-accusatory — this is a routine exception, not a fraud allegation.
- Always set requires_human_review to true. This draft is reviewed by a human before it is ever sent.
- Return ONLY the structured fields requested: subject, body, citations, recommended_owner,
  requires_human_review.
"""


def _build_agent() -> LlmAgent:
    return LlmAgent(
        name="resolution_copilot_agent",
        model=config.GEMINI_REASONING_MODEL,
        description="Drafts a source-cited resolution message for an invoice exception.",
        instruction=INSTRUCTION,
        output_schema=ResolutionDraft,
        output_key="resolution_draft",
    )


async def _run_resolution_agent(match_result: MatchResult, graph: EvidenceGraph, case_context: dict) -> ResolutionDraft:
    agent = _build_agent()
    session_service = InMemorySessionService()
    user_id, session_id = "backend", str(uuid.uuid4())
    await session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)

    prompt_payload = {
        "case_context": case_context,
        "match_result": match_result.model_dump(),
        "evidence_graph": graph.model_dump(),
    }
    message = types.Content(role="user", parts=[types.Part(text=json.dumps(prompt_payload))])
    async for _event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        pass

    session = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    raw = session.state["resolution_draft"]
    return ResolutionDraft.model_validate(raw)


async def draft_resolution(match_result: MatchResult, graph: EvidenceGraph, case_context: dict, mock_fn) -> AIResult:
    """
    mock_fn: zero-arg callable returning the mock ResolutionDraft for this
    exact case (see mock_data/mock_extractions.py).
    """
    async def ai_call():
        return await _run_resolution_agent(match_result, graph, case_context)

    return await call_gemini_with_fallback(ai_call, mock_fn, label=f"resolution:{case_context.get('exception_id')}")
