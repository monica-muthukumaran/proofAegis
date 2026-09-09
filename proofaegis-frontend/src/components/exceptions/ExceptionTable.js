import { html, useState, useMemo } from "../../lib.js";
import { Badge } from "../ui/primitives.js";
import { MATCH_SCORE_HINT } from "../../lib/labels.js";

const STATUS_TONE = {
  exception_detected: "exception", assigned: "warning", awaiting_procurement: "warning",
  awaiting_receiving: "warning", awaiting_vendor: "accent", approved_with_exception: "verified",
  resolved: "verified", closed: "neutral", processing: "neutral", received: "neutral",
};

const STATUS_OPTIONS = [
  "all", "exception_detected", "assigned", "awaiting_procurement", "awaiting_receiving",
  "awaiting_vendor", "approved_with_exception", "resolved", "closed",
];

// The queue's job is triage, so it opens on work that needs doing. Cleared
// invoices are still here and still one click away — a system that can only
// ever show problems gives a reviewer no way to judge whether it
// discriminates — but they do not get to bury the exceptions.
const OUTCOME_OPTIONS = [
  { value: "exceptions", label: "Exceptions" },
  { value: "cleared", label: "Cleared" },
  { value: "all", label: "All invoices" },
];

// How loudly the queue says each finding, on the theme's three-step scale.
//
// This had three DUPLICATE KEYS — a second line repeated vendor_mismatch,
// tax_total_mismatch and duplicate_invoice, and "last one wins" silently
// overrode the first block. The damage was not cosmetic: it demoted
// `duplicate_invoice` from critical to exception, and paying the same invoice
// twice is the single most serious thing this product can find. It never
// threw and never appeared in a diff as a behaviour change, which is why
// no-dupe-keys is now on in eslint.config.js.
//
// The scale, restored and stated once:
//
//   critical  — money may already have moved, or this is a known fraud
//               vector. Reserved for exactly two findings.
//   exception — a proven discrepancy in what is being billed.
//   warning   — the case is incomplete rather than proven wrong; it is
//               waiting on a document, not on a decision.
const TYPE_TONE = {
  duplicate_invoice: "critical",
  payment_details_changed: "critical",

  price_variance: "exception",
  po_over_billed: "exception",
  missing_purchase_order: "exception",
  vendor_mismatch: "exception",
  tax_total_mismatch: "exception",

  quantity_variance: "warning",
  missing_goods_receipt: "warning",
  // The documents on the case do not describe the same transaction. Not a
  // billing discrepancy — it means no number computed from them can be
  // trusted, so it is "incomplete" rather than "proven wrong".
  unrelated_documents: "warning",

  // Cross-case findings. Both are invisible to any per-invoice check, which
  // is the product's actual claim, so neither may render as undifferentiated
  // grey.
  //
  // vendor_price_drift is schemas.py's own words the "price equivalent of
  // PO_OVER_BILLED", and po_over_billed is an exception — so this is too. It
  // was falling through to the neutral default, which showed the queue's most
  // distinctive finding in the same grey as a cleared invoice.
  vendor_price_drift: "exception",
  // Deliberately the quietest tone, and this entry exists to record that as a
  // decision rather than leave it to the fallback. schemas.py: a recurring
  // series is what rent, a retainer or an AMC looks like to a duplicate
  // check, and shouting about those is the fastest way to lose a reviewer's
  // trust. Reported, but reported low.
  recurring_suspected: "neutral",
};

// A queue row exists from the moment a case is created, which is BEFORE any
// document has been uploaded — so every displayed field has to tolerate null
// rather than assuming an analysed case.
const dash = (value) => (value === null || value === undefined || value === "" ? "—" : value);

function label(value) {
  return value ? String(value).replaceAll("_", " ") : null;
}

function money(value) {
  if (value === null || value === undefined) return "—";
  return `₹${Number(value).toLocaleString("en-IN")}`;
}

export function ExceptionTable({ exceptions, onOpen, initialQuery = "" }) {
  // Seeded, not controlled. A vendor card can hand the queue a name to search
  // for, but from that moment the box belongs to the analyst — arriving with
  // a term prefilled and being unable to clear it is worse than arriving
  // empty.
  const [query, setQuery] = useState(initialQuery);
  const [statusFilter, setStatusFilter] = useState("all");
  const [outcome, setOutcome] = useState("exceptions");
  const [sortKey, setSortKey] = useState("exception_id");
  const [sortDir, setSortDir] = useState("asc");

  const filtered = useMemo(() => {
    let rows = exceptions;
    if (outcome === "exceptions") {
      rows = rows.filter((e) => e.exception_type && e.exception_type !== "no_exception");
    } else if (outcome === "cleared") {
      rows = rows.filter((e) => e.exception_type === "no_exception");
    }
    if (statusFilter !== "all") rows = rows.filter((e) => e.status === statusFilter);
    if (query.trim()) {
      const q = query.trim().toLowerCase();
      rows = rows.filter((e) =>
        [e.title, e.exception_id, e.invoice_id, e.vendor_name, e.purchase_order_id, e.exception_type]
          .some((field) => field && String(field).toLowerCase().includes(q))
      );
    }
    rows = [...rows].sort((a, b) => {
      const av = a[sortKey], bv = b[sortKey];
      // Unanalysed rows sort last in both directions — they are not "zero",
      // they are "not known yet", and burying them keeps triage useful.
      if (av === null || av === undefined) return 1;
      if (bv === null || bv === undefined) return -1;
      const cmp = typeof av === "number" && typeof bv === "number"
        ? av - bv
        : String(av).localeCompare(String(bv));
      return sortDir === "asc" ? cmp : -cmp;
    });
    return rows;
  }, [exceptions, query, statusFilter, outcome, sortKey, sortDir]);

  const toggleSort = (key) => {
    if (sortKey === key) setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    else { setSortKey(key); setSortDir("asc"); }
  };

  const th = (key, heading, hint) => html`
    <th aria-sort=${sortKey === key ? (sortDir === "asc" ? "ascending" : "descending") : "none"}>
      <button class="sort-button" onClick=${() => toggleSort(key)} title=${hint || undefined}>
        ${heading}${hint ? html`<abbr class="hint-mark" title=${hint}>?</abbr>` : ""} ${sortKey === key ? (sortDir === "asc" ? "↑" : "↓") : ""}
      </button>
    </th>
  `;

  return html`
    <div class="stack gap-16">
      <div class="row gap-12" style=${{ flexWrap: "wrap" }}>
        <input class="input" style=${{ maxWidth: 320 }} aria-label="Search exceptions" placeholder="Search exception, invoice, vendor, PO…"
          value=${query} onInput=${(e) => setQuery(e.target.value)} />
        <select class="input" style=${{ maxWidth: 180 }} aria-label="Filter by outcome"
          value=${outcome} onChange=${(e) => setOutcome(e.target.value)}>
          ${OUTCOME_OPTIONS.map((o) => html`<option key=${o.value} value=${o.value}>${o.label}</option>`)}
        </select>
        <select class="input" style=${{ maxWidth: 200 }} aria-label="Filter by status" value=${statusFilter} onChange=${(e) => setStatusFilter(e.target.value)}>
          ${STATUS_OPTIONS.map((s) => html`<option key=${s} value=${s}>${s === "all" ? "All statuses" : s.replaceAll("_", " ")}</option>`)}
        </select>
        <span class="text-muted text-small" style=${{ marginLeft: "auto", alignSelf: "center" }}>${filtered.length} of ${exceptions.length}</span>
      </div>

      ${filtered.length === 0 ? html`<p class="text-muted" style=${{ padding: "24px 4px" }}>No exceptions match your search.</p>` : html`
        <div class="table-scroll" role="region" aria-label="Exception results" tabIndex="0">
          <table>
            <thead>
              <tr>
                ${th("exception_id", "Case")}
                ${th("invoice_id", "Invoice")}
                ${th("vendor_name", "Vendor")}
                ${th("exception_type", "Type")}
                ${th("invoice_amount", "Amount")}
                ${th("financial_impact", "At risk")}
                ${th("match_score", "Match", MATCH_SCORE_HINT)}
                ${th("assigned_team", "Owner")}
                ${th("status", "Status")}
              </tr>
            </thead>
            <tbody>
              ${filtered.map((e) => html`
                <tr key=${e.exception_id} class="row-clickable ${e.risk_level ? `risk-${e.risk_level}` : ""}" role="link" tabIndex="0" aria-label=${`Open ${e.title || e.exception_id}`} onClick=${() => onOpen(e.exception_id)} onKeyDown=${(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onOpen(e.exception_id); } }}>
                  ${/* A named case leads with its name and keeps the reference
                       underneath: the reference is what every audit event and
                       every other system calls it, so it stays quotable. An
                       unnamed one is unchanged. */ ""}
                  <td>
                    ${e.title
                      ? html`
                        <div class="stack gap-2">
                          <span style=${{ fontWeight: 600 }}>${e.title}</span>
                          <span class="id text-muted text-small">${e.exception_id}</span>
                        </div>`
                      : html`<span class="id">${e.exception_id}</span>`}
                  </td>
                  <td><span class="id">${dash(e.invoice_id)}</span></td>
                  <td class="clamp-2" style=${{ maxWidth: 190 }}>${dash(e.vendor_name)}</td>
                  <td>
                    ${e.exception_type === "no_exception"
                      ? html`<${Badge} tone="verified">cleared<//>`
                      : e.exception_type
                        ? html`<${Badge} tone=${TYPE_TONE[e.exception_type] || "neutral"}>${label(e.exception_type)}<//>`
                        : html`<span class="text-muted text-small">not analysed</span>`}
                  </td>
                  <td>${money(e.invoice_amount)}</td>
                  <td>${money(e.financial_impact)}</td>
                  <td title=${MATCH_SCORE_HINT}>${e.match_score != null ? `${e.match_score}%` : "—"}</td>
                  <td>${dash(e.assigned_team)}</td>
                  <td><${Badge} tone=${STATUS_TONE[e.status] || "neutral"}>${label(e.status)}<//></td>
                </tr>
              `)}
            </tbody>
          </table>
        </div>
      `}
    </div>
  `;
}
