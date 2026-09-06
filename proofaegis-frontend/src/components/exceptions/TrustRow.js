import { html } from "../../lib.js";
import { Icon } from "../ui/primitives.js";

// What the reasoning model said the money was, next to what the code computed,
// with the deterministic value marked as the one that was used.
//
// The backend has always overridden the model's figure. It did so silently,
// which meant the most defensible property of this architecture was visible
// only to somebody tailing stderr. A guardrail nobody can watch is worth very
// little as an argument, however well it works.
//
// The provenance line is not decoration. There are three genuinely different
// things this row can be describing, and conflating them would be the exact
// dishonesty the row exists to rule out:
//
//   ai + agreed        a live model produced a figure and it was right.
//   ai + overridden    a live model produced a figure and it was wrong. This
//                      is the real event, and it is rare.
//   fault_injection    a value corrupted on purpose so the override can be
//                      demonstrated. Labelled as such, never passed off as
//                      model output.
//
// A fallback run (`ai_source: "mock"`) is not evidence about a model at all —
// the model did not answer — and the copy says so rather than counting it as
// agreement.

function inr(value) {
  if (value == null) return "—";
  return `₹${Number(value).toLocaleString("en-IN", { maximumFractionDigits: 2 })}`;
}

export function TrustRow({ check }) {
  if (!check) return null;

  const injected = check.kind === "fault_injection";
  const modelAnswered = check.ai_source === "ai";
  const overridden = Boolean(check.overridden);

  const provenance = injected
    ? "Injected fault — a figure corrupted on purpose so the check can be watched running. Not model output."
    : modelAnswered
      ? "Stated by the reasoning model on this case."
      : "The model did not answer; the deterministic fallback stood in. Nothing here is evidence about the model.";

  return html`
    <div class="stack gap-10" data-tour="trust-row">
      <div class="row gap-8" style=${{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <span style=${{ fontWeight: 700 }}>Financial impact — checked</span>
        <span class="text-muted text-small">Every figure the AI states is compared against the computed one.</span>
      </div>

      <div class="trust-row">
        <div class=${`trust-cell ${overridden ? "trust-cell-superseded" : ""}`}>
          <span class="trust-cell-label">
            ${injected ? "AI-stated (injected)" : "AI-stated"}
          </span>
          <span class="trust-cell-value">${inr(check.ai_value)}</span>
        </div>

        <div class="trust-cell trust-cell-authoritative">
          <span class="trust-cell-label">Computed in code</span>
          <span class="trust-cell-value">${inr(check.computed_value)}</span>
        </div>

        <div class="trust-cell">
          <span class="trust-cell-label">Difference</span>
          <span class="trust-cell-value">
            ${overridden ? inr(check.difference) : "none"}
            ${overridden && check.difference_percent != null
              ? html`<span class="text-muted text-small" style=${{ fontWeight: 400 }}>
                  ${" "}(${check.difference_percent.toFixed(1)}%)
                </span>`
              : null}
          </span>
        </div>
      </div>

      <div class=${`trust-verdict ${overridden ? "trust-verdict-overridden" : "trust-verdict-agreed"}`}>
        <${Icon} name="shield" size=${15} />
        ${overridden
          ? "Deterministic value used. The AI's figure was discarded."
          : "The two agreed. The deterministic value was used, as it always is."}
      </div>

      <p class="text-muted text-small" style=${{ margin: 0 }}>
        ${provenance}
        ${" "}
        ${check.note ? html`Basis: ${check.note}` : null}
      </p>
    </div>
  `;
}
