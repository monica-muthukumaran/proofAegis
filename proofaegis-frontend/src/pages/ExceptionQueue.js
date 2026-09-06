import { html, useState, useEffect } from "../lib.js";
import * as api from "../services/api.js";
import { ExceptionTable } from "../components/exceptions/ExceptionTable.js";
import { EmptyState, Skeleton, ErrorState } from "../components/ui/primitives.js";
import { ModeBanner } from "../components/ui/ModeBanner.js";

export function ExceptionQueue({ openException, initialQuery = "" }) {
  const [exceptions, setExceptions] = useState(null);
  const [error, setError] = useState(null);

  const load = async () => {
    setError(null);
    const r = await api.listExceptions();
    if (r.source === "error") { setError(r.error); setExceptions(null); return; }
    setExceptions(r.data);
  };

  useEffect(() => { load(); }, []);

  return html`
    <div class="stack gap-24" data-tour="sample-documents-anchor">
      <div class="stack gap-4">
        <h1 class="text-page-title">Exception Queue</h1>
        <p class="text-secondary">Invoices needing attention, with cleared ones a filter away. Search, filter, and sort locally — nothing here requires another request.</p>
      </div>
      <${ModeBanner} compact=${true} />

      <div class="panel" style=${{ padding: 22 }}>
        ${error ? html`<${ErrorState} title="Could not load exceptions" message=${error} onRetry=${load} />` :
          !exceptions ? html`<div class="stack gap-12">${[1,2,3].map((i) => html`<${Skeleton} key=${i} height="44px" />`)}</div>` :
          exceptions.length === 0 ? html`
            <${EmptyState} icon="inbox" title="No exceptions yet"
              description="Upload an invoice, purchase order, and goods receipt to begin your first investigation." />
          ` : html`<${ExceptionTable} exceptions=${exceptions} onOpen=${openException} initialQuery=${initialQuery} />`
        }
      </div>
    </div>
  `;
}
