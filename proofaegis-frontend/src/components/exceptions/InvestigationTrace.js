import { html } from "../../lib.js";
import { Badge, Icon } from "../ui/primitives.js";

// Reflects the actual backend pipeline (backend/services/):
// document_agent.py + exception_agent.py + resolution_agent.py are the
// AI-capable steps; matching_service.py and graph_service.py are
// deliberately deterministic, never AI. No hidden chain-of-thought is shown
// here — only step names, status, and what actually produced each result.
//
// This used to be a static list that reported every step as "AI-backed" and
// "Complete" no matter what had run. With Gemini off, document extraction is
// the deterministic parser, and reasoning may not have been generated at all
// — a trace that claims otherwise undermines the one thing this panel is for.
export function InvestigationTrace({ documents, matchResult, reasoning, graph }) {
  const docs = documents || [];
  const extracted = docs.filter((d) => d.processing_state === "completed" && d.extraction);
  const usedGemini = extracted.some((d) => d.extraction_source === "ai");
  const anyExtraction = extracted.length > 0;

  const steps = [
    {
      key: "document_intelligence",
      label: "Document Intelligence",
      detail: !anyExtraction
        ? "No documents extracted yet"
        : usedGemini
          ? `Extracted fields from ${extracted.length} document${extracted.length === 1 ? "" : "s"} (Google ADK + Gemini)`
          : `Extracted fields from ${extracted.length} document${extracted.length === 1 ? "" : "s"} (deterministic parser — Gemini not configured)`,
      engine: !anyExtraction ? null : usedGemini ? "ai" : "deterministic",
      done: anyExtraction,
    },
    {
      key: "matching_engine",
      label: "Matching Engine",
      detail: matchResult
        ? `Tolerance comparison over ${matchResult.comparisons.length} fields — match score ${matchResult.match_score}%`
        : "Waiting for a vendor invoice",
      engine: "deterministic",
      done: Boolean(matchResult),
    },
    {
      key: "exception_reasoning",
      label: "Exception Reasoning",
      detail: reasoning
        ? (reasoning._ai_source === "ai"
            ? "Severity, explanation, and recommended action (Google ADK + Gemini)"
            : "Explanation composed from the computed findings")
        : "Not generated yet",
      engine: reasoning ? (reasoning._ai_source === "ai" ? "ai" : "deterministic") : null,
      done: Boolean(reasoning),
    },
    {
      key: "evidence_graph_builder",
      label: "Evidence Graph Builder",
      detail: graph && graph.nodes
        ? `${graph.nodes.length} nodes assembled from computed findings — no AI`
        : "Waiting for an analyzed exception",
      engine: "deterministic",
      done: Boolean(graph && graph.nodes && graph.nodes.length),
    },
  ];

  return html`
    <div class="stack gap-8">
      ${steps.map((s) => html`
        <div key=${s.key} class="row gap-12" style=${{ padding: "10px 4px", flexWrap: "wrap" }}>
          <div style=${{ color: s.done ? "var(--verified)" : "var(--muted)" }}>
            <${Icon} name=${s.done ? "check" : "clock"} size=${16} />
          </div>
          <div class="stack gap-2" style=${{ flex: 1, minWidth: 200 }}>
            <span style=${{ fontWeight: 600, fontSize: 14 }}>${s.label}</span>
            <span class="text-muted text-small">${s.detail}</span>
          </div>
          ${s.engine ? html`
            <${Badge} tone=${s.engine === "ai" ? "accent" : "neutral"}>
              ${s.engine === "ai" ? "AI-backed" : "Deterministic"}
            <//>
          ` : null}
          <${Badge} tone=${s.done ? "verified" : "neutral"}>${s.done ? "Complete" : "Pending"}<//>
        </div>
      `)}
    </div>
  `;
}
