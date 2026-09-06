import { html } from "../../lib.js";
import { EmptyState } from "../ui/primitives.js";

function formatTime(iso) {
  try { return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" }); }
  catch { return iso; }
}

export function AuditTab({ events, dataTourAnchor }) {
  if (!events || events.length === 0) {
    return html`<${EmptyState} icon="history" title="No audit events yet" description="Status changes, generated drafts, and review notes will appear here." />`;
  }
  return html`
    <div class="stack gap-0" data-tour=${dataTourAnchor}>
      ${events.map((e, i) => html`
        <div key=${e.event_id || i} class="row gap-16" style=${{ padding: "14px 4px", borderBottom: "1px solid var(--border)" }}>
          <div style=${{ width: 8, height: 8, borderRadius: 999, background: "var(--accent)", marginTop: 6, flex: "none" }}></div>
          <div class="stack gap-4" style=${{ flex: 1 }}>
            <span style=${{ fontWeight: 600 }}>${(e.note || e.action || "").toString().replaceAll("_", " ")}</span>
            ${e.from_status ? html`<span class="text-muted text-small">${e.from_status.replaceAll("_"," ")} → ${e.to_status.replaceAll("_"," ")}</span>` : null}
            <span class="text-muted text-small">${e.actor || "system"} · ${formatTime(e.timestamp)}</span>
          </div>
        </div>
      `)}
    </div>
  `;
}
