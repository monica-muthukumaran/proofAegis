import { html, useState, useEffect } from "../../lib.js";
import * as api from "../../services/api.js";
import { Badge, Skeleton, Icon, ErrorState } from "../ui/primitives.js";
import { InvestigationTrace } from "./InvestigationTrace.js";

const SEVERITY_TONE = { low: "neutral", medium: "warning", high: "exception", critical: "critical" };

export function ExceptionSummary({ exception, matchResult, documents, graph }) {
  const [reasoning, setReasoning] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    const r = await api.getReasoning(exception.exception_id);
    // notGenerated is the honest "nothing here yet" answer from the backend
    // (HTTP 404), which is what makes the Generate button appear. It used to
    // be swallowed and replaced with mock content.
    if (r.source === "error") setError(r.error);
    setReasoning(r.data);
    setLoading(false);
  };
  useEffect(() => { load(); }, [exception.exception_id]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    const r = await api.generateReasoning(exception.exception_id);
    if (r.source === "error") setError(r.error);
    else setReasoning(r.data);
    setGenerating(false);
  };

  return html`
    <div class="stack gap-20">
      <div class="row gap-24" style=${{ flexWrap: "wrap" }}>
        <div><div class="text-muted text-small">Invoice</div><div style=${{ fontWeight: 700 }}>${exception.invoice_id}</div></div>
        <div><div class="text-muted text-small">Vendor</div><div style=${{ fontWeight: 700 }}>${exception.vendor_name}</div></div>
        <div><div class="text-muted text-small">Purchase order</div><div style=${{ fontWeight: 700 }}>${exception.purchase_order_id}</div></div>
        <div><div class="text-muted text-small">Business unit</div><div style=${{ fontWeight: 700 }}>${exception.business_unit}</div></div>
      </div>

      <hr class="hairline" />

      <div class="stack gap-4">
        <span class="text-muted text-small">Financial impact</span>
        <span class="text-kpi" style=${{ color: "var(--exception)" }}>₹${matchResult.financial_impact.toLocaleString("en-IN")}</span>
        <span class="text-muted text-small">${matchResult.financial_impact_basis}</span>
      </div>

      ${error ? html`<${ErrorState} compact=${true} title="Explanation unavailable" message=${error} onRetry=${load} />`
        : loading ? html`<${Skeleton} height="120px" />` : !reasoning ? html`
        <button class="btn btn-primary" style=${{ width: "fit-content" }} onClick=${handleGenerate} disabled=${generating}>
          ${generating ? "Analyzing…" : html`<${Icon} name="note" size=${15} /> Generate exception explanation`}
        </button>
      ` : html`
        <div class="panel-elevated stack gap-12" style=${{ padding: 18 }}>
          <div class="row gap-8" style=${{ flexWrap: "wrap" }}>
            <${Badge} tone=${SEVERITY_TONE[reasoning.severity] || "neutral"}>${reasoning.severity} severity<//>
            <${Badge} tone="warning">Human review required<//>
            <${Badge} tone=${reasoning._ai_source === "ai" ? "accent" : "neutral"}>
              ${reasoning._ai_source === "ai" ? "AI-generated explanation" : "Generated from computed findings"}
            <//>
            <${Badge} tone="neutral">Confidence ${Math.round(reasoning.confidence * 100)}%<//>
          </div>
          <p>${reasoning.description}</p>
          <div class="stack gap-4">
            <span class="text-muted text-small">Recommended action</span>
            <span style=${{ fontWeight: 600 }}>${reasoning.recommended_action}</span>
          </div>
          <button class="btn btn-ghost btn-sm" style=${{ width: "fit-content" }} onClick=${handleGenerate} disabled=${generating}>
            ${generating ? "Regenerating…" : "Regenerate explanation"}
          </button>
        </div>
      `}

      <hr class="hairline" />
      <div class="stack gap-12" data-tour="investigation-trace">
        <span class="text-section-title" style=${{ fontSize: 16 }}>Investigation trace</span>
        <${InvestigationTrace} documents=${documents} matchResult=${matchResult} reasoning=${reasoning} graph=${graph} />
      </div>
    </div>
  `;
}
