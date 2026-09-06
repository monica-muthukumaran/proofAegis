import { html } from "../../lib.js";
import { Icon } from "../ui/primitives.js";

// The headline the product is actually selling.
//
// Most AP automation decides what to approve. Given an invoice, an order and a
// receipt, it tells you whether the three agree — and so does ProofAegis, and
// that part is table stakes. What it cannot do is look sideways: a duplicate
// is only a duplicate relative to a case somewhere else, cumulative
// over-billing needs every invoice raised against one order, a changed bank
// account needs the vendor's last invoice, drift needs their last six.
//
// Every one of those fires on an invoice whose own three-way match is clean,
// which is the uncomfortable half and the reason this panel leads the screen:
// what passed is scarier than what failed.
//
// Every figure here is computed by services/analytics_service.py by
// partitioning the portfolio on exception type. Nothing is narrated by a
// model, and the value is stated as exposure surfaced for review rather than
// as loss prevented — a duplicate flagged and then confirmed legitimate had no
// money at stake at all.

const TYPE_LABEL = {
  duplicate_invoice: "Duplicate invoice",
  po_over_billed: "Cumulative over-billing",
  payment_details_changed: "Payment details changed",
  recurring_suspected: "Recurring billing pattern",
  vendor_price_drift: "Vendor price drift",
};

const TYPE_WHY = {
  duplicate_invoice: "needs the vendor's earlier invoices",
  po_over_billed: "needs every invoice raised against the order",
  payment_details_changed: "needs the account on their last invoice",
  recurring_suspected: "needs the cadence across months",
  vendor_price_drift: "needs the rate on their last six invoices",
};

function inr(value) {
  if (value == null) return "—";
  if (value >= 10000000) return `₹${(value / 10000000).toFixed(2)}Cr`;
  if (value >= 100000) return `₹${(value / 100000).toFixed(2)}L`;
  return `₹${Math.round(value).toLocaleString("en-IN")}`;
}

export function CrossCasePanel({ data }) {
  if (!data) return null;

  const single = data.single_invoice;
  const cross = data.cross_case;
  const cleared = data.would_have_cleared;
  const total = single.count + cross.count;
  // Guard the zero case: an empty window must render as an empty state, not
  // as a division by zero rendering NaN% in a headline.
  const crossShare = total ? (cross.count / total) * 100 : 0;

  return html`
    <div class="crosscase-panel" data-tour="cross-case">
      <div class="crosscase-head stack gap-8">
        <span class="text-muted text-small" style=${{ fontWeight: 700, letterSpacing: ".06em", textTransform: "uppercase" }}>
          What a per-invoice check would have missed
        </span>
        <div class="crosscase-figure">${inr(cross.value)}</div>
        <p class="text-secondary" style=${{ margin: 0, maxWidth: "62ch" }}>
          ${data.headline}
        </p>
      </div>

      <div class="crosscase-split">
        <div class="crosscase-half crosscase-half-single stack gap-6">
          <span class="crosscase-half-label">Found inside one case</span>
          <span class="text-kpi num">${single.count}</span>
          <span class="text-muted text-small">
            ${inr(single.value)} · price, quantity, tax and missing-document checks.
            Any competent three-way match finds these.
          </span>
        </div>
        <div class="crosscase-half crosscase-half-cross stack gap-6">
          <span class="crosscase-half-label">Found only across cases</span>
          <span class="text-kpi num">${cross.count}</span>
          <span class="text-muted text-small">
            ${inr(cross.value)} · ${crossShare.toFixed(0)}% of all exceptions. Invisible to
            a system that reads one invoice at a time.
          </span>
        </div>
      </div>

      <div class="stack gap-14" style=${{ padding: 22 }}>
        <div class="crosscase-bar" role="img"
          aria-label=${`${single.count} exceptions found inside one case, ${cross.count} found only across cases`}>
          <div class="crosscase-bar-single" style=${{ width: `${100 - crossShare}%` }}></div>
          <div class="crosscase-bar-cross" style=${{ width: `${crossShare}%` }}></div>
        </div>

        ${cleared.count ? html`
          <div class="row gap-8" style=${{ alignItems: "flex-start" }}>
            <${Icon} name="shield" size=${15} />
            <span class="text-secondary" style=${{ fontSize: 14 }}>
              <strong>${cleared.count} of them scored a full three-way match</strong> on their own
              documents — ${inr(cleared.value)} that a per-invoice system would have passed for
              payment. This is the point: what passes is scarier than what fails.
            </span>
          </div>` : null}

        ${Object.keys(cross.by_type || {}).length ? html`
          <div class="stack gap-0">
            ${Object.entries(cross.by_type).map(([type, stats]) => html`
              <div class="crosscase-type-row" key=${type}>
                <span class="type-dot type-dot-cross"></span>
                <span style=${{ fontWeight: 600, fontSize: 14 }}>${TYPE_LABEL[type] || type.replaceAll("_", " ")}</span>
                <span class="text-muted text-small">${TYPE_WHY[type] || ""}</span>
                <span class="text-muted text-small num" style=${{ marginLeft: "auto" }}>
                  ${stats.count} · ${inr(stats.value)}
                </span>
              </div>
            `)}
          </div>` : null}

        <p class="text-muted text-small" style=${{ margin: 0 }}>
          ${data.basis}
        </p>
      </div>
    </div>
  `;
}
