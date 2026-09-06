import { html } from "../../lib.js";
import { Badge, Icon } from "../ui/primitives.js";

// How often the deterministic layer had to correct the model.
//
// This is the only screen in the product that shows its own AI being wrong,
// which is precisely why it is worth building. Everyone claims their
// architecture keeps the model away from the arithmetic; this counts the
// times the claim was tested.
//
// THE THING THIS COMPONENT MUST NOT DO is present a number that flatters.
// Three counts are kept visibly apart, because merging them would turn a
// measurement into a marketing figure:
//
//   model answered      runs where a live model actually produced a figure.
//                       The only denominator a disagreement rate may use.
//   fallback answered   runs where the model was unreachable and the
//                       deterministic template stood in. The model said
//                       nothing, so there is nothing for it to have agreed
//                       with, and counting these as agreement would
//                       manufacture a perfect record out of an outage.
//   fault injection     values corrupted on purpose to prove the check fires.
//                       Useful, and not evidence about a model.
//
// The backend enforces the same separation (services/trust_ledger.py); this
// renders it rather than re-deriving it.

function inr(value) {
  if (value == null) return "—";
  return `₹${Math.round(value).toLocaleString("en-IN")}`;
}

export function DisagreementLedger({ trust }) {
  if (!trust) return null;

  const answered = trust.model_answered || 0;
  // Disagreements a live model caused, against overrides from any cause. They
  // are different numbers and the panel shows both: quoting only the first
  // while an injected fault sits in the table below would be a headline
  // contradicting its own evidence, and quoting only the second would claim
  // a model got something wrong when nothing established that.
  const disagreements = trust.disagreements || 0;
  const overrides = trust.overrides_applied != null ? trust.overrides_applied : disagreements;
  const injection = trust.fault_injection || { injected: 0, caught: 0 };
  const rate = trust.disagreement_rate;

  return html`
    <div class="panel stack gap-16" style=${{ padding: 22 }} data-tour="disagreement-ledger">
      <div class="stack gap-2">
        <div class="row gap-8" style=${{ justifyContent: "space-between", flexWrap: "wrap" }}>
          <h3 class="text-section-title">Disagreement ledger</h3>
          <${Badge} tone="verified">deterministic value always wins<//>
        </div>
        <p class="text-muted text-small">
          Every financial figure the reasoning agent states is compared against the one
          matching_service.py computed, before anything reaches this screen. This is the count
          of those comparisons — including the ones that agreed, because a fire rate with no
          denominator is not a measurement.
        </p>
      </div>

      <div class="trust-row">
        <div class="trust-cell">
          <span class="trust-cell-label">Model answered</span>
          <span class="trust-cell-value">${answered}</span>
        </div>
        <div class="trust-cell">
          <span class="trust-cell-label">Model disagreed</span>
          <span class="trust-cell-value">
            ${disagreements}
            ${rate != null
              ? html`<span class="text-muted text-small" style=${{ fontWeight: 400 }}>
                  ${" "}(${(rate * 100).toFixed(1)}%)</span>`
              : null}
          </span>
        </div>
        <div class="trust-cell trust-cell-authoritative">
          <span class="trust-cell-label">Overrides applied</span>
          <span class="trust-cell-value">${overrides}</span>
        </div>
        <div class="trust-cell">
          <span class="trust-cell-label">Value corrected</span>
          <span class="trust-cell-value">${inr(trust.total_value_corrected)}</span>
        </div>
      </div>

      <div class=${`trust-verdict ${overrides ? "trust-verdict-overridden" : "trust-verdict-agreed"}`}>
        <${Icon} name="shield" size=${15} />
        ${overrides
          ? `Every one of the ${overrides} resolved the same way: the computed value was used.`
          : "No override has been required in this run. The check ran on every case regardless."}
      </div>

      <div class="stack gap-8">
        <div class="row gap-8" style=${{ flexWrap: "wrap" }}>
          <span class="text-small">
            <strong>Guardrail fault injection:</strong> ${injection.caught} of ${injection.injected} caught
          </span>
          ${injection.injected
            ? html`<${Badge} tone=${injection.caught === injection.injected ? "verified" : "critical"}>
                ${injection.caught === injection.injected ? "all caught" : "MISS"}
              <//>`
            : null}
        </div>
        <p class="text-muted text-small" style=${{ margin: 0 }}>
          Deliberately corrupted figures, run through the same check. They prove the mechanism
          fires and they are counted separately — they are not evidence about how often a model
          is wrong, and adding them to the figures above would be exactly that claim.
        </p>
      </div>

      ${trust.fallback_answered ? html`
        <p class="text-muted text-small" style=${{ margin: 0 }}>
          ${trust.fallback_answered} further comparison${trust.fallback_answered === 1 ? "" : "s"} ran
          against the deterministic fallback because the model was unreachable. Those are excluded
          from the rate above: the model stated nothing, so there is nothing it can be said to
          have got right.
        </p>` : null}

      ${(trust.recent || []).length ? html`
        <div class="table-scroll" role="region" aria-label="Recent overrides" tabIndex="0">
          <table>
            <thead><tr>
              <th>Case</th><th>AI stated</th><th>Computed</th><th>Difference</th><th>Kind</th>
            </tr></thead>
            <tbody>
              ${trust.recent.map((row) => html`
                <tr key=${`${row.exception_id}-${row.checked_at}`}>
                  <td><span class="id" style=${{ fontWeight: 600 }}>${row.exception_id}</span></td>
                  <td class="num" style=${{ textDecoration: "line-through", color: "var(--muted)" }}>
                    ${inr(row.ai_value)}
                  </td>
                  <td class="num" style=${{ fontWeight: 700 }}>${inr(row.computed_value)}</td>
                  <td class="num">
                    ${inr(row.difference)}
                    ${row.difference_percent != null ? ` (${row.difference_percent.toFixed(1)}%)` : ""}
                  </td>
                  <td>
                    <${Badge} tone=${row.kind === "fault_injection" ? "warning" : "exception"}>
                      ${row.kind === "fault_injection" ? "injected fault" : "live"}
                    <//>
                  </td>
                </tr>
              `)}
            </tbody>
          </table>
        </div>` : null}

      <p class="text-muted text-small" style=${{ margin: 0 }}>
        ${trust.note} Counts describe this server process rather than all time.
      </p>
    </div>
  `;
}
