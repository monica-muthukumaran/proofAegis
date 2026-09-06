"""
portfolio_agent.py — the fifth agent, and the only one that reads data itself.

WHAT MAKES THIS DIFFERENT FROM THE OTHER FOUR

The extraction, exception, resolution and hypothesis agents are all handed
their input. Something upstream decided what mattered, computed it, and put
it in the prompt. That is the right shape for a question about ONE case,
because the case is already in front of us.

It is the wrong shape for "which vendors should I audit this quarter?" That
question has no fixed input. Answering it means deciding which aggregation
to run and over what window — and then reading real rows.

So this agent gets tools instead of a prompt full of numbers. Via MCP Toolbox
for Databases it can call the five analytics in backend/mcp/tools.yaml, each
of which is a parameterised statement against the same BigQuery table the
analytics screen reads.

THE BOUNDARY, HELD ONE LAYER LOWER

The other agents cannot fabricate a figure because a guardrail compares
theirs against the computed one (services/trust_ledger.py). This agent cannot
fabricate one for a stronger reason: **there is no tool that accepts SQL.**

It chooses a question and a window. It cannot compose a new aggregation, so
every number in its answer came out of a statement a human wrote and a test
covers. An agent with `run_sql(query)` would be able to compute a figure, and
a figure a model composed is a figure a model can get wrong.

That is why tools.yaml has five named tools and not one `query` tool. It is
the same sentence as everywhere else in this system — a number a human acts
on never comes from a model — enforced at the data layer rather than checked
afterwards.

WHAT IT IS ALLOWED TO DO

Narrate, rank, and connect. "These three vendors account for most of the
open value, and all three fail the same way, which suggests the tolerance on
that category is wrong" is judgement over figures it read. That is the work.

DEGRADED MODE

If the Toolbox server is unreachable the agent is NOT run against a
substitute. It returns unavailable, and the caller says so. An agent that
answers a portfolio question from memory when its tools are down produces
confident prose with no data behind it, which is the exact failure this
product is built to argue against.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from config import config

logger = logging.getLogger("proofaegis.portfolio_agent")

APP_NAME = "proofaegis-portfolio"

# The toolset named in mcp/tools.yaml. Asking for a named set rather than
# every tool on the server means a server that later gains a write tool does
# not silently hand it to a read-only agent.
TOOLSET = "proofaegis-analytics"

MANIFEST_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mcp", "tools.yaml")

INSTRUCTION = """\
You are a controls analyst for an accounts payable team. You answer questions
about the invoice portfolio by CALLING the tools available to you and reading
what they return.

Rules, in order of importance:

1. Never state a number that did not come out of a tool call. If you need a
   figure you do not have, call a tool. If no tool provides it, say that the
   figure is not available rather than estimating one.
2. Never describe a trend, rate or total you have not read. "Rising" requires
   the trend tool.
3. Say which window your answer covers. A figure without its period is not an
   answer a controller can act on.
4. Prefer money over counts when ranking, and say what is still open rather
   than what has already been resolved.
5. You may reason about what the figures MEAN — which vendors to look at
   first, whether several findings share a cause, what to check next. That is
   what you are for. Keep it separate from the figures themselves.

If a tool returns no rows, say so plainly. Do not fill the gap.
"""


class ToolboxUnavailable(RuntimeError):
    """The Toolbox server could not be reached, or the toolset is not loaded."""


def is_configured() -> bool:
    """Whether an attempt is even worth making. Checked before running so the
    caller can render 'not configured' rather than an error."""
    return bool(config.MCP_TOOLBOX_URL) and bool(config.GEMINI_API_KEY)


def _load_tools() -> list:
    """Fetch the toolset from the Toolbox server.

    Imported lazily, like every other optional dependency here: a checkout
    with no toolbox-core installed must still run the app and the tests.
    """
    try:
        from toolbox_core import ToolboxSyncClient  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ToolboxUnavailable(
            "toolbox-core is not installed. pip install -r requirements.txt"
        ) from exc

    try:
        client = ToolboxSyncClient(config.MCP_TOOLBOX_URL)
        tools = client.load_toolset(TOOLSET)
    except Exception as exc:  # pragma: no cover - depends on a live server
        raise ToolboxUnavailable(
            f"MCP Toolbox at {config.MCP_TOOLBOX_URL} is unreachable: {exc}"
        ) from exc

    if not tools:
        raise ToolboxUnavailable(f"toolset '{TOOLSET}' loaded no tools")
    return tools


def build_agent(tools: Optional[list] = None):
    """The ADK agent, with the Toolbox tools attached.

    Separated from `ask` so a test can build it with stub tools and assert the
    wiring without a server or an API key.
    """
    from google.adk.agents import LlmAgent  # noqa: PLC0415

    return LlmAgent(
        name="portfolio_analyst",
        model=config.GEMINI_REASONING_MODEL,
        instruction=INSTRUCTION,
        tools=tools if tools is not None else _load_tools(),
    )


def ask(question: str, timeout: Optional[float] = None) -> dict[str, Any]:
    """Answer a portfolio question, or explain why it cannot be answered.

    Returns a dict rather than raising, because the caller is an HTTP route
    and 'the tools are down' is a real answer that the UI should render as
    itself — not as a 500, and never as an answer composed without data.
    """
    if not is_configured():
        return {
            "available": False,
            "reason": "not_configured",
            "detail": ("MCP_TOOLBOX_URL and GEMINI_API_KEY must both be set. "
                       "See DEPLOYMENT_GUIDE.md, MCP Toolbox."),
        }

    import uuid  # noqa: PLC0415

    from google.adk.runners import Runner  # noqa: PLC0415
    from google.adk.sessions import InMemorySessionService  # noqa: PLC0415
    from google.genai import types  # noqa: PLC0415

    try:
        tools = _load_tools()
    except ToolboxUnavailable as exc:
        logger.warning("portfolio agent unavailable: %s", exc)
        return {
            "available": False,
            "reason": "toolbox_unreachable",
            # Deliberately no answer field. See the module docstring: an
            # agent that answers from memory when its tools are down is the
            # failure this product argues against.
            "detail": str(exc),
        }

    agent = build_agent(tools)
    session_service = InMemorySessionService()
    session_id = f"portfolio-{uuid.uuid4().hex[:12]}"
    user_id = "portfolio-analyst"
    session_service.create_session_sync(
        app_name=APP_NAME, user_id=user_id, session_id=session_id)

    runner = Runner(agent=agent, app_name=APP_NAME,
                    session_service=session_service)

    answer_parts: list[str] = []
    tool_calls: list[str] = []
    try:
        for event in runner.run(
            user_id=user_id,
            session_id=session_id,
            new_message=types.Content(
                role="user", parts=[types.Part(text=question)]),
        ):
            for call in (event.get_function_calls() or []):
                tool_calls.append(call.name)
            if event.is_final_response() and event.content and event.content.parts:
                answer_parts.extend(
                    part.text for part in event.content.parts if part.text)
    except Exception as exc:  # pragma: no cover - depends on a live model
        logger.exception("portfolio agent run failed")
        return {"available": False, "reason": "run_failed", "detail": str(exc)}

    answer = "\n".join(p.strip() for p in answer_parts if p).strip()

    return {
        "available": True,
        "question": question,
        "answer": answer,
        # Which tools actually ran. Surfaced rather than logged, because it is
        # the evidence that the answer came from data: an answer with an empty
        # tool list is prose, and the UI labels it as such.
        "tools_called": tool_calls,
        "grounded": bool(tool_calls),
        "toolset": TOOLSET,
        "engine": "bigquery-via-mcp-toolbox",
    }
