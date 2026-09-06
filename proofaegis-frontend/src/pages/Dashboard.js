import { html, useState, useEffect } from "../lib.js";
import * as api from "../services/api.js";
import { MetricCard } from "../components/dashboard/MetricCard.js";
import { ActivityTimeline } from "../components/dashboard/ActivityTimeline.js";
import { ExceptionSummaryChart } from "../components/dashboard/ExceptionSummaryChart.js";
import { Badge, Icon, EmptyState, Skeleton, ErrorState } from "../components/ui/primitives.js";
import { ModeBanner } from "../components/ui/ModeBanner.js";
import { MATCH_SCORE_HINT, VALUE_ON_HOLD_HINT } from "../lib/labels.js";
import { FirstRunTourOffer } from "../components/ui/FirstRunTourOffer.js";

function formatInr(n) {
  if (n == null) return "—";
  if (n >= 100000) return `₹${(n / 100000).toFixed(2)}L`;
  return `₹${Number(n).toLocaleString("en-IN")}`;
}

// The "priority" case is whichever open exception carries the most money,
// computed from the data — not a pinned demo ID.
const OPEN_STATUSES = new Set([
  "exception_detected", "assigned", "awaiting_procurement", "awaiting_receiving", "awaiting_vendor",
]);

function pickPriority(items) {
  const open = (items || []).filter((e) => OPEN_STATUSES.has(e.status));
  const pool = open.length ? open : (items || []);
  if (!pool.length) return null;
  return pool.reduce((best, e) =>
    (Number(e.financial_impact || 0) > Number(best.financial_impact || 0) ? e : best), pool[0]);
}

function headlineFor(exception) {
  const label = (exception.exception_type || "exception").replaceAll("_", " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}

const STATUS_TONE = {
  exception_detected: "exception", assigned: "warning", awaiting_procurement: "warning",
  awaiting_receiving: "warning", awaiting_vendor: "accent", approved_with_exception: "verified",
  resolved: "verified", closed: "neutral", processing: "neutral", received: "neutral",
};

export function Dashboard({ openException, onCreateException, onStartTour, navigateToQueue }) {
  const [exceptions, setExceptions] = useState(null);
  const [summary, setSummary] = useState(null);
  const [activity, setActivity] = useState([]);
  const [error, setError] = useState(null);
  const [showEmpty, setShowEmpty] = useState(false);

  const load = async () => {
    setError(null);
    const [excRes, summaryRes] = await Promise.all([api.listExceptions(), api.getDashboardSummary()]);
    if (excRes.source === "error") { setError(excRes.error); setExceptions(null); return; }
    setExceptions(excRes.data);
    setSummary(summaryRes.source === "error" ? null : summaryRes.data);

    // Activity comes from the real audit trail of the highest-impact open
    // case. It used to be imported straight from mockData, so the panel
    // showed invented events even against a fully live backend.
    const items = excRes.data || [];
    const focus = pickPriority(items);
    if (focus) {
      const auditRes = await api.getAudit(focus.exception_id);
      setActivity(auditRes.source === "error" ? [] : (auditRes.data || []).slice(-6).reverse());
    } else {
      setActivity([]);
    }
  };

  useEffect(() => { load(); }, []);

  const effectiveExceptions = showEmpty ? [] : exceptions;
  const priority = pickPriority(effectiveExceptions || []);

  // "Recent exceptions" has to mean recent: at portfolio scale the table was
  // rendering every record in the workspace, cleared invoices included.
  const recentExceptions = (effectiveExceptions || [])
    .filter((e) => e.exception_type && e.exception_type !== "no_exception")
    .slice()
    .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")))
    .slice(0, 8);

  return html`
    <div class="stack gap-24">
      <${FirstRunTourOffer} onStartTour=${onStartTour} />

      <div class="row" style=${{ justifyContent: "space-between", flexWrap: "wrap", gap: 16 }}>
        <div class="stack gap-4">
          <h1 class="text-page-title">Invoice Exception Intelligence</h1>
          <p class="text-secondary">Review blocked invoices, understand the evidence, and move each case toward resolution. Analytics shows what a per-invoice check would have missed.</p>
        </div>
        <div class="row gap-8" style=${{ flexWrap: "wrap" }}>
          <button class="btn btn-secondary" onClick=${onCreateException}><${Icon} name="upload" size=${15} /> New case from PDFs</button>
          <button class="btn btn-primary" onClick=${onStartTour}><${Icon} name="play" size=${15} /> Start guided tour</button>
        </div>
      </div>

      <div class="row gap-8 workspace-meta" style=${{ flexWrap: "wrap" }}>
        <${ModeBanner} />
        <label class="text-muted text-small row gap-8 workspace-meta-toggle" style=${{ cursor: "pointer" }}>
          <input type="checkbox" checked=${showEmpty} onChange=${(e) => setShowEmpty(e.target.checked)} />
          Preview empty workspace
        </label>
      </div>

      ${error ? html`
        <div class="panel"><${ErrorState} title="Could not load the workspace" message=${error} onRetry=${load} /></div>
      ` : !effectiveExceptions ? html`
        <div class="kpi-grid">${[1,2,3,4].map((i) => html`<${Skeleton} key=${i} height="92px" />`)}</div>
      ` : effectiveExceptions.length === 0 ? html`
        <div class="panel">
          <${EmptyState}
            icon="inbox"
            title="Your workspace is ready"
            description="Upload an invoice, purchase order, and goods receipt to begin investigating an exception."
            action=${html`
              <div class="row gap-8">
                <button class="btn btn-primary" onClick=${onCreateException}><${Icon} name="upload" size=${15}/> New case from PDFs<//>
              </div>
            `}
          />
        </div>
      ` : html`
        <div class="kpi-grid" data-tour="dashboard-metrics">
          <${MetricCard} icon="inbox" label="Open exceptions" value="—" raw=${summary ? summary.open_exceptions_count : null} format=${(n) => Math.round(n)} sublabel=${summary ? `${summary.clean_count} invoices cleared` : "Across current workspace"} />
          <${MetricCard} icon="graph" label="Value on hold" value="—" raw=${summary ? summary.value_on_hold : null} format=${formatInr} sublabel="Blocked pending review" hint=${VALUE_ON_HOLD_HINT} tone="exception" />
          <${MetricCard} icon="clock" label="Awaiting action" value="—" raw=${effectiveExceptions.filter((e) => e.status.startsWith("awaiting")).length} format=${(n) => Math.round(n)} sublabel="Procurement and Receiving" tone="warning" />
          <${MetricCard} icon="check" label="Average match score" value="—" raw=${summary ? summary.average_match_score : null} format=${(n) => `${n.toFixed(1)}%`} sublabel="Fields that agreed" hint=${MATCH_SCORE_HINT} tone="verified" />
        </div>

        <div class="row gap-24" style=${{ alignItems: "flex-start", flexWrap: "wrap" }}>
          <div class="stack gap-24" style=${{ flex: "2 1 480px", minWidth: 320 }}>
            ${priority ? html`
              <div class="panel stack gap-16" style=${{ padding: 22, borderColor: "rgba(251,113,133,0.35)" }}>
                <div class="row" style=${{ justifyContent: "space-between" }}>
                  <${Badge} tone="exception">Priority exception<//>
                  <span class="text-muted text-small">${priority.status.replaceAll("_", " ")}</span>
                </div>
                <div class="stack gap-4">
                  <h3 class="text-section-title">${headlineFor(priority)}</h3>
                  <p class="text-secondary">${priority.invoice_id} · ${priority.vendor_name}</p>
                </div>
                <div class="row gap-24" style=${{ flexWrap: "wrap" }}>
                  <div>
                    <div class="text-muted text-small">Financial impact</div>
                    <div style=${{ fontWeight: 700 }}>
                      ${priority.financial_impact != null ? formatInr(priority.financial_impact) : "—"}
                    </div>
                  </div>
                  <div>
                    <div class="text-muted text-small">Owner</div>
                    <div style=${{ fontWeight: 700 }}>${priority.assigned_team || "Unassigned"}</div>
                  </div>
                  <div>
                    <div class="text-muted text-small">
                      Match score<abbr class="hint-mark" title=${MATCH_SCORE_HINT}>?</abbr>
                    </div>
                    <div style=${{ fontWeight: 700 }}>
                      ${priority.match_score != null ? `${priority.match_score}%` : "—"}
                    </div>
                  </div>
                </div>
                <button class="btn btn-primary" style=${{ width: "fit-content" }} onClick=${() => openException(priority.exception_id)}>
                  Review exception <${Icon} name="arrowRight" size=${15} />
                </button>
              </div>
            ` : null}

            <div class="panel" style=${{ padding: 22 }}>
              <div class="row" style=${{ justifyContent: "space-between", marginBottom: 14 }}>
                <h3 class="text-section-title">Recent exceptions</h3>
                <button class="text-button" onClick=${() => navigateToQueue && navigateToQueue()}>View all</button>
              </div>
              <div class="table-scroll" role="region" aria-label="Recent exceptions" tabIndex="0">
                <table>
                  <thead><tr><th>ID</th><th>Invoice</th><th>Vendor</th><th>Amount</th><th>Status</th></tr></thead>
                  <tbody>
                    ${recentExceptions.map((e) => html`
                      <tr key=${e.exception_id} class="row-clickable ${e.risk_level ? `risk-${e.risk_level}` : ""}" role="link" tabIndex="0" aria-label=${`Open ${e.exception_id}`} onClick=${() => openException(e.exception_id)} onKeyDown=${(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); openException(e.exception_id); } }}>
                        <td>${e.exception_id}</td>
                        <td>${e.invoice_id}</td>
                        <td class="clamp-2" style=${{ maxWidth: 200 }}>${e.vendor_name}</td>
                        <td>${e.invoice_amount != null ? `₹${Number(e.invoice_amount).toLocaleString("en-IN")}` : "—"}</td>
                        <td><${Badge} tone=${STATUS_TONE[e.status] || "neutral"}>${e.status.replaceAll("_", " ")}<//></td>
                      </tr>
                    `)}
                  </tbody>
                </table>
              </div>
            </div>
          </div>

          <div class="stack gap-24" style=${{ flex: "1 1 300px", minWidth: 280 }}>
            <div class="panel" style=${{ padding: 22 }}>
              <h3 class="text-section-title" style=${{ marginBottom: 14 }}>Exception types</h3>
              <${ExceptionSummaryChart} breakdown=${summary && summary.exception_type_breakdown} valueBreakdown=${summary && summary.exception_type_value} />
            </div>
            <div class="panel" style=${{ padding: 22 }}>
              <h3 class="text-section-title" style=${{ marginBottom: 14 }}>Activity</h3>
              <${ActivityTimeline} events=${activity} />
            </div>
          </div>
        </div>
      `}
    </div>
  `;
}
