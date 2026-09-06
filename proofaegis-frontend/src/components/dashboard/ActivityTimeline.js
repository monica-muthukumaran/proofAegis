import { html } from "../../lib.js";
import { Icon } from "../ui/primitives.js";

const ACTION_ICON = {
  documents_processed: "file",
  finding_created: "graph",
  resolution_draft_generated: "file",
  exception_reasoning_generated: "file",
  status_changed: "check",
};

function timeAgo(iso) {
  const diffMs = Date.now() - new Date(iso).getTime();
  const mins = Math.round(diffMs / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function ActivityTimeline({ events }) {
  if (!events || events.length === 0) {
    return html`<p class="text-muted text-small">No activity yet.</p>`;
  }
  return html`
    <div class="stack gap-4">
      ${events.map((e) => html`
        <div class="row gap-12" key=${e.event_id} style=${{ padding: "10px 4px", borderBottom: "1px solid var(--border)" }}>
          <div class="panel-elevated" style=${{ width: 30, height: 30, borderRadius: 999, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--accent)", flex: "none" }}>
            <${Icon} name=${ACTION_ICON[e.action] || "clock"} size=${14} />
          </div>
          <div class="stack gap-4" style=${{ flex: 1 }}>
            <span class="text-small" style=${{ fontWeight: 600 }}>${(e.note || e.action || "").toString().replaceAll("_", " ")}</span>
            <span class="text-muted text-small">${e.actor || "system"} · ${timeAgo(e.timestamp)}</span>
          </div>
        </div>
      `)}
    </div>
  `;
}
