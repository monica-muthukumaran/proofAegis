"""
trust_ledger.py — the record of every time the deterministic layer checked
the model's arithmetic.

exception_agent.py has always overwritten the model's stated financial impact
with the value matching_service.py computed. That is the right behaviour, and
until now it was completely invisible: it wrote a log line nobody reads and
corrected the number in place. A silent safety net proves nothing. Anyone can
say "our architecture keeps AI out of the arithmetic"; this module is what
turns that sentence into a count.

WHAT IS COUNTED, AND WHAT DELIBERATELY IS NOT

Every check is recorded, agreement included. "The guardrail fired 4 times"
means nothing without the 316 times it did not, and a ledger that only
retained disagreements would be a list of failures with no denominator.

Two things are kept strictly apart, because merging them would be a lie:

  live            a model actually answered and its number was compared.
                  `ai_source` says whether that was Gemini ("ai") or the
                  deterministic fallback ("mock"). Fallback runs are recorded
                  but never counted as the model agreeing — the model did not
                  speak, so there is nothing to agree with. That distinction
                  is the difference between an honest measurement and a
                  fabricated 100%.

  fault_injection a value we corrupted on purpose to demonstrate that the
                  check catches one. Useful, and not evidence about the
                  model. Reported in its own column, never added to the live
                  totals.

MATERIALITY

A float round-trip through JSON can move a value by a fraction of a paisa.
Anything at or below one paisa is agreement; anything above it is a real
disagreement and the deterministic value is used. There is no band in which
the model's number is preferred, at any size of gap, for any reason.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from schemas import TrustCheck

logger = logging.getLogger("proofaegis.trust_ledger")

# Below this, the two numbers are the same number and the difference is
# floating-point noise. Above it, the deterministic value wins.
MATERIAL_DIFFERENCE = 0.01

# Reported alongside the raw count: a disagreement of a rupee on a lakh is
# arithmetic drift, one of 25% is the model inventing a figure. Both are
# overridden identically; only the reporting distinguishes them.
SIGNIFICANT_PERCENT = 1.0

# Process-local. Firestore is the durable home for these once a workspace is
# real (they are ordinary case fields, written by record_on_case below); this
# in-memory list is what makes the portfolio view work in the demo datastore
# and in tests, where there is no Firestore.
_lock = threading.Lock()
_checks: list[TrustCheck] = []


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compare(exception_id: str, ai_value: Optional[float], computed_value: float,
            *, ai_source: str = "mock", kind: str = "live",
            note: Optional[str] = None) -> TrustCheck:
    """
    Builds the record for one comparison. Pure — it decides nothing and
    changes nothing, so the caller can log it, store it, or in the eval
    harness's case accumulate thousands of them without side effects.
    """
    computed = float(computed_value)
    stated = None if ai_value is None else float(ai_value)
    difference = 0.0 if stated is None else abs(stated - computed)
    overridden = difference > MATERIAL_DIFFERENCE

    # A percentage of zero is not a number. An override against a computed
    # zero is real and material, and reporting it as "inf%" or "0%" would both
    # be wrong, so the percentage is simply absent and the absolute gap
    # carries the meaning.
    percent = None
    if stated is not None and computed != 0:
        percent = round(difference / abs(computed) * 100, 4)

    return TrustCheck(
        exception_id=exception_id,
        ai_value=stated,
        computed_value=round(computed, 2),
        difference=round(difference, 2),
        difference_percent=percent,
        overridden=overridden,
        ai_source=ai_source,
        kind=kind,
        checked_at=_now(),
        note=note,
    )


def record(check: TrustCheck) -> TrustCheck:
    """Adds a completed check to the process-local ledger."""
    with _lock:
        _checks.append(check)
    if check.overridden:
        logger.warning(
            "trust_override exception=%s ai_value=%s computed=%s diff=%s source=%s kind=%s",
            check.exception_id, check.ai_value, check.computed_value,
            check.difference, check.ai_source, check.kind,
        )
    return check


def record_on_case(ds, check: TrustCheck) -> None:
    """
    Persists the check onto the case itself, so the detail view can show the
    trust row without consulting a separate store and so the record survives
    in Firestore alongside everything else about the case.

    Failing to write this must never fail the request that produced it: the
    reasoning the user asked for has already been computed, and losing the
    audit row is strictly less bad than losing the answer.
    """
    try:
        ds.update_case_fields(check.exception_id, {"trust_check": check.model_dump()})
    except Exception:  # noqa: BLE001 — see docstring
        logger.exception("trust_check_persist_failed exception=%s", check.exception_id)


def all_checks() -> list[TrustCheck]:
    with _lock:
        return list(_checks)


def reset() -> None:
    """Test-only. The ledger is process-local state and tests must not inherit
    each other's records."""
    with _lock:
        _checks.clear()


# ---------------------------------------------------------------------------
# The ledger, aggregated
# ---------------------------------------------------------------------------
def summarize(checks: Optional[list[TrustCheck]] = None) -> dict:
    """
    The disagreement ledger: how often the model's stated figure diverged from
    the computed one, and what happened every time.

    The answer to "what happened every time" is the same answer every time,
    which is the point of reporting it: the deterministic value was used. The
    interesting number is not the outcome, it is the rate.
    """
    checks = all_checks() if checks is None else checks

    live = [c for c in checks if c.kind == "live"]
    injected = [c for c in checks if c.kind == "fault_injection"]
    # Only runs where a model actually produced a number can tell us anything
    # about the model. Fallback runs are recorded for completeness and
    # excluded from every rate below.
    model_answered = [c for c in live if c.ai_source == "ai"]
    disagreements = [c for c in model_answered if c.overridden]
    significant = [c for c in disagreements
                   if c.difference_percent is None or c.difference_percent > SIGNIFICANT_PERCENT]

    # Every override, whatever produced it. Distinct from `disagreements`,
    # which counts only the ones a live model caused — an injected fault that
    # the check caught is still an override that happened, and reporting
    # "no override required" while one sits in the table below would be a
    # summary contradicting its own evidence.
    all_overrides = [c for c in checks if c.overridden]

    return {
        "checks_recorded": len(checks),
        # Every case the check ran on, including the injected ones. The check
        # genuinely ran on those cases; what they cannot be counted toward is
        # a statement about the model, and the fields below enforce that.
        "cases_checked": len({c.exception_id for c in checks}),
        # The honest denominator.
        "model_answered": len(model_answered),
        "fallback_answered": len([c for c in live if c.ai_source != "ai"]),
        "disagreements": len(disagreements),
        "disagreement_rate": (round(len(disagreements) / len(model_answered), 4)
                              if model_answered else None),
        "significant_disagreements": len(significant),
        "significant_threshold_percent": SIGNIFICANT_PERCENT,
        "overrides_applied": len(all_overrides),
        "largest_disagreement": (
            max((c.difference for c in all_overrides), default=0.0)
        ),
        "total_value_corrected": round(sum(c.difference for c in all_overrides), 2),
        # Every override resolves the same way, by construction.
        "outcome": "deterministic value used" if all_overrides else "no override required",
        "fault_injection": {
            "injected": len(injected),
            "caught": len([c for c in injected if c.overridden]),
        },
        "recent": [c.model_dump() for c in sorted(
            (c for c in checks if c.overridden), key=lambda c: c.checked_at, reverse=True)[:25]],
        "note": (
            "Only runs where a model actually produced a figure count toward the rate. "
            "Deterministic-fallback runs are recorded and excluded — the model did not "
            "state a number, so there is nothing for it to have agreed with. Fault "
            "injections are deliberate corruptions used to prove the check fires; they "
            "are never added to the live totals."
        ),
    }
