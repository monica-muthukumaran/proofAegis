// TrendChart.js — is this getting better or worse?
//
// Stacked bars show volume split into clean and exception, so the two move
// against a visible total rather than floating free. The overlaid line is the
// exception RATE, which is the number that actually indicates control: 15
// exceptions out of 30 invoices and 15 out of 300 look identical as a bar and
// are completely different situations.
import { html, useState } from "../../lib.js";

const WIDTH = 640;
const HEIGHT = 300;
const PAD = { top: 20, right: 52, bottom: 42, left: 46 };

function monthLabel(key) {
  const [year, month] = key.split("-");
  const names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  return `${names[Number(month) - 1]} ${String(year).slice(2)}`;
}

function formatInr(n) {
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(0)}k`;
  return `₹${Math.round(n)}`;
}

export function TrendChart({ points }) {
  const [active, setActive] = useState(null);

  const data = points || [];
  if (data.length === 0) {
    return html`<p class="text-muted text-small">Not enough history to plot a trend yet.</p>`;
  }

  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const maxInvoices = Math.max(1, ...data.map((p) => p.invoices));
  const maxRate = Math.max(0.1, ...data.map((p) => p.exception_rate));

  const slot = plotW / data.length;
  const barW = Math.min(34, slot * 0.58);
  const cx = (i) => PAD.left + slot * i + slot / 2;
  const barY = (count) => PAD.top + plotH - (count / maxInvoices) * plotH;
  const rateY = (rate) => PAD.top + plotH - (rate / maxRate) * plotH;

  const linePath = data
    .map((p, i) => `${i === 0 ? "M" : "L"} ${cx(i)} ${rateY(p.exception_rate)}`)
    .join(" ");

  return html`
    <div class="stack gap-12">
      <div class="row gap-16" style=${{ flexWrap: "wrap" }}>
        <span class="legend-item"><span class="legend-swatch" style=${{ background: "var(--accent-soft)" }}></span>Clean</span>
        <span class="legend-item"><span class="legend-swatch" style=${{ background: "var(--exception)" }}></span>Exceptions</span>
        <span class="legend-item"><span class="legend-swatch" style=${{ background: "var(--accent-2)" }}></span>Exception rate</span>
      </div>

      <svg viewBox="0 0 ${WIDTH} ${HEIGHT}" class="chart-svg" role="img"
        aria-label="Monthly invoice volume split by clean and exception, with exception rate">
        ${[0, 0.5, 1].map((f, i) => html`
          <g key=${`g${i}`}>
            <line x1=${PAD.left} y1=${barY(maxInvoices * f)} x2=${WIDTH - PAD.right} y2=${barY(maxInvoices * f)} class="chart-grid" />
            <text x=${PAD.left - 8} y=${barY(maxInvoices * f) + 4} textAnchor="end" class="chart-tick">
              ${Math.round(maxInvoices * f)}
            </text>
            <text x=${WIDTH - PAD.right + 8} y=${rateY(maxRate * f) + 4} textAnchor="start" class="chart-tick">
              ${Math.round(maxRate * f * 100)}%
            </text>
          </g>
        `)}

        ${data.map((p, i) => {
          const exceptionH = (p.exceptions / maxInvoices) * plotH;
          const cleanH = (p.clean / maxInvoices) * plotH;
          const isActive = active === i;
          return html`
            <g key=${p.month} onMouseEnter=${() => setActive(i)} onMouseLeave=${() => setActive(null)}
              style=${{ cursor: "pointer" }}>
              <rect x=${cx(i) - slot / 2} y=${PAD.top} width=${slot} height=${plotH} fill="transparent" />
              <rect class="trend-bar" x=${cx(i) - barW / 2} y=${PAD.top + plotH - cleanH}
                width=${barW} height=${Math.max(0, cleanH)} rx="2"
                fill="var(--accent-soft)" opacity=${isActive ? 1 : 0.9} />
              <rect class="trend-bar" x=${cx(i) - barW / 2} y=${PAD.top + plotH - cleanH - exceptionH}
                width=${barW} height=${Math.max(0, exceptionH)} rx="2"
                fill="var(--exception)" opacity=${isActive ? 1 : 0.85} />
              <text x=${cx(i)} y=${HEIGHT - PAD.bottom + 18} textAnchor="middle" class="chart-tick">
                ${monthLabel(p.month)}
              </text>
            </g>
          `;
        })}

        <path d=${linePath} fill="none" stroke="var(--accent-2)" strokeWidth="2.2"
          strokeLinecap="round" strokeLinejoin="round" class="trend-line" />
        ${data.map((p, i) => html`
          <circle key=${`pt${p.month}`} cx=${cx(i)} cy=${rateY(p.exception_rate)} r=${active === i ? 5 : 3.2}
            fill="var(--surface)" stroke="var(--accent-2)" strokeWidth="2" />
        `)}
      </svg>

      <div class="panel-elevated" style=${{ padding: 12, minHeight: 52 }}>
        ${active !== null && data[active] ? html`
          <span class="text-small">
            <strong>${monthLabel(data[active].month)}</strong> — ${data[active].invoices} invoices,
            ${data[active].exceptions} exceptions (${Math.round(data[active].exception_rate * 100)}%),
            ${formatInr(data[active].value_at_risk)} at risk
          </span>
        ` : html`
          <span class="text-muted text-small">Hover a month for its figures. Bars are invoice volume; the line is exception rate.</span>
        `}
      </div>
    </div>
  `;
}
