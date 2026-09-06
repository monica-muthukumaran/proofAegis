// Analytics.js — the argument for the product.
//
// The rest of ProofAegis investigates one blocked invoice. This screen makes
// the case, and the order of it is the pitch:
//
//   1. WHAT A PER-INVOICE CHECK WOULD HAVE MISSED. Most AP automation decides
//      what to approve. This decides what shouldn't have passed, and the
//      cross-case panel is the only figure on the page a commercial product
//      does not already produce. It leads.
//   2. HOW OFTEN THE GUARDRAIL FIRED. The one place in the product that shows
//      its own AI being wrong.
//   3. MEASURED ACCURACY, with every disagreement named.
//   4. Then the vendor ranking, trend and ageing — the substrate that makes
//      the first three trustworthy rather than the headline.
//
// Everything is deterministic arithmetic over the portfolio. No model produces
// a figure on this page, and the page says so, because a controller acting on
// "this vendor is your problem" needs to know the claim is arithmetic.
import { html, useState, useEffect } from "../lib.js";
import * as api from "../services/api.js";
import { VendorRiskChart } from "../components/analytics/VendorRiskChart.js";
import { TrendChart } from "../components/analytics/TrendChart.js";
import { AgeingChart } from "../components/analytics/AgeingChart.js";
import { CrossCasePanel } from "../components/analytics/CrossCasePanel.js";
import { DisagreementLedger } from "../components/analytics/DisagreementLedger.js";
import { AccuracyTable } from "../components/analytics/AccuracyTable.js";
import { MetricCard } from "../components/dashboard/MetricCard.js";
import { Skeleton, ErrorState, Badge, Icon } from "../components/ui/primitives.js";
import { ModeBanner } from "../components/ui/ModeBanner.js";

const WINDOWS = [
  { days: 90, label: "90 days" },
  { days: 180, label: "6 months" },
  { days: 365, label: "12 months" },
];

function formatInr(n) {
  if (n == null) return "—";
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(2)}Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(2)}L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}

export function Analytics() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [days, setDays] = useState(365);
  const [loading, setLoading] = useState(true);

  const load = async (windowDays) => {
    setLoading(true);
    setError(null);
    const r = await api.getAnalyticsOverview(windowDays);
    if (r.source === "error") { setError(r.error); setData(null); setLoading(false); return; }
    setData(r.data);
    setLoading(false);
  };

  useEffect(() => { load(days); }, [days]);

  const summary = data && data.summary;

  return html`
    <div class="stack gap-24">
      <div class="row" style=${{ justifyContent: "space-between", flexWrap: "wrap", gap: 16 }}>
        <div class="stack gap-4">
          <h1 class="text-page-title">What shouldn't have passed</h1>
          <p class="text-secondary" style=${{ maxWidth: "68ch" }}>
            Most AP automation decides what to approve. ProofAegis investigates what failed —
            and what shouldn't have passed. Everything below is arithmetic over stored outcomes.
          </p>
        </div>
        <div class="row gap-4">
          ${WINDOWS.map((w) => html`
            <button key=${w.days} class="btn btn-sm ${days === w.days ? "btn-primary" : "btn-secondary"}"
              onClick=${() => setDays(w.days)}>${w.label}</button>
          `)}
        </div>
      </div>

      <div class="row gap-8" style=${{ flexWrap: "wrap" }}>
        <${ModeBanner} compact=${true} />
        <${Badge} tone="verified">All figures computed in code — not by AI<//>
      </div>

      ${error ? html`
        <div class="panel"><${ErrorState} title="Could not load analytics" message=${error} onRetry=${() => load(days)} /></div>
      ` : loading || !data ? html`
        <div class="kpi-grid">${[1, 2, 3, 4].map((i) => html`<${Skeleton} key=${i} height="92px" />`)}</div>
        <${Skeleton} height="320px" />
      ` : html`
        ${data.cross_case ? html`<${CrossCasePanel} data=${data.cross_case} />` : null}

        <div class="kpi-grid">
          <${MetricCard} icon="inbox" label="Invoices analysed" value="—"
            raw=${summary.invoice_count} format=${(n) => Math.round(n).toLocaleString("en-IN")}
            sublabel=${`Across ${data.vendor_risk.vendor_count} vendors`} />
          <${MetricCard} icon="check" label="Clean match rate" value="—"
            raw=${summary.clean_rate * 100} format=${(n) => `${n.toFixed(1)}%`}
            sublabel=${`${summary.clean_count} passed with no exception`} tone="verified" />
          <${MetricCard} icon="graph" label="Exception rate" value="—"
            raw=${summary.exception_rate * 100} format=${(n) => `${n.toFixed(1)}%`}
            sublabel=${`${summary.exception_count} exceptions raised`} tone="warning" />
          <${MetricCard} icon="clock" label="Value at risk" value="—"
            raw=${summary.value_at_risk} format=${formatInr}
            sublabel=${`${(summary.value_at_risk_share * 100).toFixed(1)}% of invoiced value, still open`}
            tone="exception" />
        </div>

        ${data.trust ? html`<${DisagreementLedger} trust=${data.trust} />` : null}

        <${AccuracyTable} />

        <div class="panel stack gap-16" style=${{ padding: 22 }}>
          <div class="stack gap-2">
            <h3 class="text-section-title">Where failures concentrate</h3>
            <p class="text-muted text-small">
              How often each vendor produces an exception, against how much money that puts at risk.
              A high rate on small invoices and a low rate on large ones are different problems —
              ranking on either number alone hides one of them.
            </p>
          </div>
          <${VendorRiskChart} vendors=${data.vendor_risk.vendors} />
        </div>

        <div class="row gap-24" style=${{ alignItems: "flex-start", flexWrap: "wrap" }}>
          <div class="panel stack gap-16" style=${{ padding: 22, flex: "2 1 460px", minWidth: 320 }}>
            <div class="stack gap-2">
              <h3 class="text-section-title">Is this getting better or worse?</h3>
              <p class="text-muted text-small">
                Monthly volume split into clean and exception, with the exception rate overlaid.
              </p>
            </div>
            <${TrendChart} points=${data.trend.points} />
          </div>

          <div class="panel stack gap-16" style=${{ padding: 22, flex: "1 1 300px", minWidth: 280 }}>
            <div class="stack gap-2">
              <h3 class="text-section-title">Ageing and SLA</h3>
              <p class="text-muted text-small">How long open exceptions have been waiting.</p>
            </div>
            <${AgeingChart} ageing=${data.ageing} />
          </div>
        </div>

        <div class="panel stack gap-16" style=${{ padding: 22 }}>
          <div class="stack gap-2">
            <h3 class="text-section-title">Vendors to act on</h3>
            <p class="text-muted text-small">
              Ranked by money at risk, then by how often they fail. Each explanation cites only
              computed figures.
            </p>
          </div>
          <div class="table-scroll" role="region" aria-label="Vendor risk detail" tabIndex="0">
            <table>
              <thead>
                <tr>
                  <th>Vendor</th><th>Invoices</th><th>Exceptions</th><th>Rate</th>
                  <th>At risk</th><th>Recurring failure</th><th>Avg age</th><th>Band</th>
                </tr>
              </thead>
              <tbody>
                ${data.vendor_risk.vendors.map((v) => html`
                  <tr key=${v.vendor_id} class=${v.risk_band === "high" ? "risk-high" : v.risk_band === "medium" ? "risk-medium" : ""}>
                    <td style=${{ fontWeight: 600 }}>${v.vendor_name}</td>
                    <td>${v.invoice_count}</td>
                    <td>${v.exception_count}</td>
                    <td>${Math.round(v.exception_rate * 100)}%</td>
                    <td>${formatInr(v.value_at_risk)}</td>
                    <td>${v.top_exception_type ? v.top_exception_type.replaceAll("_", " ") : "—"}</td>
                    <td>${v.average_open_age_days}d</td>
                    <td>
                      <${Badge} tone=${v.risk_band === "high" ? "exception" : v.risk_band === "medium" ? "warning" : "verified"}>
                        ${v.risk_band}
                      <//>
                    </td>
                  </tr>
                `)}
              </tbody>
            </table>
          </div>
        </div>

        <p class="text-muted text-small">
          <${Icon} name="shield" size=${13} /> Synthetic portfolio. Exception rates, value at risk,
          ageing, and trend are computed by deterministic code over stored case outcomes — the same
          arithmetic that decides an individual case. No figure on this page originates from a model.
        </p>
      `}
    </div>
  `;
}
