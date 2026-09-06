"""
ai_fallback.py — the concrete mechanism behind FR-013 (mock mode) and
FR-014 (error handling), replacing what the original pack described only as
prose ("add retry, add mock fallback").

Every AI call site (document_agent.py, resolution_agent.py) goes through
`call_gemini_with_fallback`. It:

  1. Skips the AI call entirely and returns mock data when config.USE_MOCK_DATA
     is set (or credentials are absent) — this is the demo-safety default.
  2. Otherwise calls the given async ADK function, with one retry and a hard
     timeout.
  3. On ANY failure — network error, timeout, or pydantic ValidationError from
     an ADK output_schema mismatch — logs the reason and falls back to mock
     data rather than surfacing a raw exception to the user.

The caller always gets back an AIResult with `source` set to "ai" or "mock",
so the UI can render the mock-mode indicator required by FR-013/FR-014
honestly, not decoratively.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from pydantic import BaseModel, ValidationError

from config import config
from schemas import AIResult

logger = logging.getLogger("proofaegis.ai_fallback")


async def call_gemini_with_fallback(
    ai_call: Callable[[], Awaitable[BaseModel]],
    mock_fn: Callable[[], BaseModel],
    *,
    label: str,
) -> AIResult:
    """
    ai_call: zero-arg async callable that runs the ADK agent and returns a
             validated pydantic model (raises on failure).
    mock_fn: zero-arg sync callable that returns the mock pydantic model for
             this exact case — always defined, never allowed to fail.
    label:   short string used only for logging (e.g. "document_extraction:INV-2026-1187").
    """
    if config.USE_MOCK_DATA:
        logger.info("mock_mode_active call=%s", label)
        return AIResult(source="mock", data=mock_fn().model_dump())

    last_error: Exception | None = None
    attempts = config.AI_CALL_MAX_RETRIES + 1
    for attempt in range(1, attempts + 1):
        try:
            result = await asyncio.wait_for(ai_call(), timeout=config.AI_CALL_TIMEOUT_SECONDS)
            return AIResult(source="ai", data=result.model_dump())
        except asyncio.TimeoutError as exc:
            last_error = exc
            logger.warning("ai_call_timeout call=%s attempt=%s/%s", label, attempt, attempts)
        except ValidationError as exc:
            last_error = exc
            logger.warning("ai_call_schema_invalid call=%s attempt=%s/%s error=%s", label, attempt, attempts, exc)
        except Exception as exc:  # noqa: BLE001 — genuinely must catch-all here; this IS the safety net
            last_error = exc
            logger.warning("ai_call_failed call=%s attempt=%s/%s error=%s", label, attempt, attempts, exc)

    logger.error("ai_call_exhausted_falling_back_to_mock call=%s error=%s", label, last_error)
    return AIResult(source="mock", data=mock_fn().model_dump(), error=str(last_error) if last_error else None)
