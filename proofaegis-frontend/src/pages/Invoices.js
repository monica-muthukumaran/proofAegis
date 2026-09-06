// Invoices.js — the invoice register.
//
// The exception queue answers "what needs work". This answers "where does
// THIS invoice stand", which is the question an AP inbox actually receives:
// a vendor emails asking why INV-2026-1187 has not been paid, and the
// analyst needs the answer without knowing which case it became.
//
// Every row is a projection of one case record from GET /api/exceptions —
// the same payload the queue reads — so an invoice's amount and outcome here
// can never disagree with the case it opens.
import { html, useState, useEffect, useMemo } from "../lib.js";
import * as api from "../services/api.js";
import { Badge, EmptyState, Skeleton, ErrorState } from "../components/ui/primitives.js";
import { MetricCard } from "../components/dashboard/MetricCard.js";
import { ModeBanner } from "../components/ui/ModeBanner.js";
import { RegisterToolbar, makeSortHeader } from "../components/registers/RegisterToolbar.js";
import {
  money, moneyShort, dash, label, isException, isCleared,
  statusOptions, toInvoiceRows, compareBy, STATUS_TONE, TYPE_TONE,
} from "../lib/registers.js";
import { FINANCIAL_IMPACT_HINT } from "../lib/labels.js";

const OUTCOMES = [
  { value: "all", label: "All outcomes" },
  { value: "exceptions", label: "With exception" },
  { value: "cleared", label: "Cleared" },
  { value: "unanalysed", label: "Not analysed" },
];

export function Invoices({ openException }) {
  const [cases, setCases] = useState(null);
  const [error, setError] = useState(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [outcome, setOutcome] = useState("all");
  const [sortKey, setSortKey] = useState("invoice_id");
  const [sortDir, setSortDir] = useState("asc");

  const load = async () => {
    setError(null);
    const r = await api.listExceptions();
    if (r.source === "error") { setError(r.error); setCases(null); return; }
    setCases(r.data || []);
  };
  useEffect(() => { load(); }, []);

  const rows = useMemo(() => toInvoiceRows(cases), [cases]);

  const filtered = useMemo(() => {
    let out = rows;
    if (outcome === "exceptions") out = out.filter(isException);
    else if (outcome === "cleared") out = out.filter(isCleared);
    else if (outcome === "unanalysed") out = out.filter((r) => !r.exception_type);
    if (status !== "all") out = out.filter((r) => r.status === status);
    const q = query.trim().toLowerCase();
    if (q) {
      out = out.filter((r) => [r.invoice_id, r.vendor_name, r.purchase_order_id, r.exception_id, r.description]
        .some((f) => f && String(f).toLowerCase().includes(q)));
    }
    return [...out].sort(compareBy(sortKey, sortDir));
  }, [rows, query, status, outcome, sortKey, sortDir]);

  const setSort = (key) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("asc"); }
  };
  const th = makeSortHeader(sortKey, sortDir, setSort);

  // KPIs describe the FILTERED set, so they stay true as the view narrows —
  // a total that ignores the active filter is a number nobody can act on.
  const totals = useMemo(() => ({
    count: filtered.length,
    invoiced: filtered.reduce((s, r) => s + (Number(r.invoice_amount) || 0), 0),
    atRisk: filtered.reduce((s, r) => s + (Number(r.financial_impact) || 0), 0),
    withException: filtered.filter(isException).length,
  }), [filtered]);

  return html`
    <div class="stack gap-24">
      <div class="stack gap-4">
        <h1 class="text-page-title">Invoices</h1>
        <p class="text-secondary" style=${{ maxWidth: "72ch" }}>
          Every invoice ProofAegis has ingested, cleared and blocked alike — not your ERP's
          invoice master. Search by invoice, vendor or PO to find where one stands, then open
          its case for the evidence behind the outcome.
        </p>
      </div>
      <${ModeBanner} compact=${true} />

      ${error ? html`
        <div class="panel" style=${{ padding: 22 }}>
          <${ErrorState} title="Could not load invoices" message=${error} onRetry=${load} />
        </div>
      ` : !cases ? html`
        <div class="panel stack gap-12" style=${{ padding: 22 }}>
          ${[1, 2, 3, 4].map((i) => html`<${Skeleton} key=${i} height="44px" />`)}
        </div>
      ` : rows.length === 0 ? html`
        <div class="panel" style=${{ padding: 22 }}>
          <${EmptyState} icon="file" title="No invoices yet"
            description="Invoices appear here once a case has been created and its documents read." />
        </div>
      ` : html`
        <div class="kpi-grid">
          <${MetricCard} icon="file" label="Invoices shown" raw=${totals.count}
            format=${(n) => Math.round(n).toLocaleString("en-IN")}
            sublabel=${`of ${rows.length} ingested`} />
          <${MetricCard} icon="layers" label="Invoiced value" raw=${totals.invoiced}
            format=${moneyShort} sublabel="Total across the rows shown" />
          <${MetricCard} icon="shield" label="Value at risk" raw=${totals.atRisk}
            format=${moneyShort} tone="exception" hint=${FINANCIAL_IMPACT_HINT}
            sublabel="Impact on invoices with an exception" />
          <${MetricCard} icon="inbox" label="With exception" raw=${totals.withException}
            format=${(n) => Math.round(n).toLocaleString("en-IN")}
            tone="warning" sublabel="Analysed and failed a check" />
        </div>

        <div class="panel stack gap-16" style=${{ padding: 22 }}>
          <${RegisterToolbar}
            query=${query} setQuery=${setQuery}
            searchLabel="Search invoices"
            placeholder="Search invoice, vendor, PO, description…"
            status=${status} setStatus=${setStatus} statuses=${statusOptions(cases)}
            shown=${filtered.length} total=${rows.length} unit="invoices"
            extra=${html`
              <select class="input" style=${{ maxWidth: 180 }} aria-label="Filter by outcome"
                value=${outcome} onChange=${(e) => setOutcome(e.target.value)}>
                ${OUTCOMES.map((o) => html`<option key=${o.value} value=${o.value}>${o.label}</option>`)}
              </select>
            `}
          />

          ${filtered.length === 0 ? html`
            <p class="text-muted" style=${{ padding: "24px 4px" }}>No invoices match your search.</p>
          ` : html`
            <div class="table-scroll" role="region" aria-label="Invoice register" tabIndex="0">
              <table>
                <thead>
                  <tr>
                    ${th("invoice_id", "Invoice")}
                    ${th("vendor_name", "Vendor")}
                    ${th("purchase_order_id", "Purchase order")}
                    ${th("description", "Line item")}
                    ${th("invoice_amount", "Invoiced", null, "right")}
                    ${th("financial_impact", "At risk", FINANCIAL_IMPACT_HINT, "right")}
                    ${th("exception_type", "Outcome")}
                    ${th("status", "Status")}
                  </tr>
                </thead>
                <tbody>
                  ${filtered.map((r) => html`
                    <tr key=${r.exception_id} class="row-clickable ${r.risk_level ? `risk-${r.risk_level}` : ""}"
                      role="link" tabIndex="0" aria-label=${`Open case ${r.exception_id} for invoice ${r.invoice_id}`}
                      onClick=${() => openException(r.exception_id)}
                      onKeyDown=${(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openException(r.exception_id); } }}>
                      <td class="inv-cell">
                        <span class="id">${r.invoice_id}</span>
                        ${r.duplicate_count > 1 ? html`
                          <div class="text-small" style=${{ color: "var(--exception)", fontWeight: 600 }}
                            title=${`This invoice number appears on ${r.duplicate_count} cases. Open each to see what differs.`}>
                            1 of ${r.duplicate_count} with this number
                          </div>
                        ` : null}
                      </td>
                      <td class="clamp-2" style=${{ maxWidth: 200 }}>${dash(r.vendor_name)}</td>
                      <td><span class="id">${dash(r.purchase_order_id)}</span></td>
                      <td class="clamp-2" style=${{ maxWidth: 220 }}>${dash(r.description)}</td>
                      <td style=${{ textAlign: "right" }}>${money(r.invoice_amount)}</td>
                      <td style=${{ textAlign: "right" }}>${money(r.financial_impact)}</td>
                      <td>
                        ${!r.exception_type
                          ? html`<span class="text-muted text-small">not analysed</span>`
                          : r.exception_type === "no_exception"
                            ? html`<${Badge} tone="verified">cleared<//>`
                            : html`<${Badge} tone=${TYPE_TONE[r.exception_type] || "neutral"}>${label(r.exception_type)}<//>`}
                      </td>
                      <td><${Badge} tone=${STATUS_TONE[r.status] || "neutral"}>${label(r.status)}<//></td>
                    </tr>
                  `)}
                </tbody>
              </table>
            </div>
          `}
        </div>
      `}
    </div>
  `;
}
