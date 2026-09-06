// Vendors.js — the vendor register.
//
// The analytics screen already plots vendors as a risk scatter, which answers
// "who should we look at first" at a glance. It cannot answer "tell me about
// THIS vendor", because a bubble has no room for the reasoning. This page is
// the readable form of the same data: one card per vendor, ranked by money at
// risk, each carrying the sentence that explains its own ranking.
//
// Nothing here is computed in the browser. GET /api/analytics/vendor-risk
// returns exception_rate, value_at_risk, risk_band and a `why_at_risk`
// sentence that backend/services/analytics_service.py assembles from those
// same figures — deterministically, citing no number it did not compute. So
// the explanation on a card cannot drift from the numbers beside it, and no
// model wrote either.
import { html, useState, useEffect, useMemo } from "../lib.js";
import * as api from "../services/api.js";
import { Badge, EmptyState, Skeleton, ErrorState, Icon } from "../components/ui/primitives.js";
import { MetricCard } from "../components/dashboard/MetricCard.js";
import { ModeBanner } from "../components/ui/ModeBanner.js";
import { money, moneyShort, dash, label } from "../lib/registers.js";
import { MATCH_SCORE_HINT, FINANCIAL_IMPACT_HINT } from "../lib/labels.js";

const WINDOWS = [
  { days: 90, label: "90 days" },
  { days: 180, label: "6 months" },
  { days: 365, label: "12 months" },
];

const BAND_TONE = { high: "exception", medium: "warning", low: "verified" };

const BAND_HINT =
  "Assigned by rule, not by model: high at a 40% exception rate or ₹10L at " +
  "risk, medium at 20% or ₹2.5L. A vendor with few invoices can reach a high " +
  "rate on thin evidence — the invoice count is on the card for that reason.";

const RATE_HINT =
  "Share of this vendor's invoices that failed a check. Cleared invoices are " +
  "the denominator, so a vendor is not penalised for sending many invoices.";

const SORTS = [
  { value: "value_at_risk", label: "Value at risk" },
  { value: "exception_rate", label: "Exception rate" },
  { value: "invoice_count", label: "Invoice volume" },
  { value: "average_open_age_days", label: "Days open" },
  { value: "vendor_name", label: "Name" },
];

function pct(v) {
  return v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`;
}

function VendorCard({ vendor, onViewExceptions }) {
  const recurring = Object.entries(vendor.recurring_types || {}).slice(0, 3);
  const initials = (vendor.vendor_name || "?")
    .split(/\s+/).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
  // analytics_service.py groups on `vendor_id or vendor_name`, so a vendor
  // with no ID on file comes back with its own name in that field. Printing
  // it as an ID under the heading just says the name twice.
  const hasRealId = vendor.vendor_id && vendor.vendor_id !== vendor.vendor_name;

  return html`
    <article class="panel vendor-card stack gap-16">
      <div class="row gap-12" style=${{ alignItems: "flex-start" }}>
        <div class="panel-elevated vendor-avatar">${initials}</div>
        <div class="stack gap-2" style=${{ minWidth: 0, flex: 1 }}>
          <h3 class="text-section-title clamp-2" style=${{ margin: 0 }}>${dash(vendor.vendor_name)}</h3>
          <div class="text-muted text-small">
            ${hasRealId ? html`<span class="id">${vendor.vendor_id}</span>` : null}
            ${hasRealId && vendor.business_unit ? " · " : null}
            ${vendor.business_unit || (hasRealId ? null : html`<span class="text-muted">No vendor ID on file</span>`)}
          </div>
        </div>
        <span title=${BAND_HINT}>
          <${Badge} tone=${BAND_TONE[vendor.risk_band] || "neutral"}>${label(vendor.risk_band)} risk<//>
        </span>
      </div>

      <div class="vendor-stats">
        <div class="stack gap-2" title=${FINANCIAL_IMPACT_HINT}>
          <span class="text-muted text-small">Value at risk</span>
          <strong>${money(vendor.value_at_risk)}</strong>
        </div>
        <div class="stack gap-2" title=${RATE_HINT}>
          <span class="text-muted text-small">Exception rate</span>
          <strong>${pct(vendor.exception_rate)}</strong>
        </div>
        <div class="stack gap-2">
          <span class="text-muted text-small">Invoices</span>
          <strong>${vendor.exception_count} of ${vendor.invoice_count}</strong>
        </div>
        <div class="stack gap-2" title=${MATCH_SCORE_HINT}>
          <span class="text-muted text-small">Avg match</span>
          <strong>${vendor.average_match_score === null || vendor.average_match_score === undefined ? "—" : `${vendor.average_match_score}%`}</strong>
        </div>
        <div class="stack gap-2">
          <span class="text-muted text-small">Avg days open</span>
          <strong>${vendor.average_open_age_days ? `${vendor.average_open_age_days}d` : "—"}</strong>
        </div>
        <div class="stack gap-2">
          <span class="text-muted text-small">Invoiced</span>
          <strong>${moneyShort(vendor.invoiced_value)}</strong>
        </div>
      </div>

      ${vendor.why_at_risk ? html`
        <p class="text-secondary text-small vendor-why">${vendor.why_at_risk}</p>
      ` : null}

      ${recurring.length ? html`
        <div class="row gap-4" style=${{ flexWrap: "wrap" }}>
          ${recurring.map(([type, count]) => html`
            <${Badge} key=${type} tone="neutral">${label(type)} · ${count}<//>
          `)}
        </div>
      ` : null}

      <button class="btn btn-secondary btn-sm" style=${{ alignSelf: "flex-start" }}
        onClick=${() => onViewExceptions(vendor.vendor_name)}
        aria-label=${`View exceptions for ${vendor.vendor_name}`}>
        View exceptions <${Icon} name="arrowRight" size=${14} />
      </button>
    </article>
  `;
}

export function Vendors({ onViewExceptions }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(365);
  const [query, setQuery] = useState("");
  const [band, setBand] = useState("all");
  const [sortKey, setSortKey] = useState("value_at_risk");

  const load = async (windowDays) => {
    setError(null);
    setData(null);
    // The backend caps this at MAX_VENDOR_ROWS; 100 asks for the whole
    // register rather than the analytics chart's top slice.
    const r = await api.getVendorRisk(windowDays, 100);
    if (r.source === "error") { setError(r.error); return; }
    setData(r.data);
  };
  useEffect(() => { load(days); }, [days]);

  const vendors = (data && data.vendors) || [];

  const filtered = useMemo(() => {
    let out = vendors;
    if (band !== "all") out = out.filter((v) => v.risk_band === band);
    const q = query.trim().toLowerCase();
    if (q) {
      out = out.filter((v) => [v.vendor_name, v.vendor_id, v.business_unit, v.top_exception_type]
        .some((f) => f && String(f).toLowerCase().includes(q)));
    }
    return [...out].sort((a, b) => {
      if (sortKey === "vendor_name") return String(a.vendor_name || "").localeCompare(String(b.vendor_name || ""));
      return (Number(b[sortKey]) || 0) - (Number(a[sortKey]) || 0);
    });
  }, [vendors, query, band, sortKey]);

  const totals = useMemo(() => ({
    count: filtered.length,
    atRisk: filtered.reduce((s, v) => s + (Number(v.value_at_risk) || 0), 0),
    high: filtered.filter((v) => v.risk_band === "high").length,
    invoices: filtered.reduce((s, v) => s + (Number(v.invoice_count) || 0), 0),
  }), [filtered]);

  return html`
    <div class="stack gap-24">
      <div class="row" style=${{ justifyContent: "space-between", flexWrap: "wrap", gap: 16 }}>
        <div class="stack gap-4">
          <h1 class="text-page-title">Vendors</h1>
          <p class="text-secondary" style=${{ maxWidth: "70ch" }}>
            Ranked by money at risk, then by how often they fail. Every figure is arithmetic over
            stored case outcomes — including the sentence explaining each ranking. No model
            produces a number or a claim on this page.
          </p>
        </div>
        <div class="row gap-4">
          ${WINDOWS.map((w) => html`
            <button key=${w.days} class="btn btn-sm ${days === w.days ? "btn-primary" : "btn-secondary"}"
              onClick=${() => setDays(w.days)}>${w.label}</button>
          `)}
        </div>
      </div>
      <${ModeBanner} compact=${true} />

      ${error ? html`
        <div class="panel" style=${{ padding: 22 }}>
          <${ErrorState} title="Could not load vendors" message=${error} onRetry=${() => load(days)} />
        </div>
      ` : !data ? html`
        <div class="stack gap-16">
          <div class="kpi-grid">${[1, 2, 3, 4].map((i) => html`<${Skeleton} key=${i} height="96px" />`)}</div>
          <div class="vendor-grid">${[1, 2, 3, 4, 5, 6].map((i) => html`<${Skeleton} key=${i} height="230px" />`)}</div>
        </div>
      ` : vendors.length === 0 ? html`
        <div class="panel" style=${{ padding: 22 }}>
          <${EmptyState} icon="building" title="No vendor activity in this window"
            description="Widen the window, or ingest invoices to build a vendor history." />
        </div>
      ` : html`
        <div class="kpi-grid">
          <${MetricCard} icon="building" label="Vendors shown" raw=${totals.count}
            format=${(n) => Math.round(n).toLocaleString("en-IN")}
            sublabel=${`of ${data.vendor_count} active`} />
          <${MetricCard} icon="shield" label="Value at risk" raw=${totals.atRisk}
            format=${moneyShort} tone="exception" hint=${FINANCIAL_IMPACT_HINT}
            sublabel="Open exceptions across these vendors" />
          <${MetricCard} icon="inbox" label="High-risk vendors" raw=${totals.high}
            format=${(n) => Math.round(n).toLocaleString("en-IN")}
            tone="warning" hint=${BAND_HINT} sublabel="By exception rate or exposure" />
          <${MetricCard} icon="file" label="Invoices covered" raw=${totals.invoices}
            format=${(n) => Math.round(n).toLocaleString("en-IN")}
            sublabel=${`Last ${data.window_days} days`} />
        </div>

        <div class="row gap-12" style=${{ flexWrap: "wrap" }}>
          <input class="input" style=${{ maxWidth: 300 }} aria-label="Search vendors"
            placeholder="Search vendor, ID, business unit…"
            value=${query} onInput=${(e) => setQuery(e.target.value)} />
          <select class="input" style=${{ maxWidth: 170 }} aria-label="Filter by risk band"
            value=${band} onChange=${(e) => setBand(e.target.value)}>
            <option value="all">All risk bands</option>
            <option value="high">High risk</option>
            <option value="medium">Medium risk</option>
            <option value="low">Low risk</option>
          </select>
          <select class="input" style=${{ maxWidth: 190 }} aria-label="Sort vendors"
            value=${sortKey} onChange=${(e) => setSortKey(e.target.value)}>
            ${SORTS.map((s) => html`<option key=${s.value} value=${s.value}>Sort by ${s.label.toLowerCase()}</option>`)}
          </select>
          <span class="text-muted text-small" style=${{ marginLeft: "auto", alignSelf: "center" }}>
            ${filtered.length} of ${vendors.length} vendors
          </span>
        </div>

        ${filtered.length === 0 ? html`
          <div class="panel" style=${{ padding: 22 }}>
            <p class="text-muted">No vendors match your search.</p>
          </div>
        ` : html`
          <div class="vendor-grid">
            ${filtered.map((v) => html`
              <${VendorCard} key=${v.vendor_id} vendor=${v} onViewExceptions=${onViewExceptions} />
            `)}
          </div>
        `}
      `}
    </div>
  `;
}
