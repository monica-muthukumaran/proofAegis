// AgeingChart.js — how long open exceptions have been sitting.
//
// Bars carry two encodings because the two disagree and the disagreement is
// the point: bar LENGTH is case count, the figure beside it is money. A
// bucket with two cases and most of the exposure is the one to work first,
// and a count-only chart hides exactly that.
//
// Buckets past the SLA are tinted, so "we are outside our own policy on N
// cases" is readable without arithmetic.
import { html } from "../../lib.js";

function formatInr(n) {
  if (n >= 10000000) return `₹${(n / 10000000).toFixed(1)}Cr`;
  if (n >= 100000) return `₹${(n / 100000).toFixed(1)}L`;
  if (n >= 1000) return `₹${(n / 1000).toFixed(0)}k`;
  return `₹${Math.round(n)}`;
}

// Bucket labels start with the lower bound in days, which is all we need to
// know whether the whole bucket sits past the SLA.
function bucketStartDays(label) {
  const match = /^(\d+)/.exec(label);
  return match ? Number(match[1]) : 0;
}

export function AgeingChart({ ageing }) {
  if (!ageing || !ageing.buckets) return null;

  const { buckets, sla_days: slaDays, open_exceptions: open, breaching_sla: breaching, oldest_open_days: oldest } = ageing;
  const maxCount = Math.max(1, ...buckets.map((b) => b.count));

  if (open === 0) {
    return html`
      <p class="text-muted text-small">
        No open exceptions in this window — nothing is currently ageing.
      </p>
    `;
  }

  return html`
    <div class="stack gap-16">
      <div class="row gap-16" style=${{ flexWrap: "wrap" }}>
        <div class="stack gap-2">
          <span class="text-muted text-small">Open exceptions</span>
          <span style=${{ fontWeight: 700, fontSize: 20 }}>${open}</span>
        </div>
        <div class="stack gap-2">
          <span class="text-muted text-small">Past the ${slaDays}-day SLA</span>
          <span style=${{ fontWeight: 700, fontSize: 20, color: breaching > 0 ? "var(--exception)" : "var(--verified)" }}>
            ${breaching}
          </span>
        </div>
        <div class="stack gap-2">
          <span class="text-muted text-small">Oldest open case</span>
          <span style=${{ fontWeight: 700, fontSize: 20 }}>${Math.round(oldest)}d</span>
        </div>
      </div>

      <div class="stack gap-10">
        ${buckets.map((b) => {
          const breached = bucketStartDays(b.label) > slaDays;
          return html`
            <div class="stack gap-4" key=${b.label}>
              <div class="row" style=${{ justifyContent: "space-between", gap: 8 }}>
                <span class="text-small">
                  ${b.label}
                  ${breached ? html`<span class="text-small" style=${{ color: "var(--exception)" }}> · past SLA</span>` : ""}
                </span>
                <span class="text-small text-muted">
                  ${b.count} ${b.count === 1 ? "case" : "cases"} · ${formatInr(b.value_at_risk)}
                </span>
              </div>
              <div class="bar-track">
                <div class="bar-fill" style=${{
                  width: `${Math.max(b.count ? 3 : 0, (b.count / maxCount) * 100)}%`,
                  background: breached ? "var(--exception)" : "var(--accent)",
                }}></div>
              </div>
            </div>
          `;
        })}
      </div>

      <p class="text-muted text-small">
        Bar length is case count; the figure beside it is money at risk. A short bar carrying most of
        the exposure is the one to work first.
      </p>
    </div>
  `;
}
