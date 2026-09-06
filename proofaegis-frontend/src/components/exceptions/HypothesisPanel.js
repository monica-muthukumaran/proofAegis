import { html, useState, useEffect } from "../../lib.js";
import * as api from "../../services/api.js";
import { Badge, Icon, Skeleton } from "../ui/primitives.js";

// Ranked candidate explanations for a finding the code already computed, each
// paired with the evidence that would settle it.
//
// The framing in the copy is deliberate and load-bearing: this panel tells a
// reviewer WHAT TO CHECK, never what happened. Every heading here is a
// question with a document attached, and the confidence figure describes a
// ranking rather than a conclusion. That boundary is the reason this agent is
// allowed to exist next to a deterministic matcher at all — it cannot state a
// number, because its output schema has no numeric field in it.
//
// When the model does not answer, the fallback returns the standard checks for
// the exception type in a fixed order, and this panel says the ranking is
// generic. That admission matters: unlike the other agents' fallbacks, this
// one is genuinely worse than the model, and pretending otherwise would be
// claiming a ranking that nothing produced.

export function HypothesisPanel({ exceptionId }) {
  const [data, setData] = useState(null);
  const [source, setSource] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.getHypotheses(exceptionId).then((r) => {
      if (cancelled) return;
      setData(r.data);
      setSource(r.data && r.data._ai_source);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [exceptionId]);

  const generate = async () => {
    setGenerating(true);
    setError(null);
    const r = await api.generateHypotheses(exceptionId);
    setGenerating(false);
    if (r.source === "error") { setError(r.error); return; }
    setData(r.data);
    setSource(r.data && r.data._ai_source);
  };

  if (loading) return html`<${Skeleton} height="180px" />`;

  const hypotheses = (data && data.hypotheses) || [];

  return html`
    <div class="stack gap-16" data-tour="hypotheses">
      <div class="stack gap-4">
        <div class="row gap-8" style=${{ justifyContent: "space-between", flexWrap: "wrap" }}>
          <h3 class="text-section-title">What to check next</h3>
          ${source
            ? html`<${Badge} tone=${source === "ai" ? "accent" : "neutral"}>
                ${source === "ai" ? "reasoned against this vendor's history" : "generic checklist — model unavailable"}
              <//>`
            : null}
        </div>
        <p class="text-muted text-small">
          The finding and every figure on this case were computed in code. This is the one place
          a model is asked for judgement rather than arithmetic: given that finding, what would
          explain it, and what document would settle each explanation. It suggests what to look
          at — it never concludes.
        </p>
      </div>

      ${error ? html`
        <p class="form-feedback form-feedback-error">${error}</p>
      ` : null}

      ${!hypotheses.length ? html`
        <div class="stack gap-12">
          <p class="text-secondary" style=${{ margin: 0 }}>
            No hypotheses generated for this case yet.
          </p>
          <button class="btn btn-primary" style=${{ width: "fit-content" }}
            onClick=${generate} disabled=${generating}>
            <${Icon} name="graph" size=${15} />
            ${generating ? "Thinking…" : "Suggest what to check"}
          </button>
        </div>
      ` : html`
        <div class="stack gap-12">
          ${hypotheses.map((h) => html`
            <div key=${h.rank} class="panel-elevated stack gap-8"
              style=${{ padding: 16, borderLeft: "3px solid var(--viz-rule)" }}>
              <div class="row gap-8" style=${{ alignItems: "flex-start" }}>
                <span class="badge badge-neutral" style=${{ flex: "none" }}>${h.rank}</span>
                <span style=${{ fontWeight: 700, lineHeight: 1.35 }}>${h.cause}</span>
                <span class="text-muted text-small num" style=${{ marginLeft: "auto", flex: "none" }}>
                  ${Math.round((h.likelihood || 0) * 100)}%
                </span>
              </div>

              <div class="stack gap-4" style=${{ paddingLeft: 2 }}>
                <span class="text-small">
                  <strong>Check:</strong> ${h.evidence_to_check}
                </span>
                ${h.where_to_look ? html`
                  <span class="text-muted text-small">Where: ${h.where_to_look}</span>` : null}
                <span class="text-muted text-small">
                  Confirms it if ${h.confirms_if.replace(/\.$/, "")}. Rules it out if
                  ${" "}${h.rules_out_if.charAt(0).toLowerCase() + h.rules_out_if.slice(1).replace(/\.$/, "")}.
                </span>
              </div>
            </div>
          `)}

          ${data.what_would_change_this ? html`
            <p class="text-muted text-small" style=${{ margin: 0 }}>
              ${data.what_would_change_this}
            </p>` : null}

          <div class="row gap-8" style=${{ flexWrap: "wrap" }}>
            <button class="btn btn-secondary btn-sm" onClick=${generate} disabled=${generating}>
              ${generating ? "Thinking…" : "Regenerate"}
            </button>
            <span class="text-muted text-small">
              Human review required before any payment action.
            </span>
          </div>
        </div>
      `}
    </div>
  `;
}
