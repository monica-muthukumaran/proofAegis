// registers.js — the record-level views over the case portfolio.
//
// ProofAegis stores one thing: an exception case. But an AP team does not
// only think in cases — they get asked "what is the status of INV-2026-1187",
// "how much have we billed against PO-2026-00421", "which vendor is costing
// us the most". Those are register questions, and answering them by opening
// cases one at a time is the manual work this product exists to remove.
//
// Every figure below is derived from GET /api/exceptions, which already
// carries invoice_id, purchase_order_id, invoice_amount, po_amount, vendor
// and outcome on each record. So the registers cost ONE request, cannot
// disagree with the queue (same payload, same read), and invent nothing.
//
// What they deliberately do not claim: this is not the ERP's invoice master.
// It is every invoice ProofAegis has seen. The pages say so, because a
// register that silently omits records is worse than no register.

/** Money, or an em dash. Never "₹0" for a value that is simply not known. */
export function money(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `₹${Math.round(Number(value)).toLocaleString("en-IN")}`;
}

/** Compact money for KPI tiles, where a 9-digit figure would wrap. */
export function moneyShort(value) {
  if (value === null || value === undefined) return "—";
  const n = Number(value);
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)}Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(2)}L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}

export const dash = (v) => (v === null || v === undefined || v === "" ? "—" : v);
export const label = (v) => (v ? String(v).replaceAll("_", " ") : null);

/** A case counts as an exception only once it has been analysed AND failed. */
export const isException = (c) => Boolean(c.exception_type) && c.exception_type !== "no_exception";

/** Cleared is an analysed pass — distinct from "not analysed yet". */
export const isCleared = (c) => c.exception_type === "no_exception" || c.status === "cleared";

export const STATUS_TONE = {
  exception_detected: "exception", assigned: "warning", awaiting_procurement: "warning",
  awaiting_receiving: "warning", awaiting_vendor: "accent", approved_with_exception: "verified",
  resolved: "verified", cleared: "verified", closed: "neutral", processing: "neutral",
  received: "neutral",
};

export const TYPE_TONE = {
  price_variance: "exception", quantity_variance: "warning",
  missing_goods_receipt: "warning", missing_purchase_order: "exception",
  po_over_billed: "exception", payment_details_changed: "critical",
  duplicate_invoice: "critical", tax_total_mismatch: "warning",
  vendor_mismatch: "exception",
};

/**
 * Statuses actually present in the data, rather than a hardcoded list that
 * silently drops rows when the backend adds one. The portfolio generator
 * emits `cleared`, which no hardcoded UI list currently knows about — this
 * is how the registers avoid inheriting that bug.
 */
export function statusOptions(cases) {
  return [...new Set((cases || []).map((c) => c.status).filter(Boolean))].sort();
}

/**
 * One row per invoice. A case IS an invoice here — the backend creates
 * exactly one case per invoice it ingests — so this is a projection, not an
 * aggregation, and no figure is combined across records.
 */
export function toInvoiceRows(cases) {
  const rows = (cases || []).filter((c) => c.invoice_id);
  // An invoice number appearing on more than one case IS a duplicate-billing
  // finding, and the register is where someone looks that number up. Without
  // this the page shows seven identical-looking rows and leaves the reader to
  // work out whether it is a data problem or a rendering bug.
  const seen = new Map();
  for (const c of rows) seen.set(c.invoice_id, (seen.get(c.invoice_id) || 0) + 1);

  return rows
    .map((c) => ({
      duplicate_count: seen.get(c.invoice_id),
      invoice_id: c.invoice_id,
      exception_id: c.exception_id,
      vendor_name: c.vendor_name,
      vendor_id: c.vendor_id,
      purchase_order_id: c.purchase_order_id,
      business_unit: c.business_unit,
      description: c.line_item_description,
      invoice_amount: c.invoice_amount,
      po_amount: c.po_amount,
      financial_impact: isException(c) ? c.financial_impact : null,
      exception_type: c.exception_type,
      status: c.status,
      risk_level: c.risk_level,
      created_at: c.created_at,
    }));
}

/**
 * One row per purchase order, aggregating every invoice billed against it.
 *
 * Grouping rather than projecting is the whole point. A single case cannot
 * see that two invoices were raised against one PO — backend/datastore.py
 * calls that out as a class of problem only visible across cases — so the
 * register groups, and `billed_total` vs `ordered_amount` makes cumulative
 * over-billing legible even when no individual invoice breached tolerance.
 *
 * With today's 1:1 seed data every group holds one invoice and this reads as
 * an ordinary register. That is the correct degenerate case, not a reason to
 * model it as a flat list.
 */
export function toPurchaseOrderRows(cases) {
  const groups = new Map();

  for (const c of cases || []) {
    if (!c.purchase_order_id) continue;
    let g = groups.get(c.purchase_order_id);
    if (!g) {
      g = {
        purchase_order_id: c.purchase_order_id,
        vendor_name: c.vendor_name,
        vendor_id: c.vendor_id,
        business_unit: c.business_unit,
        description: c.line_item_description,
        ordered_amount: null,
        billed_total: 0,
        invoice_count: 0,
        invoices: [],
        exception_count: 0,
        at_risk: 0,
        statuses: new Set(),
      };
      groups.set(c.purchase_order_id, g);
    }
    // Every case citing this PO reports the same PO total; take the first
    // usable one rather than summing, which would multiply the order by the
    // number of invoices raised against it.
    //
    // Zero is rejected alongside null. A real case in the portfolio carries
    // po_amount 0.0 on an invoice for ₹62,540 — that is an order total the
    // extractor never read, not a ₹0 commitment, and treating it as one made
    // the register accuse the vendor of billing ₹62,540 against nothing.
    // Nobody raises a purchase order for ₹0, so an absent value and a zero
    // are the same fact and both belong in the "not captured" column.
    if (g.ordered_amount === null && Number(c.po_amount) > 0) {
      g.ordered_amount = Number(c.po_amount);
    }
    if (typeof c.invoice_amount === "number") g.billed_total += c.invoice_amount;
    g.invoice_count += 1;
    g.invoices.push({ invoice_id: c.invoice_id, exception_id: c.exception_id, amount: c.invoice_amount, status: c.status });
    if (isException(c)) {
      g.exception_count += 1;
      g.at_risk += Number(c.financial_impact) || 0;
    }
    if (c.status) g.statuses.add(c.status);
  }

  return [...groups.values()].map((g) => ({
    ...g,
    statuses: [...g.statuses],
    // Seven cases can share one invoice number — that IS the duplicate, and
    // it is the reason the order is over-billed. Seven identically-labelled
    // buttons would hide it, so a repeated number falls back to the case ID,
    // which is unique and is what the click opens anyway.
    invoices: g.invoices.map((i, _, all) => ({
      ...i,
      duplicated: all.filter((o) => o.invoice_id === i.invoice_id).length > 1,
      chip: all.filter((o) => o.invoice_id === i.invoice_id).length > 1
        ? i.exception_id
        : (i.invoice_id || i.exception_id),
    })),
    // The invoice numbers that appear more than once against this order, so
    // the row can name the duplicate instead of leaving the reader to spot
    // seven repeats of the same string.
    duplicate_numbers: [...new Set(
      g.invoices
        .map((i) => i.invoice_id)
        .filter((id, _, all) => id && all.filter((o) => o === id).length > 1),
    )],
    // Null, not zero, when the order value was never captured — "we billed
    // ₹2.6L against an unknown order" must not render as a ₹2.6L overrun.
    variance: g.ordered_amount === null ? null : g.billed_total - g.ordered_amount,
  }));
}

/** Sort helper shared by both registers. Unknowns sort last either way. */
export function compareBy(key, dir) {
  return (a, b) => {
    const av = a[key], bv = b[key];
    if (av === null || av === undefined) return 1;
    if (bv === null || bv === undefined) return -1;
    const cmp = typeof av === "number" && typeof bv === "number"
      ? av - bv
      : String(av).localeCompare(String(bv));
    return dir === "asc" ? cmp : -cmp;
  };
}
