// VendorRiskChart.js — where the next exception is likely to come from.
//
// Two axes because two different questions matter and they have different
// answers: how OFTEN a vendor fails (rate) and how MUCH that costs (value at
// risk). A vendor failing 64% of the time on small invoices and one failing
// 29% of the time on large ones are both problems, and neither shows up if
// you rank on a single number. Bubble size is invoice volume, so a high rate
// over three invoices reads as the weak evidence it is.
//
// Value uses a log scale: at real spread, one large exposure flattens every
// other vendor to the baseline on a linear axis.
import { html, useState } from "../../lib.js";

const WIDTH = 640;
const HEIGHT = 340;
const PAD = { top: 18, right: 20, bottom: 44, left: 68 };

const BAND_COLOR = { high: "var(--exception)", medium: "var(--warning)", low: "var(--verified)" };

function formatInr(n) {
  if (n == null) return "—";
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(1)}Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(0)}k`;
  return `₹${Math.round(n)}`;
}

export function VendorRiskChart({ vendors }) {
  const [active, setActive] = useState(null);

  const points = (vendors || []).filter((v) => v.invoice_count > 0);
  if (points.length === 0) {
    return html`<p class="text-muted text-small">No vendor activity in this window.</p>`;
  }

  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;

  const maxRate = Math.max(0.1, ...points.map((v) => v.exception_rate));
  const maxValue = Math.max(1, ...points.map((v) => v.value_at_risk));
  const maxVolume = Math.max(1, ...points.map((v) => v.invoice_count));

  // log1p keeps zero-risk vendors on the axis instead of at negative infinity.
  const logMax = Math.log1p(maxValue);
  const x = (rate) => PAD.left + (rate / maxRate) * plotW;
  const y = (value) => PAD.top + plotH - (Math.log1p(value) / logMax) * plotH;
  const r = (count) => 5 + (count / maxVolume) * 16;

  const rateTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * maxRate);
  const valueTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.expm1(f * logMax));

  return html`
    <div class="stack gap-12">
      <svg viewBox="0 0 ${WIDTH} ${HEIGHT}" class="chart-svg" role="img"
        aria-label="Vendor risk: exception rate against value at risk, sized by invoice volume">
        ${valueTicks.map((v, i) => html`
          <g key=${`gy${i}`}>
            <line x1=${PAD.left} y1=${y(v)} x2=${WIDTH - PAD.right} y2=${y(v)} class="chart-grid" />
            <text x=${PAD.left - 8} y=${y(v) + 4} textAnchor="end" class="chart-tick">${formatInr(v)}</text>
          </g>
        `)}
        ${rateTicks.map((t, i) => html`
          <text key=${`gx${i}`} x=${x(t)} y=${HEIGHT - PAD.bottom + 18} textAnchor="middle" class="chart-tick">
            ${Math.round(t * 100)}%
          </text>
        `)}

        <text x=${PAD.left + plotW / 2} y=${HEIGHT - 8} textAnchor="middle" class="chart-axis-label">
          Exception rate
        </text>
        <text x=${14} y=${PAD.top + plotH / 2} textAnchor="middle" class="chart-axis-label"
          transform=${`rotate(-90 14 ${PAD.top + plotH / 2})`}>
          Value at risk
        </text>

        ${points.map((v) => html`
          <circle
            key=${v.vendor_id}
            cx=${x(v.exception_rate)} cy=${y(v.value_at_risk)} r=${r(v.invoice_count)}
            class="bubble ${active && active.vendor_id === v.vendor_id ? "active" : ""}"
            style=${{ fill: BAND_COLOR[v.risk_band] || "var(--accent)" }}
            onMouseEnter=${() => setActive(v)}
            onMouseLeave=${() => setActive(null)}
            onClick=${() => setActive(v)}
            tabIndex="0"
            onFocus=${() => setActive(v)}
            onBlur=${() => setActive(null)}
          ><title>${v.vendor_name}</title></circle>
        `)}
      </svg>

      <div class="panel-elevated stack gap-4" style=${{ padding: 14, minHeight: 92 }}>
        ${active ? html`
          <div class="row gap-8" style=${{ flexWrap: "wrap", alignItems: "baseline" }}>
            <span style=${{ fontWeight: 700 }}>${active.vendor_name}</span>
            <span class="text-muted text-small">${active.business_unit || ""}</span>
            <span class="badge badge-${active.risk_band === "high" ? "exception" : active.risk_band === "medium" ? "warning" : "verified"}"
              style=${{ marginLeft: "auto" }}>
              <span class="badge-dot" style=${{ background: "currentColor" }}></span>${active.risk_band} risk
            </span>
          </div>
          <p class="text-small">${active.why_at_risk}</p>
          <span class="text-muted text-small">
            ${active.invoice_count} invoices · avg match ${active.average_match_score ?? "—"}%
            · avg open age ${active.average_open_age_days}d
          </span>
        ` : html`
          <span class="text-muted text-small">
            Hover a vendor to see why it is flagged. Bubble size is invoice volume; colour is risk band.
            Every figure is computed from the portfolio — no model produces these numbers.
          </span>
        `}
      </div>
    </div>
  `;
}
