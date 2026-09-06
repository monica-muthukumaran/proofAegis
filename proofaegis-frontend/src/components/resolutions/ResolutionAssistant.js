import { html, useState, useEffect } from "../../lib.js";
import * as api from "../../services/api.js";
import { DraftEditor } from "./DraftEditor.js";
import { EmptyState, Skeleton, Icon, Badge, ErrorState } from "../ui/primitives.js";

export function ResolutionAssistant({ exceptionId, onOpenCitation }) {
  const [draft, setDraft] = useState(null);
  const [loading, setLoading] = useState(true);
  const [generating, setGenerating] = useState(false);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    const r = await api.getResolution(exceptionId);
    if (r.source === "error") setError(r.error);
    setDraft(r.data);
    setLoading(false);
  };

  useEffect(() => { load(); }, [exceptionId]);

  const handleGenerate = async () => {
    setGenerating(true);
    setError(null);
    const r = await api.generateResolution(exceptionId);
    if (r.source === "error") setError(r.error);
    else setDraft(r.data);
    setGenerating(false);
  };

  if (error) return html`<${ErrorState} title="Draft unavailable" message=${error} onRetry=${load} />`;
  if (loading) return html`<${Skeleton} height="220px" />`;

  if (!draft) {
    return html`
      <${EmptyState}
        icon="note"
        title="No draft generated yet"
        description="Generate a source-cited resolution message from the verified findings for this exception."
        action=${html`
          <button class="btn btn-primary" onClick=${handleGenerate} disabled=${generating} data-tour="generate-resolution-btn">
            ${generating ? "Generating…" : html`<${Icon} name="note" size=${15} /> Generate resolution draft`}
          </button>
        `}
      />
    `;
  }

  return html`
    <div class="stack gap-16">
      <div class="row gap-8" style=${{ justifyContent: "space-between", flexWrap: "wrap" }}>
        <div class="row gap-8" style=${{ flexWrap: "wrap" }}>
          <${Badge} tone=${draft._ai_source === "ai" ? "accent" : "neutral"}>
            ${draft._ai_source === "ai" ? "AI-generated draft" : "Draft built from computed findings"}
          <//>
          <${Badge} tone="warning">Review before sending<//>
        </div>
        <button class="btn btn-secondary btn-sm" onClick=${handleGenerate} disabled=${generating}>
          ${generating ? "Regenerating…" : "Regenerate draft"}
        </button>
      </div>
      <${DraftEditor} draft=${draft} onOpenCitation=${onOpenCitation} />
    </div>
  `;
}
