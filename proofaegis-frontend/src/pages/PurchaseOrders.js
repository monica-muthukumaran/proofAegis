// PurchaseOrders.js — the purchase-order register.
//
// This is deliberately NOT the invoice register with one column swapped.
// A PO is a commitment; an invoice is a claim against it. The question this
// screen exists to answer is the one no single case can: how much has been
// billed against this order in total, and does that exceed what was ordered?
//
// backend/datastore.py names cumulative billing as a class of problem only
// visible across cases, so the register groups by PO number and compares
// summed billing against the order value. Two ₹60,000 invoices against a
// ₹100,000 order each pass a per-invoice tolerance check and together
// overrun it — that is the row this page makes visible.
//
// Ordered value is taken from the first case that reports it, never summed:
// every case citing a PO repeats the same order total, so adding them would
// multiply the commitment by the number of invoices raised against it.
import { html, useState, useEffect, useMemo } from "../lib.js";
import * as api from "../services/api.js";
import { Badge, EmptyState, Skeleton, ErrorState } from "../components/ui/primitives.js";
import { MetricCard } from "../components/dashboard/MetricCard.js";
import { ModeBanner } from "../components/ui/ModeBanner.js";
import { RegisterToolbar, makeSortHeader } from "../components/registers/RegisterToolbar.js";
import {
  money, moneyShort, dash, label,
  statusOptions, toPurchaseOrderRows, compareBy, STATUS_TONE,
} from "../lib/registers.js";

const VARIANCE_HINT =
  "Total billed against this order minus the order value. Positive means the " +
  "vendor has invoiced more than was committed — across every invoice raised " +
  "against the PO, not just one. Blank when the order value was never captured.";

const BILLED_HINT =
  "Sum of every invoice ProofAegis has seen against this purchase order.";

const VIEWS = [
  { value: "all", label: "All orders" },
  { value: "overbilled", label: "Over-billed" },
  { value: "multi", label: "Multiple invoices" },
  { value: "exceptions", label: "With exception" },
];

export function PurchaseOrders({ openException }) {
  const [cases, setCases] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [view, setView] = useState("all");
  const [sortKey, setSortKey] = useState("purchase_order_id");
  const [sortDir, setSortDir] = useState("asc");

  const load = async () => {
    setError(null);
    const r = await api.listExceptions();
    if (r.source === "error") { setError(r.error); setCases(null); return; }
    setCases(r.data || []);
  };
  useEffect(() => { load(); }, []);

  const rows = useMemo(() => toPurchaseOrderRows(cases), [cases]);

  const filtered = useMemo(() => {
    let out = rows;
    if (view === "overbilled") out = out.filter((r) => r.variance !== null && r.variance > 0);
    else if (view === "multi") out = out.filter((r) => r.invoice_count > 1);
    else if (view === "exceptions") out = out.filter((r) => r.exception_count > 0);
    if (status !== "all") out = out.filter((r) => r.statuses.includes(status));
    const q = query.trim().toLowerCase();
    if (q) {
      out = out.filter((r) =>
        [r.purchase_order_id, r.vendor_name, r.description, r.business_unit].some((f) => f && String(f).toLowerCase().includes(q))
        || r.invoices.some((i) => i.invoice_id && i.invoice_id.toLowerCase().includes(q)));
    }
    return [...out].sort(compareBy(sortKey, sortDir));
  }, [rows, query, status, view, sortKey, sortDir]);

  const setSort = (key) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("asc"); }
  };
  const th = makeSortHeader(sortKey, sortDir, setSort);

  const totals = useMemo(() => {
    // Orders whose value was never captured are excluded from the ordered
    // total and counted separately. Summing them as zero would print
    // "Ordered ₹0 / Billed ₹7L" over a set where the order values are simply
    // unknown — the same false overrun the variance column refuses to claim.
    const known = filtered.filter((r) => r.ordered_amount !== null);
    return {
      count: filtered.length,
      ordered: known.reduce((s, r) => s + Number(r.ordered_amount), 0),
      orderedKnown: known.length,
      billed: filtered.reduce((s, r) => s + (Number(r.billed_total) || 0), 0),
      overbilled: filtered.filter((r) => r.variance !== null && r.variance > 0).length,
    };
  }, [filtered]);

  // Opening a PO with one invoice goes straight to its case. With several,
  // there is no single case to open, so the row stays a summary and the
  // invoice chips below it are the way in.
  const openRow = (r) => { if (r.invoices.length === 1) openException(r.invoices[0].exception_id); };

  return html`
    <div class="stack gap-24">
      <div class="stack gap-4">
        <h1 class="text-page-title">Purchase Orders</h1>
        <p class="text-secondary" style=${{ maxWidth: "72ch" }}>
          Every order ProofAegis has seen an invoice against, with the total billed compared to
          the value committed. Grouping by order is what makes cumulative over-billing visible —
          invoices that each pass tolerance alone can still overrun the PO together.
        </p>
      </div>
      <${ModeBanner} compact=${true} />

      ${error ? html`
        <div class="panel" style=${{ padding: 22 }}>
          <${ErrorState} title="Could not load purchase orders" message=${error} onRetry=${load} />
        </div>
      ` : !cases ? html`
        <div class="panel stack gap-12" style=${{ padding: 22 }}>
          ${[1, 2, 3, 4].map((i) => html`<${Skeleton} key=${i} height="44px" />`)}
        </div>
      ` : rows.length === 0 ? html`
        <div class="panel" style=${{ padding: 22 }}>
          <${EmptyState} icon="layers" title="No purchase orders yet"
            description="Orders appear here once an invoice citing a PO number has been ingested." />
        </div>
      ` : html`
        <div class="kpi-grid">
          <${MetricCard} icon="layers" label="Orders shown" raw=${totals.count}
            format=${(n) => Math.round(n).toLocaleString("en-IN")}
            sublabel=${`of ${rows.length} with billing`} />
          <${MetricCard} icon="check" label="Ordered value"
            value=${totals.orderedKnown === 0 ? "—" : undefined}
            raw=${totals.orderedKnown === 0 ? undefined : totals.ordered}
            format=${moneyShort}
            sublabel=${totals.orderedKnown === totals.count
              ? "Committed across the rows shown"
              : `Committed across ${totals.orderedKnown} of ${totals.count} — the rest have no order value on file`} />
          <${MetricCard} icon="file" label="Billed against" raw=${totals.billed}
            format=${moneyShort} hint=${BILLED_HINT} sublabel="Invoiced across the rows shown" />
          <${MetricCard} icon="shield" label="Over-billed orders" raw=${totals.overbilled}
            format=${(n) => Math.round(n).toLocaleString("en-IN")}
            tone="exception" hint=${VARIANCE_HINT} sublabel="Billed more than ordered" />
        </div>

        <div class="panel stack gap-16" style=${{ padding: 22 }}>
          <${RegisterToolbar}
            query=${query} setQuery=${setQuery}
            searchLabel="Search purchase orders"
            placeholder="Search PO, vendor, invoice, line item…"
            status=${status} setStatus=${setStatus} statuses=${statusOptions(cases)}
            shown=${filtered.length} total=${rows.length} unit="orders"
            extra=${html`
              <select class="input" style=${{ maxWidth: 190 }} aria-label="Filter by billing view"
                value=${view} onChange=${(e) => setView(e.target.value)}>
                ${VIEWS.map((o) => html`<option key=${o.value} value=${o.value}>${o.label}</option>`)}
              </select>
            `}
          />

          ${filtered.length === 0 ? html`
            <p class="text-muted" style=${{ padding: "24px 4px" }}>No purchase orders match your search.</p>
          ` : html`
            <div class="table-scroll" role="region" aria-label="Purchase order register" tabIndex="0">
              <table>
                <thead>
                  <tr>
                    ${th("purchase_order_id", "Purchase order")}
                    ${th("vendor_name", "Vendor")}
                    ${th("description", "Line item")}
                    ${th("ordered_amount", "Ordered", null, "right")}
                    ${th("invoice_count", "Invoices", BILLED_HINT, "right")}
                    ${th("billed_total", "Billed", BILLED_HINT, "right")}
                    ${th("variance", "Variance", VARIANCE_HINT, "right")}
                    ${th("at_risk", "At risk", null, "right")}
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  ${filtered.map((r) => {
                    const over = r.variance !== null && r.variance > 0;
                    const single = r.invoices.length === 1;
                    return html`
                      <tr key=${r.purchase_order_id}
                        class="${single ? "row-clickable" : ""} ${over ? "row-breach" : ""}"
                        role=${single ? "link" : null} tabIndex=${single ? "0" : null}
                        aria-label=${single ? `Open case ${r.invoices[0].exception_id} for order ${r.purchase_order_id}` : null}
                        onClick=${single ? () => openRow(r) : null}
                        onKeyDown=${single ? (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openRow(r); } } : null}>
                        <td class="po-cell">
                          <div class="stack gap-4">
                            <span class="id">${r.purchase_order_id}</span>
                            ${r.invoice_count > 1 ? html`
                              ${r.duplicate_numbers.length ? html`
                                <span class="text-small" style=${{ color: "var(--exception)", fontWeight: 600 }}>
                                  Invoice ${r.duplicate_numbers.join(", ")} billed more than once
                                </span>
                              ` : null}
                              <div class="row gap-4" style=${{ flexWrap: "wrap" }}>
                                ${r.invoices.map((i) => html`
                                  <button key=${i.exception_id} class="btn btn-ghost btn-sm" style=${{ minHeight: 26, padding: "2px 6px", fontSize: ".75rem" }}
                                    onClick=${(e) => { e.stopPropagation(); openException(i.exception_id); }}
                                    title=${i.duplicated ? `Invoice ${i.invoice_id} — one of several cases sharing this number` : undefined}
                                    aria-label=${`Open case ${i.exception_id} for invoice ${i.invoice_id}`}>${i.chip}</button>
                                `)}
                              </div>
                            ` : html`<span class="text-muted text-small">${dash(r.invoices[0] && r.invoices[0].invoice_id)}</span>`}
                          </div>
                        </td>
                        <td class="clamp-2" style=${{ maxWidth: 190 }}>${dash(r.vendor_name)}</td>
                        <td class="clamp-2" style=${{ maxWidth: 200 }}>${dash(r.description)}</td>
                        <td style=${{ textAlign: "right" }}>${money(r.ordered_amount)}</td>
                        <td style=${{ textAlign: "right" }}>${r.invoice_count}</td>
                        <td style=${{ textAlign: "right" }}>${money(r.billed_total)}</td>
                        <td style=${{ textAlign: "right" }} title=${VARIANCE_HINT}>
                          ${r.variance === null ? html`<span class="text-muted">—</span>` : html`
                            <span style=${over ? { color: "var(--exception)", fontWeight: 700 } : null}>
                              ${over ? "+" : ""}${money(r.variance)}
                            </span>
                          `}
                        </td>
                        <td style=${{ textAlign: "right" }}>${r.at_risk > 0 ? money(r.at_risk) : html`<span class="text-muted">—</span>`}</td>
                        <td>
                          <div class="row gap-4" style=${{ flexWrap: "wrap" }}>
                            ${r.statuses.map((s) => html`<${Badge} key=${s} tone=${STATUS_TONE[s] || "neutral"}>${label(s)}<//>`)}
                          </div>
                        </td>
                      </tr>
                    `;
                  })}
                </tbody>
              </table>
            </div>
          `}
        </div>
      `}
    </div>
  `;
}
