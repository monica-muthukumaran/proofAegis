// mockData.js — mirrors proofaegis-backend/mock_data/seed_cases.json and
// mock_extractions.py exactly. This is what the guided tour runs on (it must
// work with zero backend, per the brief) and what services/api.js falls
// back to if the real backend isn't reachable.

export const TOLERANCE = { price_variance_percent: 5, quantity_variance_percent: 2 };

// The STORED fields of each case — what a datastore actually holds. The
// derived match summary (type, score, impact, risk, owner) is deliberately NOT
// written here; it is computed below from MATCH_RESULTS, for the same reason
// backend/services/case_service.py computes it on read rather than trusting a
// stored copy.
//
// This split is the fix for a real defect. These rows used to be the whole of
// EXCEPTIONS, and they were missing every derived field that the live
// `/api/exceptions` response carries. The frontend was therefore written
// against a contract the mock did not honour, and three things broke the
// moment the app ran on mock data:
//
//   * Dashboard's "Recent exceptions" filters on `exception_type`, so with the
//     field absent EVERY row was filtered out and the table rendered empty
//     while the KPI above it said there were three open exceptions.
//   * pickPriority ranks on `financial_impact`; with all of them undefined it
//     fell through to the first row and the priority card showed a headline of
//     "Exception" with em dashes for impact and match score.
//   * The queue's risk rails key off `risk_level` and never appeared.
//
// Copying the numbers in by hand would have re-created exactly the drift the
// backend comment at case_service.py:160 warns about (seed data once carried
// hand-picked match scores of 72/78/60 that no code produced). So they are
// derived, once, from the same MATCH_RESULTS the match workspace renders.
const EXCEPTION_RECORDS = [
  {
    exception_id: "EXC-2026-0001",
    invoice_id: "INV-2026-1187",
    vendor_name: "Chennai Industrial Supplies Pvt. Ltd.",
    purchase_order_id: "PO-2026-00421",
    business_unit: "Operations",
    currency: "INR",
    invoice_amount: 265000,
    po_amount: 240000,
    status: "exception_detected",
    // "Recent exceptions" sorts on this. Without it the sort compared
    // undefined against undefined and the ordering was whatever the array
    // happened to be in.
    created_at: "2026-07-02T14:42:00Z",
  },
  {
    exception_id: "EXC-2026-0002",
    invoice_id: "INV-2026-2204",
    vendor_name: "Southern Office Systems",
    purchase_order_id: "PO-2026-00516",
    business_unit: "Facilities",
    currency: "INR",
    invoice_amount: 315000,
    po_amount: 315000,
    status: "awaiting_receiving",
    created_at: "2026-07-01T09:15:00Z",
  },
  {
    exception_id: "EXC-2026-0003",
    invoice_id: "INV-2026-3310",
    vendor_name: "BlueWave IT Services",
    purchase_order_id: "PO-2026-00602",
    business_unit: "IT",
    currency: "INR",
    invoice_amount: 180000,
    po_amount: 180000,
    status: "awaiting_receiving",
    created_at: "2026-06-29T16:08:00Z",
  },
];

export const DOCUMENTS = {
  "EXC-2026-0001": [
    { document_id: "DOC-0001-INV", document_type: "vendor_invoice", file_name: "vendor_invoice_001.pdf", confidence: 0.97 },
    { document_id: "DOC-0001-PO", document_type: "purchase_order", file_name: "purchase_order_001.pdf", confidence: 0.98 },
    { document_id: "DOC-0001-GRN", document_type: "goods_receipt_note", file_name: "goods_receipt_note_001.pdf", confidence: 0.95 },
    { document_id: "DOC-0001-REJ", document_type: "rejection_notice", file_name: "rejection_notice_001.pdf", confidence: 0.99 },
  ],
  "EXC-2026-0002": [
    { document_id: "DOC-0002-INV", document_type: "vendor_invoice", file_name: "vendor_invoice_002.pdf", confidence: 0.96 },
    { document_id: "DOC-0002-PO", document_type: "purchase_order", file_name: "purchase_order_002.pdf", confidence: 0.97 },
    { document_id: "DOC-0002-GRN", document_type: "goods_receipt_note", file_name: "goods_receipt_note_002.pdf", confidence: 0.94 },
    { document_id: "DOC-0002-REJ", document_type: "rejection_notice", file_name: "rejection_notice_002.pdf", confidence: 0.98 },
  ],
  "EXC-2026-0003": [
    { document_id: "DOC-0003-INV", document_type: "vendor_invoice", file_name: "vendor_invoice_003.pdf", confidence: 0.96 },
    { document_id: "DOC-0003-PO", document_type: "purchase_order", file_name: "purchase_order_003.pdf", confidence: 0.97 },
    { document_id: "DOC-0003-REJ", document_type: "rejection_notice", file_name: "rejection_notice_003.pdf", confidence: 0.99 },
  ],
};

// Mirrors services/matching_service.py's output shape exactly.
export const MATCH_RESULTS = {
  "EXC-2026-0001": {
    exception_type: "price_variance",
    match_score: 67,
    financial_impact: 25000,
    financial_impact_basis: "Variance/unit (250) x quantity (100).",
    recommended_owner: "Procurement",
    risk_level: "high",
    comparisons: [
      { field: "vendor", classification: "matched", evaluable: true },
      { field: "po_number", classification: "matched", evaluable: true },
      { field: "quantity", classification: "matched", evaluable: true, expected_value: 100, actual_value: 100 },
      { field: "unit_price", classification: "outside_tolerance", evaluable: true, expected_value: 2400, actual_value: 2650, absolute_variance: 250, percentage_variance: 10.42, tolerance_percent: 5 },
    ],
  },
  "EXC-2026-0002": {
    exception_type: "quantity_variance",
    match_score: 67,
    financial_impact: 50400,
    financial_impact_basis: "80 unreceived units x implied unit price (630.00) = amount at risk pending receipt confirmation.",
    recommended_owner: "Receiving",
    risk_level: "medium",
    comparisons: [
      { field: "vendor", classification: "matched", evaluable: true },
      { field: "po_number", classification: "matched", evaluable: true },
      { field: "quantity", classification: "outside_tolerance", evaluable: true, expected_value: 420, actual_value: 500, absolute_variance: 80, percentage_variance: 19.05, tolerance_percent: 2 },
    ],
  },
  "EXC-2026-0003": {
    exception_type: "missing_goods_receipt",
    match_score: 67,
    financial_impact: 180000,
    financial_impact_basis: "Full invoice amount at risk pending goods receipt or service confirmation — not a computed price/quantity variance.",
    recommended_owner: "Requesting business unit",
    risk_level: "high",
    comparisons: [
      { field: "vendor", classification: "matched", evaluable: true },
      { field: "po_number", classification: "matched", evaluable: true },
      { field: "quantity", classification: "missing", evaluable: false },
    ],
  },
};

// The list shape the real `/api/exceptions` returns: the stored record plus
// the derived match summary. Mirrors case_service.summarize_exception() —
// same five fields, same names, same source — so anything written against the
// live contract works unchanged on mock data, which is the entire point of a
// fixture.
export const EXCEPTIONS = EXCEPTION_RECORDS.map((record) => {
  const match = MATCH_RESULTS[record.exception_id];
  if (!match) return record;
  return {
    ...record,
    exception_type: match.exception_type,
    match_score: match.match_score,
    financial_impact: match.financial_impact,
    risk_level: match.risk_level,
    assigned_team: match.recommended_owner,
  };
});

export const REASONING = {
  "EXC-2026-0001": {
    exception_type: "price_variance", severity: "high",
    description: "This invoice bills 100 units at INR 2,650 each, but the purchase order set the price at INR 2,400 — a 10.42% overcharge, above the 5% tolerance we allow automatically.",
    financial_impact: 25000, recommended_owner: "Procurement",
    recommended_action: "Request vendor credit note or procurement approval.",
    confidence: 0.95, requires_human_review: true, _ai_source: "mock",
  },
  "EXC-2026-0002": {
    exception_type: "quantity_variance", severity: "medium",
    description: "500 units were invoiced, but the goods receipt shows only 420 units actually arrived — a 19.05% shortfall, well above the 2% tolerance. INR 50,400 of unreceived goods is at risk.",
    financial_impact: 50400, recommended_owner: "Receiving",
    recommended_action: "Ask Receiving to confirm whether the remaining 80 units are still in transit before releasing payment for the full invoice.",
    confidence: 0.93, requires_human_review: true, _ai_source: "mock",
  },
  "EXC-2026-0003": {
    exception_type: "missing_goods_receipt", severity: "high",
    description: "No goods receipt or service confirmation is on file for this invoice. The full INR 180,000 is unverified and should not be paid until delivery/completion is confirmed.",
    financial_impact: 180000, recommended_owner: "Requesting business unit",
    recommended_action: "Obtain a goods receipt or written service-completion confirmation from the requesting business unit before releasing payment.",
    confidence: 0.90, requires_human_review: true, _ai_source: "mock",
  },
};

export const RESOLUTIONS = {
  "EXC-2026-0001": {
    subject: "Price variance on INV-2026-1187 — request for correction",
    body: "Hello,\n\nInvoice INV-2026-1187 against PO-2026-00421 was received at a unit price of INR 2,650, against the PO unit price of INR 2,400 — a variance of 10.42%, outside our 5% tolerance. For 100 units, this represents a financial impact of INR 25,000.\n\nCould you confirm whether this reflects a pricing update we don't have on file, or issue a corrected invoice at the PO price? Happy to discuss.\n\nThanks,\nAccounts Payable",
    citations: [
      { claim: "Invoice unit price INR 2,650", source_document_id: "DOC-0001-INV", source_field: "unit_price" },
      { claim: "PO unit price INR 2,400", source_document_id: "DOC-0001-PO", source_field: "unit_price" },
    ],
    recommended_owner: "Procurement", requires_human_review: true, _ai_source: "mock",
  },
  "EXC-2026-0002": {
    subject: "Quantity variance on INV-2026-2204 — 80 units unreceived",
    body: "Hello,\n\nInvoice INV-2026-2204 bills 500 units against PO-2026-00516, but the goods receipt on file shows only 420 units received — a variance of 19.05%, outside our 2% tolerance. At the implied unit price of INR 630, this represents INR 50,400 at risk pending confirmation.\n\nCould Receiving confirm whether the remaining 80 units are in transit, or whether the invoice should be revised?\n\nThanks,\nAccounts Payable",
    citations: [
      { claim: "Invoiced quantity 500 units", source_document_id: "DOC-0002-INV", source_field: "quantity" },
      { claim: "Received quantity 420 units", source_document_id: "DOC-0002-GRN", source_field: "received_quantity" },
    ],
    recommended_owner: "Receiving", requires_human_review: true, _ai_source: "mock",
  },
  "EXC-2026-0003": {
    subject: "Missing goods receipt for INV-2026-3310 — confirmation needed",
    body: "Hello,\n\nInvoice INV-2026-3310 against PO-2026-00602 has no goods receipt or service confirmation on file. The full invoice amount of INR 180,000 is on hold pending confirmation.\n\nCould the requesting business unit confirm delivery/completion of the service so we can proceed?\n\nThanks,\nAccounts Payable",
    citations: [{ claim: "Invoice total INR 180,000", source_document_id: "DOC-0003-INV", source_field: "total_amount" }],
    recommended_owner: "Requesting business unit", requires_human_review: true, _ai_source: "mock",
  },
};

export function buildEvidenceGraph(exceptionId) {
  const match = MATCH_RESULTS[exceptionId];
  const docs = DOCUMENTS[exceptionId] || [];
  const nodes = [];
  const edges = [];
  let edgeSeq = 0;
  const nextEdge = () => `${exceptionId}-edge-${++edgeSeq}`;

  docs.forEach((d) => {
    nodes.push({ id: `doc-${d.document_id}`, type: "document", label: d.file_name, detail: `Type: ${d.document_type} · Confidence: ${d.confidence}` });
  });

  const ruleId = `${exceptionId}-rule-tolerance`;
  nodes.push({
    id: ruleId, type: "business_rule", label: "Tolerance rule",
    detail: `Price tolerance ${TOLERANCE.price_variance_percent}% · Quantity tolerance ${TOLERANCE.quantity_variance_percent}%`,
  });

  match.comparisons.filter((c) => c.evaluable).forEach((c) => {
    const valueId = `${exceptionId}-value-${c.field}`;
    nodes.push({
      id: valueId, type: "extracted_value",
      label: `${c.field}: expected ${c.expected_value ?? "—"} / actual ${c.actual_value ?? "—"}`,
      detail: c.percentage_variance != null ? `variance ${c.percentage_variance}%` : null,
    });
    docs.forEach((d) => edges.push({ id: nextEdge(), source: valueId, target: `doc-${d.document_id}`, relationship: "extracted_from" }));
    edges.push({ id: nextEdge(), source: valueId, target: ruleId, relationship: "evaluated_against" });

    if (c.classification === "outside_tolerance" || c.classification === "within_tolerance") {
      const findingId = `${exceptionId}-finding-${c.field}`;
      nodes.push({
        id: findingId, type: "finding",
        label: `${c.classification.replace("_", " ")}: ${c.field}`,
        detail: `${match.exception_type} — ${match.financial_impact_basis}`,
      });
      edges.push({ id: nextEdge(), source: valueId, target: findingId, relationship: "produces" });
    }
  });

  return { nodes, edges };
}

export function buildAuditTrail(exceptionId) {
  const base = [
    { event_id: "seed-1", action: "documents_processed", actor: "system", note: "4 documents extracted", timestamp: "2026-07-02T09:12:00Z" },
    { event_id: "seed-2", action: "finding_created", actor: "system", note: "Exception detected by matching engine", timestamp: "2026-07-02T09:12:04Z" },
  ];
  if (exceptionId === "EXC-2026-0001") {
    base.push({ event_id: "seed-3", action: "resolution_draft_generated", actor: "system", note: "source=mock", timestamp: "2026-07-02T09:14:00Z" });
  }
  return base;
}

// Computed from the cases above rather than typed out, mirroring
// backend/routes/dashboard.py. Hand-written totals are how a fixture starts
// disagreeing with itself: this block previously omitted `clean_count`
// entirely, so the Open-exceptions KPI rendered the literal string
// "undefined invoices cleared" underneath it, and omitted
// `exception_type_value`, so the breakdown chart had no money to scale by.
//
// Deriving them means the mock dashboard can never contradict the mock queue,
// and adding a case above updates every figure here for free.
const OPEN_STATUSES = new Set([
  "exception_detected", "assigned", "awaiting_procurement",
  "awaiting_receiving", "awaiting_vendor",
]);

export const DASHBOARD_SUMMARY = (() => {
  // A cleared invoice is a case, and it belongs in the denominator of the
  // average match score — but it is not an exception type and must stay out
  // of the breakdown chart. Same rule as the backend.
  const cleared = EXCEPTIONS.filter((e) => e.exception_type === "no_exception");
  const scored = EXCEPTIONS.filter((e) => e.match_score != null);
  const breakdown = {};
  const value = {};
  let valueOnHold = 0;

  for (const e of EXCEPTIONS) {
    if (!e.exception_type || e.exception_type === "no_exception") continue;
    const impact = Number(e.financial_impact || 0);
    breakdown[e.exception_type] = (breakdown[e.exception_type] || 0) + 1;
    value[e.exception_type] = (value[e.exception_type] || 0) + impact;
    if (OPEN_STATUSES.has(e.status)) valueOnHold += impact;
  }

  return {
    invoice_count: EXCEPTIONS.length,
    clean_count: cleared.length,
    open_exceptions_count: EXCEPTIONS.filter((e) => OPEN_STATUSES.has(e.status)).length,
    value_on_hold: Math.round(valueOnHold * 100) / 100,
    average_match_score: scored.length
      ? Math.round((scored.reduce((sum, e) => sum + e.match_score, 0) / scored.length) * 10) / 10
      : 0,
    awaiting_vendor_count: EXCEPTIONS.filter((e) => e.status === "awaiting_vendor").length,
    exception_type_breakdown: breakdown,
    exception_type_value: value,
  };
})();
