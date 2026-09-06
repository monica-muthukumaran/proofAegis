import { html, useState, useEffect } from "../lib.js";
import * as api from "../services/api.js";
import { Skeleton, ErrorState } from "../components/ui/primitives.js";
import { ModeBanner } from "../components/ui/ModeBanner.js";

export function Settings() {
  const [tolerance, setTolerance] = useState(null);
  const [error, setError] = useState(null);

  const load = async () => {
    setError(null);
    const r = await api.getTolerance();
    if (r.source === "error") { setError(r.error); return; }
    setTolerance(r.data);
  };

  useEffect(() => { load(); }, []);

  return html`
    <div class="stack gap-24" style=${{ maxWidth: 560 }}>
      <div class="stack gap-4">
        <h1 class="text-page-title">Settings</h1>
        <p class="text-secondary">Tolerance thresholds used by the matching engine. Read-only in this build.</p>
      </div>

      <div class="panel stack gap-16" style=${{ padding: 24 }}>
        ${error ? html`<${ErrorState} compact=${true} title="Could not load tolerance rules" message=${error} onRetry=${load} />` : !tolerance ? html`<${Skeleton} height="80px" />` : html`
          <div class="row gap-24" style=${{ flexWrap: "wrap" }}>
            <div class="panel-elevated stack gap-4" style=${{ padding: 18, flex: "1 1 200px" }}>
              <span class="text-muted text-small">Price variance tolerance</span>
              <span class="text-kpi">${tolerance.price_variance_percent}%</span>
            </div>
            <div class="panel-elevated stack gap-4" style=${{ padding: 18, flex: "1 1 200px" }}>
              <span class="text-muted text-small">Quantity variance tolerance</span>
              <span class="text-kpi">${tolerance.quantity_variance_percent}%</span>
            </div>
          </div>
        `}
        <${ModeBanner} />
        <p class="text-muted text-small">
          These thresholds live in Firestore's settings/tolerance_rules document and are applied by
          the deterministic matching engine on every comparison — never adjusted by AI.
        </p>
      </div>
    </div>
  `;
}
