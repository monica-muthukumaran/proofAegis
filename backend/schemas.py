"""
Pydantic models used in two places:

1. As `output_schema` on the ADK LlmAgents in services/document_agent.py and
   services/resolution_agent.py — ADK validates the model's final response
   against these at the framework level (raises pydantic.ValidationError on
   drift), which is what lets call_gemini_with_fallback treat "bad AI output"
   and "AI unreachable" the same way: both fall back to mock data.
2. As the shape of API responses, so the frontend gets a stable contract.
"""
from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# FR-006 classifications
# ---------------------------------------------------------------------------
class MatchClassification(str, Enum):
    MATCHED = "matched"
    WITHIN_TOLERANCE = "within_tolerance"
    OUTSIDE_TOLERANCE = "outside_tolerance"
    MISSING = "missing"
    UNABLE_TO_VERIFY = "unable_to_verify"
    REQUIRES_HUMAN_REVIEW = "requires_human_review"


# ---------------------------------------------------------------------------
# FR-011 status workflow
# ---------------------------------------------------------------------------
class SystemStatus(str, Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    EXCEPTION_DETECTED = "exception_detected"
    ASSIGNED = "assigned"
    # Terminal, pipeline-set: the three-way match found nothing outside
    # tolerance. Not every invoice is a problem, and a system that can only
    # ever report problems gives a reviewer no way to judge whether it
    # discriminates. A cleared case still carries its full evidence chain —
    # that chain is the proof the invoice is payable.
    CLEARED = "cleared"


class UserStatus(str, Enum):
    AWAITING_PROCUREMENT = "awaiting_procurement"
    AWAITING_RECEIVING = "awaiting_receiving"
    AWAITING_VENDOR = "awaiting_vendor"
    APPROVED_WITH_EXCEPTION = "approved_with_exception"
    RESOLVED = "resolved"
    CLOSED = "closed"


USER_SETTABLE_STATUSES = {s.value for s in UserStatus}
SYSTEM_SET_STATUSES = {s.value for s in SystemStatus}
ALL_STATUSES = USER_SETTABLE_STATUSES | SYSTEM_SET_STATUSES


class ExceptionType(str, Enum):
    # Every comparison agreed or fell within tolerance. Previously this case
    # returned PRICE_VARIANCE as a placeholder with a comment telling callers
    # to check match_score instead — nothing did, so a clean invoice was
    # displayed to an analyst as a price variance.
    NO_EXCEPTION = "no_exception"
    PRICE_VARIANCE = "price_variance"
    QUANTITY_VARIANCE = "quantity_variance"
    MISSING_GOODS_RECEIPT = "missing_goods_receipt"
    MISSING_PURCHASE_ORDER = "missing_purchase_order"
    VENDOR_MISMATCH = "vendor_mismatch"
    TAX_TOTAL_MISMATCH = "tax_total_mismatch"
    DUPLICATE_INVOICE = "duplicate_invoice"
    # Several invoices that each pass on their own and together exceed the
    # order they are billed against. Invisible to any single-case check.
    PO_OVER_BILLED = "po_over_billed"
    # The vendor's bank details differ from their previous invoice. Reported,
    # never adjudicated — see history_service's boundary note.
    PAYMENT_DETAILS_CHANGED = "payment_details_changed"
    # Same vendor, same amount, on a regular beat. This is what a rent
    # payment, retainer, AMC or subscription looks like to a duplicate check,
    # and reporting every one of them as DUPLICATE_INVOICE — the highest
    # priority finding there is — is the fastest way to lose an AP reviewer's
    # trust. Still reported, because a duplicate can hide inside a recurring
    # series; reported far lower, because most of the time it is the rent.
    RECURRING_SUSPECTED = "recurring_suspected"
    # A unit price climbing steadily across a vendor's invoices, each rise
    # inside tolerance and the cumulative rise well outside it. The price
    # equivalent of PO_OVER_BILLED, and equally invisible per invoice.
    VENDOR_PRICE_DRIFT = "vendor_price_drift"


# The exception types that CANNOT be reached by looking at one case's
# documents, however carefully. Every one of them needs a query across the
# rest of the workspace (services/history_service.py), and every one of them
# fires on invoices whose own three-way match is clean.
#
# This set is the product's actual claim, so it is declared once and counted
# from here — analytics reports "what a per-invoice system would have missed"
# by partitioning the portfolio on this membership, rather than by three
# separate hand-maintained lists drifting apart in three files.
CROSS_CASE_EXCEPTION_TYPES = frozenset({
    ExceptionType.DUPLICATE_INVOICE,
    ExceptionType.PO_OVER_BILLED,
    ExceptionType.PAYMENT_DETAILS_CHANGED,
    ExceptionType.RECURRING_SUSPECTED,
    ExceptionType.VENDOR_PRICE_DRIFT,
})

CROSS_CASE_TYPE_VALUES = frozenset(t.value for t in CROSS_CASE_EXCEPTION_TYPES)


# ---------------------------------------------------------------------------
# FR-004 field extraction — one schema per document type. These ARE the
# output_schema passed to the ADK extraction agent, so the model's response
# is structurally guaranteed (or it fails validation and mock fallback fires).
# ---------------------------------------------------------------------------
class ExtractionConfidence(BaseModel):
    field_name: str
    confidence: float = Field(ge=0, le=1)


class LineItem(BaseModel):
    """One row of a document's item table.

    Real purchase orders and invoices are multi-line: the plumbing PO that
    exposed this carried three (16,000 + 22,000 + 15,000). Forcing a
    multi-line document into a single `quantity`/`unit_price` pair did not
    merely lose detail, it produced wrong numbers — the extractor returned
    quantity=3, which is the row COUNT, next to the first row's unit price.
    A downstream tolerance check on those two values is arithmetic on
    fiction, so the rows are now kept as rows.
    """
    description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    hsn_sac: Optional[str] = None


class InvoiceExtraction(BaseModel):
    invoice_number: str
    vendor_name: str
    po_number: Optional[str] = None
    invoice_date: Optional[str] = None
    line_items: List[LineItem] = Field(default_factory=list)
    # Kept for the single-line case and for every existing consumer of this
    # schema. They are None — not zero, and not a row count — whenever the
    # document has several rows and no single value is truthful. A comparison
    # against None is reported as "missing", which is the honest outcome.
    line_item_description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: float
    # Payment instructions as printed on THIS invoice. Stored so a change
    # against the vendor's previous invoice can be detected — see
    # services/history_service.py, which reports the change and deliberately
    # does not judge whether the new account is legitimate.
    bank_account_number: Optional[str] = None
    bank_ifsc: Optional[str] = None
    bank_name: Optional[str] = None
    # Tax identity, used to check the invoice is from who it claims and to
    # verify tax arithmetic.
    vendor_tax_id: Optional[str] = None
    field_confidences: List[ExtractionConfidence] = Field(default_factory=list)


class PurchaseOrderExtraction(BaseModel):
    po_number: str
    vendor_name: str
    line_items: List[LineItem] = Field(default_factory=list)
    line_item_description: Optional[str] = None
    quantity: Optional[float] = None
    unit_price: Optional[float] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: float
    field_confidences: List[ExtractionConfidence] = Field(default_factory=list)


class GoodsReceiptExtraction(BaseModel):
    receipt_number: Optional[str] = None
    po_number: str
    received_quantity: float
    receipt_date: Optional[str] = None
    field_confidences: List[ExtractionConfidence] = Field(default_factory=list)


class QuotationExtraction(BaseModel):
    """A vendor quotation / estimate — the document that PRECEDES the order.

    It was previously unsupported, so a perfectly ordinary AP document was
    rejected with "could not tell what kind of document this is". A quotation
    is not part of two- or three-way matching (there is nothing to match it
    against yet), but it is evidence: it is what the purchase order was
    raised from, and a PO priced above its own quotation is a finding a
    reviewer wants to see.
    """
    quotation_number: Optional[str] = None
    vendor_name: str
    quotation_date: Optional[str] = None
    reference: Optional[str] = None
    line_items: List[LineItem] = Field(default_factory=list)
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    tax_amount: Optional[float] = None
    total_amount: Optional[float] = None
    field_confidences: List[ExtractionConfidence] = Field(default_factory=list)


class RejectionNoticeExtraction(BaseModel):
    invoice_number: str
    rejection_reason: str
    rejected_date: Optional[str] = None
    field_confidences: List[ExtractionConfidence] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# FR-005 / FR-006 — a single comparison line inside the match result
# ---------------------------------------------------------------------------
class ComparisonField(str, Enum):
    VENDOR = "vendor"
    PO_NUMBER = "po_number"
    QUANTITY = "quantity"
    UNIT_PRICE = "unit_price"
    TAX = "tax"
    TOTAL = "total"
    SUBTOTAL = "subtotal"
    LINE_ITEMS = "line_items"
    TAX_ARITHMETIC = "tax_arithmetic"
    QUOTED_PRICE = "quoted_price"
    PO_BILLED_TOTAL = "po_billed_total"


class LineComparison(BaseModel):
    """One PO line set against the invoice line that bills it.

    A single `unit_price` comparison can only ever describe a one-line
    document. On a three-line order it hides exactly the case this tool
    exists to catch: two lines billed correctly and the third overcharged,
    with the totals still close enough to pass a tolerance check.
    """
    description: Optional[str] = None
    po_quantity: Optional[float] = None
    invoice_quantity: Optional[float] = None
    po_unit_price: Optional[float] = None
    invoice_unit_price: Optional[float] = None
    po_amount: Optional[float] = None
    invoice_amount: Optional[float] = None
    variance_amount: Optional[float] = None
    percentage_variance: Optional[float] = None
    classification: MatchClassification
    # Which side the line appeared on when it could not be paired.
    only_on: Optional[str] = None  # "invoice" | "purchase_order"


class Comparison(BaseModel):
    field: ComparisonField
    expected_value: Optional[float | str] = None
    actual_value: Optional[float | str] = None
    absolute_variance: Optional[float] = None
    percentage_variance: Optional[float] = None
    tolerance_percent: Optional[float] = None
    classification: MatchClassification
    evaluable: bool  # False when a required source doc is legitimately missing


class MatchResult(BaseModel):
    exception_type: ExceptionType
    comparisons: List[Comparison]
    # Empty when either side has no itemized rows; never a reason to fail.
    line_comparisons: List[LineComparison] = Field(default_factory=list)
    match_score: int = Field(ge=0, le=100)
    # "goods" | "services". Plumbing work has nothing to receive, so calling
    # the outstanding document a GOODS receipt is wrong for half of real AP.
    # The exception_type stays missing_goods_receipt either way: splitting it
    # into two enum values would fragment every historical analytics bucket to
    # solve what is a labelling problem.
    procurement_kind: str = "goods"
    # What the UI puts next to the exception type, e.g. "goods receipt" or
    # "service confirmation".
    awaiting_document: Optional[str] = None
    # One sentence: what is settled, what is outstanding, what clears it.
    # A 100% match score beside "high risk" reads as a contradiction without
    # it.
    outstanding: Optional[str] = None
    # Findings that cannot be seen from inside a single case — duplicates,
    # cumulative over-billing, changed payment details. Populated by
    # services/history_service.py before the matcher runs; each entry names
    # the earlier document it was found against.
    duplicate_of: List[dict] = Field(default_factory=list)
    po_billing: Optional[dict] = None
    payment_detail_changes: List[dict] = Field(default_factory=list)
    # A rising unit-price trend across this vendor's invoices, when one was
    # found. See services/history_service.py:detect_price_drift.
    price_drift: Optional[dict] = None
    # True when the exception type came from a check that needed other cases
    # in the workspace. This is the field the portfolio analytics count to
    # answer "what would a per-invoice system have missed", so it is set here,
    # once, rather than re-derived from the type at three call sites.
    cross_case: bool = False
    # Which tolerance rule applied — workspace default, category, or vendor.
    tolerance_source: Optional[str] = None
    financial_impact: float
    financial_impact_basis: str  # human-readable: what the number means (FR per Case C note)
    recommended_owner: str
    risk_level: str  # low | medium | high


# ---------------------------------------------------------------------------
# FR-007 — Exception Reasoning Agent (Document 5 "Component 2"). AI-backed:
# takes the already-computed MatchResult and adds severity, a plain-language
# description, and a recommended action. It must NEVER recompute
# financial_impact itself — that field is echoed from the deterministic
# MatchResult and cross-checked in exception_agent.py, not derived here.
# ---------------------------------------------------------------------------
class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ExceptionReasoning(BaseModel):
    exception_type: ExceptionType
    severity: Severity
    description: str  # plain-language explanation of the discrepancy
    financial_impact: float  # must equal MatchResult.financial_impact — see exception_agent.py guardrail
    recommended_owner: str
    recommended_action: str
    confidence: float = Field(ge=0, le=1)
    requires_human_review: bool = True


# ---------------------------------------------------------------------------
# The guardrail, made visible
# ---------------------------------------------------------------------------
# exception_agent.py has always overwritten the model's stated financial
# impact with the deterministic one. That is the right behaviour and it was
# completely invisible: a silent safety net proves nothing to anyone watching.
#
# This record is what the check produces every time it runs — on agreement as
# much as on disagreement, because "the guardrail fired 4 times in 320 cases"
# is only meaningful next to the 316 it did not. It is stored per case and
# aggregated across the portfolio into the disagreement ledger.
class TrustCheck(BaseModel):
    exception_id: str
    # What the model said the money was, before anything was corrected.
    ai_value: Optional[float] = None
    # What matching_service.py computed. This is the value that is used, in
    # every case, whether or not the two agree.
    computed_value: float
    # Absolute and relative gap. Percent is None when the computed value is
    # zero, because a percentage of nothing is not a number.
    difference: float = 0.0
    difference_percent: Optional[float] = None
    # True when the gap cleared the material threshold and the deterministic
    # value replaced the model's in the record the user sees.
    overridden: bool = False
    # "ai" when a model actually answered, "mock" when the deterministic
    # fallback stood in. A ledger that silently counts fallback runs as model
    # agreement would be measuring nothing at all, so the two never mix.
    ai_source: str = "mock"
    # "live" for an ordinary case, "fault_injection" for a deliberately
    # corrupted value used to prove the guardrail catches one. These are
    # counted separately and never added together.
    kind: str = "live"
    checked_at: str
    note: Optional[str] = None


# ---------------------------------------------------------------------------
# FR-008/009 — evidence graph
# ---------------------------------------------------------------------------
class GraphNodeType(str, Enum):
    DOCUMENT = "document"
    EXTRACTED_VALUE = "extracted_value"
    BUSINESS_RULE = "business_rule"
    FINDING = "finding"
    # Where the case goes next — the owner it should sit with and the action
    # that would settle it. The graph used to stop at the finding, which meant
    # the one screen whose job is to answer "how did you get here" said
    # nothing about "so what now". Both values are echoed from the
    # deterministic MatchResult; nothing here is generated.
    ROUTING = "routing"


class GraphNode(BaseModel):
    id: str
    type: GraphNodeType
    label: str
    detail: Optional[str] = None
    source_document_id: Optional[str] = None


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    relationship: str  # e.g. "extracted_from", "evaluated_against", "produces"


class EvidenceGraph(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]


# ---------------------------------------------------------------------------
# FR-010 — Resolution Copilot. This IS the output_schema for the resolution
# ADK agent: citations are a required, structurally-enforced field, not
# something the model can quietly drop.
# ---------------------------------------------------------------------------
class Citation(BaseModel):
    claim: str
    source_document_id: str
    source_field: str


class ResolutionDraft(BaseModel):
    subject: str
    body: str
    citations: List[Citation]
    recommended_owner: str
    requires_human_review: bool = True


# ---------------------------------------------------------------------------
# FR-012 — audit trail
# ---------------------------------------------------------------------------
class AuditEvent(BaseModel):
    event_id: str
    exception_id: str
    actor: str  # "system" or a user identifier
    action: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    note: Optional[str] = None
    timestamp: str


# ---------------------------------------------------------------------------
# Wrapper every AI call site returns — lets the API/UI show a mock-mode
# indicator (FR-013) without every caller re-deriving it.
# ---------------------------------------------------------------------------
class AIResult(BaseModel):
    source: str  # "ai" | "mock"
    data: dict
    error: Optional[str] = None
