import { html } from "../../lib.js";
import { Badge } from "../ui/primitives.js";
import { MATCH_SCORE_HINT } from "../../lib/labels.js";
import { ToleranceBand } from "./ToleranceBand.js";
import { TrustRow } from "./TrustRow.js";

const CLASSIFICATION_TONE = {
  matched: "verified", within_tolerance: "verified", outside_tolerance: "exception",
  missing: "neutral", unable_to_verify: "warning", requires_human_review: "warning",
};

const FIELD_LABEL = {
  vendor: "Vendor", po_number: "PO number", quantity: "Quantity", unit_price: "Unit price",
  tax: "Tax", total: "Total", subtotal: "Subtotal (pre-tax)", line_items: "Line items",
  tax_arithmetic: "Invoice adds up", quoted_price: "Order vs quotation",
  po_billed_total: "Billed against this order",
};

function money(value) {
  if (value == null) return "—";
  return typeof value === "number" ? value.toLocaleString("en-IN") : value;
}

export function MatchWorkspace({ matchResult, trustCheck, linkWarnings = [] }) {
  const lines = matchResult.line_comparisons || [];
  const allDuplicates = matchResult.duplicate_of || [];
  // A recognised billing schedule is reported through the same channel as a
  // duplicate and means the opposite thing, so the two are separated before
  // anything is rendered. Showing a monthly retainer under "this invoice may
  // already have been recorded" is the false positive the recurring check
  // exists to prevent, and it would be undone here by presenting them alike.
  const duplicates = allDuplicates.filter((d) => d.confidence !== "recurring");
  const recurring = allDuplicates.filter((d) => d.confidence === "recurring");
  const paymentChanges = matchResult.payment_detail_changes || [];
  const drift = matchResult.price_drift;
  const billing = matchResult.po_billing;

  return html`
    <div class="stack gap-20">
      ${matchResult.cross_case ? html`
        <div class="panel-elevated stack gap-4"
          style=${{ padding: 16, borderLeft: "3px solid var(--viz-finding)" }}>
          <span class="row gap-8" style=${{ fontWeight: 700 }}>
            <span class="type-dot type-dot-cross"></span>
            Found by looking across cases, not at this one
          </span>
          <p class="text-muted text-small" style=${{ margin: 0 }}>
            Every comparison below is about this invoice against its own order and receipt.
            This finding is not — it came from what the rest of the workspace already contains,
            and no per-invoice check could reach it.
          </p>
        </div>
      ` : null}

      ${duplicates.length ? html`
        <div class="panel-elevated stack gap-8"
          style=${{ padding: 16, borderLeft: "3px solid var(--critical, var(--exception))" }}>
          <span style=${{ fontWeight: 700 }}>
            This invoice may already have been recorded
          </span>
          ${duplicates.map((d, index) => html`
            <div class="stack gap-4" key=${index}>
              <p class="text-secondary" style=${{ margin: 0 }}>${d.reason}</p>
              <span class="text-muted text-small">
                ${d.confidence === "exact" ? "Same vendor and invoice number" : "Same vendor and amount, close in time"}
                ${d.exception_id ? ` · seen on ${d.exception_id}` : ""}
              </span>
            </div>
          `)}
          <p class="text-muted text-small" style=${{ margin: 0 }}>
            Settle this before reading anything below: a duplicate should not be paid at
            all, which makes every variance on it irrelevant.
          </p>
        </div>
      ` : null}

      ${recurring.length ? html`
        <div class="panel-elevated stack gap-6"
          style=${{ padding: 16, borderLeft: "3px solid var(--viz-rule)" }}>
          <span class="row gap-8" style=${{ fontWeight: 700 }}>
            <span class="type-dot type-dot-note"></span>
            Recognised billing pattern — not a duplicate
          </span>
          ${recurring.map((r, index) => html`
            <p class="text-secondary" style=${{ margin: 0 }} key=${index}>${r.reason}</p>
          `)}
          <p class="text-muted text-small" style=${{ margin: 0 }}>
            "Same vendor, same amount, close in time" is also what rent, a retainer, an AMC and
            every subscription look like. This one arrives on a regular cadence, so it is reported
            here at low severity rather than at the top of the case as a duplicate — where it
            would have outranked every real finding on it, every month, forever.
          </p>
        </div>
      ` : null}

      ${paymentChanges.length ? html`
        <div class="panel-elevated stack gap-8"
          style=${{ padding: 16, borderLeft: "3px solid var(--critical, var(--exception))" }}>
          <span class="row gap-8" style=${{ fontWeight: 700 }}>
            <span class="type-dot type-dot-cross"></span>
            Payment details differ from last time
          </span>
          ${paymentChanges.map((c, index) => html`
            <p class="text-secondary" style=${{ margin: 0 }} key=${index}>${c.detail}</p>
          `)}
        </div>
      ` : null}

      ${drift ? html`
        <div class="panel-elevated stack gap-8"
          style=${{ padding: 16, borderLeft: "3px solid var(--viz-finding)" }}>
          <span class="row gap-8" style=${{ fontWeight: 700 }}>
            <span class="type-dot type-dot-cross"></span>
            This vendor's rate has been climbing
          </span>
          <p class="text-secondary" style=${{ margin: 0 }}>${drift.detail}</p>
          <div class="row gap-16" style=${{ flexWrap: "wrap" }}>
            ${drift.history.map((point, index) => html`
              <span key=${index} class="text-muted text-small num">
                ${point.invoice_date || "—"} · ${money(point.unit_price)}
              </span>
            `)}
          </div>
        </div>
      ` : null}

      ${billing && billing.order_value ? html`
        <div class="panel-elevated stack gap-4" style=${{ padding: 16 }}>
          <span style=${{ fontWeight: 700 }}>Billed against ${billing.po_number}</span>
          <div class="row gap-16" style=${{ flexWrap: "wrap" }}>
            <span class="text-muted text-small">
              Order ${money(billing.order_value)}
            </span>
            <span class="text-muted text-small">
              Billed ${money(billing.total_billed)} across ${billing.invoice_count} invoice${billing.invoice_count === 1 ? "" : "s"}
            </span>
            <span class=${billing.is_over_billed ? "" : "text-muted"} style=${{ fontSize: 13 }}>
              ${billing.is_over_billed
                ? `Over by ${money(billing.over_billed_by)}`
                : `Remaining ${money(billing.remaining)}`}
            </span>
          </div>
        </div>
      ` : null}

      ${linkWarnings.length ? html`
        <div class="panel-elevated stack gap-4"
          style=${{ padding: 16, borderLeft: "3px solid var(--warning)" }}>
          <span style=${{ fontWeight: 700 }}>Check these documents belong together</span>
          ${linkWarnings.map((w) => html`
            <p class="text-muted text-small" key=${w.role}>${w.detail}</p>
          `)}
          <p class="text-muted text-small">
            Every number below was computed from the documents named above. If they describe
            different orders, the comparison is not meaningful.
          </p>
        </div>
      ` : null}

      <div class="row gap-16" style=${{ flexWrap: "wrap" }}>
        <div class="panel-elevated stack gap-4" style=${{ padding: 16, flex: "1 1 160px" }}>
          <span class="text-muted text-small">Match score</span>
          <span class="text-kpi" title=${MATCH_SCORE_HINT}>${matchResult.match_score}%</span>
        </div>
        <div class="panel-elevated stack gap-4" style=${{ padding: 16, flex: "1 1 160px" }}>
          <span class="text-muted text-small">Exception type</span>
          <span style=${{ fontWeight: 700, fontSize: 16 }}>
            ${matchResult.awaiting_document
              ? `missing ${matchResult.awaiting_document}`
              : matchResult.exception_type.replaceAll("_", " ")}
          </span>
          ${matchResult.procurement_kind === "services" ? html`
            <span class="text-muted text-small">
              Services order — there are no goods to receive
            </span>` : null}
        </div>
        <div class="panel-elevated stack gap-4" style=${{ padding: 16, flex: "1 1 160px" }}>
          <span class="text-muted text-small">Risk level</span>
          <${Badge} tone=${matchResult.risk_level === "high" ? "critical" : matchResult.risk_level === "medium" ? "warning" : "verified"}>
            ${matchResult.risk_level}
          <//>
        </div>
      </div>

      ${matchResult.outstanding ? html`
        <div class="panel-elevated stack gap-4" style=${{ padding: 16 }}>
          <span style=${{ fontWeight: 700 }}>What is outstanding</span>
          <p class="text-secondary" style=${{ margin: 0 }}>${matchResult.outstanding}</p>
          <p class="text-muted text-small" style=${{ margin: 0 }}>
            A high match score and an open finding are not a contradiction: the score
            measures whether the documents on file agree, and the finding is about a
            document that is not on file.
          </p>
        </div>
      ` : null}

      <${ToleranceBand} matchResult=${matchResult} />

      ${trustCheck ? html`
        <div class="panel-elevated" style=${{ padding: 16 }}>
          <${TrustRow} check=${trustCheck} />
        </div>` : null}

      <div style=${{ overflowX: "auto" }}>
        <table>
          <thead><tr><th>Field</th><th>Expected (PO / receipt)</th><th>Actual (invoice)</th><th>Variance</th><th>Tolerance</th><th>Result</th></tr></thead>
          <tbody>
            ${matchResult.comparisons.map((c) => html`
              <tr key=${c.field} class=${c.classification === "outside_tolerance" ? "row-breach" : ""}>
                <td style=${{ fontWeight: 600 }}>${FIELD_LABEL[c.field] || c.field}</td>
                <td>${c.evaluable ? (c.expected_value ?? "—") : "Not on file"}</td>
                <td>${c.evaluable ? (c.actual_value ?? "—") : "—"}</td>
                <td>${c.percentage_variance != null ? `${c.percentage_variance}%` : "—"}</td>
                <td>${c.tolerance_percent != null ? `${c.tolerance_percent}%` : "—"}</td>
                <td><${Badge} tone=${CLASSIFICATION_TONE[c.classification] || "neutral"}>${c.classification.replaceAll("_", " ")}<//></td>
              </tr>
            `)}
          </tbody>
        </table>
      </div>

      ${lines.length ? html`
        <div class="stack gap-8">
          <span style=${{ fontWeight: 700 }}>Line by line</span>
          <p class="text-muted text-small">
            A single overcharged line can sit inside an order whose total still looks
            acceptable, so each ordered line is compared with the line that bills it.
          </p>
          <div style=${{ overflowX: "auto" }}>
            <table>
              <thead><tr>
                <th>Item</th><th>Ordered qty</th><th>Billed qty</th>
                <th>Ordered rate</th><th>Billed rate</th><th>Variance</th><th>Result</th>
              </tr></thead>
              <tbody>
                ${lines.map((line, index) => html`
                  <tr key=${index} class=${line.classification === "outside_tolerance" ? "row-breach" : ""}>
                    <td>
                      ${line.description || "—"}
                      ${line.only_on === "invoice" ? html`
                        <${Badge} tone="exception">billed, never ordered<//>` : null}
                      ${line.only_on === "purchase_order" ? html`
                        <${Badge} tone="neutral">ordered, not billed<//>` : null}
                    </td>
                    <td>${line.po_quantity ?? "—"}</td>
                    <td>${line.invoice_quantity ?? "—"}</td>
                    <td>${money(line.po_unit_price)}</td>
                    <td>${money(line.invoice_unit_price)}</td>
                    <td>${line.percentage_variance != null ? `${line.percentage_variance}%` : "—"}</td>
                    <td>
                      <${Badge} tone=${CLASSIFICATION_TONE[line.classification] || "neutral"}>
                        ${line.classification.replaceAll("_", " ")}
                      <//>
                    </td>
                  </tr>
                `)}
              </tbody>
            </table>
          </div>
        </div>
      ` : null}

      ${matchResult.tolerance_source ? html`
        <p class="text-muted text-small" style=${{ margin: 0 }}>
          Tolerances applied: ${matchResult.tolerance_source}.
        </p>
      ` : null}

      <p class="text-muted text-small">
        Arithmetic and tolerance calculations here are fully deterministic — no AI is involved in computing
        variances, match score, or financial impact.
      </p>
    </div>
  `;
}
