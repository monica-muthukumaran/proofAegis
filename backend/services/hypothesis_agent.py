"""
hypothesis_agent.py — the fourth ADK agent, and the only one doing work a
template could not.

WHY THIS EXISTS

The other three agents extract fields, describe a finding in plain language,
and draft a message. Every one of those is replaceable by a template over the
deterministic MatchResult, and two of them already HAVE such a template as
their fallback (mock_data/generic_mocks.py). That is a fair criticism of the
whole AI layer: if the fallback is as good as the model, the model is
decoration.

This agent is given the job a template genuinely cannot do. From a computed
finding — a price variance of 10.42% on this vendor, this order, these line
items — it produces RANKED CANDIDATE EXPLANATIONS, each paired with the
specific evidence that would confirm or rule it out.

    Price variance of 10.42%. Candidate causes:
      (a) the vendor applied a revised rate card — look for a price revision
          notice dated after the order;
      (b) our purchase order carries a stale rate — check the quotation it
          was raised from;
      (c) the wrong line was matched — compare the HSN codes.

Generating that list requires knowing how procurement actually goes wrong,
which is world knowledge rather than arithmetic. Ranking the candidates
requires judgement about which is most likely given this vendor's history.
Naming the document that would settle each one requires knowing what
documents exist and what they contain. A lookup table can enumerate causes
for a price variance; it cannot weigh them against the fact that this
particular vendor has been drifting upward for four months.

THE SAFETY PROPERTY, WHICH IS THE POINT

This agent CANNOT fabricate a number, because it is not asked for one. Every
figure in its input comes from matching_service.py, and its output schema has
no numeric field at all — only text, a rank, and a confidence. There is
nothing here for a guardrail to override, which is a stronger position than
having a guardrail: the failure mode was designed out rather than caught.

It also never concludes. Each hypothesis is a thing to CHECK, with the check
named. "The AI tells you what to look at, the code tells you what is true" is
the boundary, and this is the half of it that a model is actually good at.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import List, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field

from config import config
from schemas import AIResult, MatchResult
from services.ai_fallback import call_gemini_with_fallback

APP_NAME = "proofaegis-hypothesis"
logger = logging.getLogger("proofaegis.hypothesis_agent")


# ---------------------------------------------------------------------------
# Output schema — deliberately free of numbers
# ---------------------------------------------------------------------------
class Hypothesis(BaseModel):
    """One candidate explanation, and how to settle it."""
    rank: int = Field(ge=1, description="1 is most likely given the evidence supplied.")
    cause: str = Field(description="One sentence: what would explain this finding.")
    # What a person should go and look at. Named specifically enough to act
    # on — "the quotation this order was raised from", not "supporting
    # documents".
    evidence_to_check: str
    # What that evidence would look like in each direction, so the check has a
    # decision attached rather than just a task.
    confirms_if: str
    rules_out_if: str
    # Where a reviewer would find it. Free text, because the honest answer is
    # often "a system this product cannot see".
    where_to_look: Optional[str] = None
    likelihood: float = Field(ge=0, le=1)


class HypothesisSet(BaseModel):
    finding: str = Field(description="The computed finding these explain, restated.")
    hypotheses: List[Hypothesis]
    # Anything the model believes would change its ranking if known. Useful
    # precisely because it is an admission of what the evidence does not say.
    what_would_change_this: Optional[str] = None
    # Always true, force-set after generation. Nothing here is a conclusion.
    requires_human_review: bool = True


INSTRUCTION = """You are the Investigation Hypothesis Agent for an Accounts Payable exception tool.

You are given a finding that has ALREADY been computed by deterministic code, together with the
documents on the case and what is known about this vendor's history. The numbers are settled and
are not yours to revisit.

Your job is to produce RANKED CANDIDATE EXPLANATIONS for why this finding exists, and for each one,
the specific evidence that would confirm or rule it out.

Rules:
- Produce 2 to 4 hypotheses, ranked with 1 as most likely given the evidence supplied.
- Each must name a SPECIFIC document, record or system to check — "the quotation this order was
  raised from", "a price revision notice dated after the order", "the HSN codes on both line
  items". Never "supporting documentation" or "relevant records".
- State what confirms it and what rules it out, so the reviewer has a decision, not a chore.
- Use the vendor history you are given. If this vendor has been drifting upward for months, a
  one-off keying error is a WORSE explanation than a rate change, and your ranking must reflect
  that.
- Do NOT state, restate, adjust or invent any monetary amount, percentage, quantity or date. Refer
  to the finding qualitatively. The figures are computed elsewhere and shown next to your output.
- Do NOT conclude. Every hypothesis is a thing to check. You are telling the reviewer where to
  look, not what happened.
- Prefer ordinary explanations. Most exceptions are administrative, not fraudulent. Where a
  finding genuinely has a fraud-shaped explanation (changed bank details, a duplicate), include it
  without dramatising it, and name the out-of-band check that settles it.

Return ONLY the structured fields requested.
"""


def _build_agent() -> LlmAgent:
    return LlmAgent(
        name="investigation_hypothesis_agent",
        model=config.GEMINI_REASONING_MODEL,
        description="Turns a computed finding into ranked candidate explanations and the evidence that would settle each.",
        instruction=INSTRUCTION,
        output_schema=HypothesisSet,
        output_key="hypotheses",
    )


def _vendor_context(history: dict) -> dict:
    """What is known about this vendor, qualitatively.

    Deliberately excludes amounts. The agent is instructed not to state
    figures, and the cheapest way to enforce that is to not hand it any it
    does not need — an instruction not to use a number is weaker than the
    number not being there.
    """
    return {
        "prior_exceptions": history.get("exception_count"),
        "prior_invoices": history.get("invoice_count"),
        "most_common_failure": history.get("top_exception_type"),
        "price_has_been_drifting_upward": bool(history.get("price_drift")),
        "has_recurring_billing_pattern": bool(history.get("recurring")),
    }


async def _run_agent(payload: dict) -> HypothesisSet:
    agent = _build_agent()
    session_service = InMemorySessionService()
    user_id, session_id = "backend", str(uuid.uuid4())
    await session_service.create_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    runner = Runner(agent=agent, app_name=APP_NAME, session_service=session_service)

    message = types.Content(role="user", parts=[types.Part(text=json.dumps(payload))])
    async for _event in runner.run_async(user_id=user_id, session_id=session_id, new_message=message):
        pass

    session = await session_service.get_session(app_name=APP_NAME, user_id=user_id, session_id=session_id)
    return HypothesisSet.model_validate(session.state["hypotheses"])


async def generate_hypotheses(match_result: MatchResult, document_types: list[str],
                              vendor_history: dict, *, label: str) -> AIResult:
    """
    Ranked candidate explanations for a computed finding.

    The fallback (mock_data/hypothesis_fallback.py) is a small catalogue keyed
    on exception type. It is deliberately kept thin and it is worse than the
    model, which is the honest situation and the opposite of the other three
    agents: a canned list cannot weigh a cause against this vendor's history,
    so with Gemini off the user gets generic checks and the UI says so.
    """
    from mock_data.hypothesis_fallback import build_hypothesis_fallback

    payload = {
        "finding": {
            "exception_type": match_result.exception_type.value,
            "what_was_compared": [
                {
                    "field": c.field.value,
                    "result": c.classification.value,
                    "checked": c.evaluable,
                }
                for c in match_result.comparisons
            ],
            "line_level_findings": [
                {"item": line.description, "result": line.classification.value,
                 "only_on": line.only_on}
                for line in match_result.line_comparisons
            ],
            "outstanding": match_result.outstanding,
            "basis_of_the_computed_impact": match_result.financial_impact_basis,
            "needed_other_cases_to_find": match_result.cross_case,
        },
        "documents_on_file": document_types,
        "vendor_context": _vendor_context(vendor_history),
    }

    async def ai_call():
        return await _run_agent(payload)

    result = await call_gemini_with_fallback(
        ai_call,
        lambda: build_hypothesis_fallback(match_result, document_types),
        label=f"hypotheses:{label}",
    )

    # Nothing this agent returns is a conclusion, and the flag says so
    # regardless of what came back.
    hypotheses = HypothesisSet.model_validate(result.data)
    hypotheses.requires_human_review = True
    hypotheses.hypotheses.sort(key=lambda h: h.rank)
    result.data = hypotheses.model_dump()
    return result
