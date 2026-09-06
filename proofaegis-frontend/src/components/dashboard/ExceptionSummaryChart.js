import { html } from "../../lib.js";

const LABELS = {
  price_variance: "Price variance",
  quantity_variance: "Quantity variance",
  missing_goods_receipt: "Missing goods receipt",
  po_over_billed: "Order over-billed",
  payment_details_changed: "Payment details changed",
  missing_purchase_order: "Missing purchase order",
  vendor_mismatch: "Vendor mismatch",
  tax_total_mismatch: "Tax / total mismatch",
  duplicate_invoice: "Duplicate invoice",
};

const TYPE_COLOR = {
  price_variance: "var(--exception)",
  quantity_variance: "var(--warning)",
  missing_goods_receipt: "var(--accent-2)",
  po_over_billed: "var(--warning)",
  payment_details_changed: "var(--critical, var(--exception))",
  missing_purchase_order: "var(--critical)",
  vendor_mismatch: "var(--critical)",
  tax_total_mismatch: "var(--warning)",
  duplicate_invoice: "var(--exception)",
};

function formatInr(n) {
  if (n == null) return null;
  if (n >= 100000) return `₹${(n / 100000).toFixed(2)}L`;
  return `₹${Number(n).toLocaleString("en-IN")}`;
}

/**
 * breakdown: { type: count }
 * valueBreakdown (optional): { type: financial_impact }
 *
 * Bars are scaled by VALUE when it is available and by count otherwise. "3
 * exceptions" says nothing about which one matters; "₹1.8L vs ₹25k" does, and
 * a bar chart that encodes magnitude is the only kind worth drawing.
 */
export function ExceptionSummaryChart({ breakdown, valueBreakdown }) {
  const entries = Object.entries(breakdown || {});
  if (entries.length === 0) return html`<p class="text-muted text-small">No exceptions to summarize yet.</p>`;

  const useValue = valueBreakdown && entries.some(([type]) => valueBreakdown[type] > 0);
  const weight = ([type, count]) => (useValue ? (valueBreakdown[type] || 0) : count);
  const max = Math.max(...entries.map(weight), 1);
  const ordered = [...entries].sort((a, b) => weight(b) - weight(a));

  return html`
    <div class="stack gap-12">
      ${ordered.map(([type, count], index) => html`
        <div class="stack gap-4" key=${type}>
          <div class="row" style=${{ justifyContent: "space-between", gap: 8 }}>
            <span class="text-small">${LABELS[type] || type}</span>
            <span class="text-small text-muted">
              ${useValue ? `${formatInr(valueBreakdown[type] || 0)} · ${count}` : count}
            </span>
          </div>
          <div class="bar-track">
            <div class="bar-fill"
              style=${{
                width: `${Math.max(2, (weight([type, count]) / max) * 100)}%`,
                background: TYPE_COLOR[type] || "var(--accent)",
                animationDelay: `${index * 70}ms`,
              }}></div>
          </div>
        </div>
      `)}
      ${useValue ? html`
        <span class="text-muted text-small">Bars scaled by financial impact.</span>
      ` : null}
    </div>
  `;
}
