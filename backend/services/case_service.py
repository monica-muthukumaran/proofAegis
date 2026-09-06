"""
case_service.py — glue layer. Routes call these functions instead of
reaching into datastore/matching_service/graph_service directly, so the
computation path (fetch -> match -> graph) has one canonical implementation.
"""
from __future__ import annotations

from typing import Optional

from datastore import get_datastore
from mock_data.generic_mocks import build_reasoning_fallback, build_resolution_fallback
from mock_data.mock_extractions import (
    DOCUMENT_MOCKS,
    FAULT_INJECTED_CASES,
    REASONING_MOCKS,
    RESOLUTION_MOCKS,
)
from schemas import AIResult, EvidenceGraph, MatchResult, TrustCheck
from services import trust_ledger
from services.exception_agent import generate_exception_reasoning
from services.graph_service import build_evidence_graph
from services.hypothesis_agent import generate_hypotheses
from services.matching_service import evaluate_exception


def get_match_result(exception_id: str) -> Optional[MatchResult]:
    ds = get_datastore()
    matching_input = ds.get_matching_input(exception_id)
    if matching_input is None:
        return None
    return evaluate_exception(matching_input, tolerance_for(ds, matching_input))


def tolerance_for(ds, matching_input: dict) -> dict:
    """The tolerance rule that applies to this case.

    A single global percentage cannot be right for both commodity hardware and
    a large services contract, so the settings record may carry per-vendor and
    per-category overrides. The category is derived from the invoice's own
    line items rather than configured, so a rule written for "services"
    applies without anyone tagging each case by hand.
    """
    from services.matching_service import classify_procurement_kind

    category = classify_procurement_kind(
        matching_input.get("invoice_line_items") or matching_input.get("po_line_items"))
    return ds.get_tolerance_rules(
        vendor_name=matching_input.get("vendor_name"), category=category)


def get_evidence_graph(exception_id: str) -> Optional[EvidenceGraph]:
    ds = get_datastore()
    match_result = get_match_result(exception_id)
    if match_result is None:
        return None
    documents = ds.get_documents(exception_id)
    tolerance = tolerance_for(ds, ds.get_matching_input(exception_id) or {})
    source_documents = get_source_documents(exception_id, documents)
    return build_evidence_graph(exception_id, documents, match_result, tolerance, source_documents)


def get_rejection_notice_text(exception_id: str, documents: list[dict]) -> str:
    """Prefers the text actually extracted from an uploaded rejection notice;
    falls back to the seeded mock for the three demo cases; empty string when
    the case simply has no rejection notice (which is allowed)."""
    for doc in documents:
        if doc.get("document_type") == "rejection_notice" and doc.get("extraction"):
            reason = doc["extraction"].get("rejection_reason")
            if reason:
                return reason
    rejection_mock = DOCUMENT_MOCKS.get((exception_id, "rejection_notice"))
    return rejection_mock().rejection_reason if rejection_mock else ""


def get_source_documents(exception_id: str, documents: list[dict]) -> dict:
    """role -> document_id. Uploaded cases record this during ingestion; for
    seeded cases it is derived from the documents on file, so citations
    resolve either way."""
    ds = get_datastore()
    case = ds.get_exception(exception_id) or {}
    recorded = case.get("source_documents") or {}
    if recorded:
        return recorded
    mapping = {}
    for doc in documents:
        doc_type = doc.get("document_type")
        if doc_type and doc_type not in mapping:
            mapping[doc_type] = doc["document_id"]
    return mapping


async def get_exception_reasoning(exception_id: str) -> Optional[AIResult]:
    """FR-007 — Exception Reasoning Agent. Composes the deterministic
    MatchResult with document references and the rejection notice text, per
    Document 5 Component 2's documented input shape.

    The fallback is a deterministic template over the computed MatchResult
    (mock_data/generic_mocks.py) rather than a hand-written constant, so a
    case built from real uploads has a working reasoning path with Gemini
    off — the seeded cases keep their richer hand-written copy."""
    ds = get_datastore()
    match_result = get_match_result(exception_id)
    if match_result is None:
        return None

    documents = ds.get_documents(exception_id)
    document_references = [
        {"document_id": d["document_id"], "document_type": d.get("document_type")} for d in documents
    ]
    rejection_notice_text = get_rejection_notice_text(exception_id, documents)

    seeded = REASONING_MOCKS.get(exception_id)
    fallback_fn = seeded or (lambda: build_reasoning_fallback(match_result, rejection_notice_text))

    result = await generate_exception_reasoning(
        match_result, document_references, rejection_notice_text, fallback_fn, label=exception_id,
        fault_injected=exception_id in FAULT_INJECTED_CASES,
    )
    # The guardrail's own record, stored beside everything else about the
    # case. It is what the detail view's trust row reads, and it is worth
    # keeping whether or not it fired: "checked, agreed" is a fact about this
    # case as much as "checked, overridden" is.
    check = result.data.get("trust_check")
    if check:
        trust_ledger.record_on_case(ds, TrustCheck.model_validate(check))
    return result


def get_resolution_fallback(exception_id: str):
    """Zero-arg callable returning the ResolutionDraft to use when Gemini is
    off or fails. Seeded cases use their hand-written draft; every other case
    gets a cited template built from its own computed figures."""
    ds = get_datastore()
    seeded = RESOLUTION_MOCKS.get(exception_id)
    if seeded:
        return seeded

    match_result = get_match_result(exception_id)
    if match_result is None:
        return None

    exception = ds.get_exception(exception_id) or {}
    documents = ds.get_documents(exception_id)
    case_context = {
        "exception_id": exception_id,
        "invoice_id": exception.get("invoice_id"),
        "vendor_name": exception.get("vendor_name"),
        "currency": exception.get("currency", "INR"),
    }
    source_documents = get_source_documents(exception_id, documents)
    return lambda: build_resolution_fallback(match_result, case_context, source_documents)

def summarize_exception(exception: dict) -> dict:
    """
    Attaches the DERIVED fields the queue and dashboard display — exception
    type, match score, financial impact, risk level, recommended owner — to a
    case record.

    These are deliberately not stored as authoritative columns: they are
    recomputed from matching_service.py on read, so what the queue shows can
    never drift from what the match workspace shows. (The original seed data
    carried hand-picked match scores of 72/78/60 that no code produced; this
    is the fix for that class of problem.)

    A case that cannot be matched yet simply comes back without them, and the
    UI renders that as "awaiting documents" rather than as a zero.
    """
    enriched = dict(exception)

    # A case whose outcome was already computed and stored carries it forward
    # untouched. run_analysis (for uploaded cases) and the portfolio generator
    # (for synthetic ones) are the only writers, so there is exactly one
    # definition of these numbers and no chance of drift. Recomputing every
    # row on every read is what made a 300-record queue slow.
    if enriched.get("exception_type") is not None and enriched.get("match_score") is not None:
        return enriched

    try:
        match_result = get_match_result(exception["exception_id"])
    except Exception:  # noqa: BLE001 — a malformed case must not break the whole queue
        match_result = None
    if match_result is None:
        return enriched
    enriched.update({
        "exception_type": match_result.exception_type.value,
        "match_score": match_result.match_score,
        "financial_impact": match_result.financial_impact,
        "risk_level": match_result.risk_level,
        "assigned_team": match_result.recommended_owner,
    })
    return enriched


async def get_investigation_hypotheses(exception_id: str) -> Optional[AIResult]:
    """FR-007b — the Investigation Hypothesis Agent.

    Hands the computed finding, the documents on file, and what is known about
    this vendor to services/hypothesis_agent.py, which returns ranked candidate
    explanations and the evidence that would settle each one.

    The vendor context is assembled here rather than in the agent because it
    is a portfolio query, and the agent should receive facts rather than a
    datastore. It is deliberately qualitative: no amounts are passed, because
    the agent has no business stating one.
    """
    ds = get_datastore()
    match_result = get_match_result(exception_id)
    if match_result is None:
        return None

    documents = ds.get_documents(exception_id)
    document_types = sorted({d.get("document_type") for d in documents if d.get("document_type")})

    case = ds.get_exception(exception_id) or {}
    history = _vendor_history(ds, case.get("vendor_name"), exception_id)
    history["price_drift"] = match_result.price_drift
    history["recurring"] = any(d.get("confidence") == "recurring"
                               for d in (match_result.duplicate_of or []))

    return await generate_hypotheses(
        match_result, document_types, history, label=exception_id)


def _vendor_history(ds, vendor_name: Optional[str], exclude_exception_id: str) -> dict:
    """This vendor's record across the workspace, counted not judged."""
    from services.analytics_service import vendor_risk
    from services.matching_service import vendor_key

    if not vendor_name:
        return {}
    target = vendor_key(vendor_name)
    ranked = vendor_risk(ds.list_exceptions(), days=365, limit=200)
    for row in ranked.get("vendors", []):
        if vendor_key(row.get("vendor_name")) == target:
            return dict(row)
    return {}
