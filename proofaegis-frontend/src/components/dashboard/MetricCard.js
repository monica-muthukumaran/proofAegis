import { html } from "../../lib.js";
import { Icon } from "../ui/primitives.js";
import { useCountUp } from "../../lib/useCountUp.js";

// `value` renders as given (already-formatted strings, em dashes while
// loading). Pass `raw` + `format` instead to have the figure count up on
// mount: `raw` is the real number, `format` turns each animation frame into
// display text. The final frame is always the exact value, so an animated
// KPI can never disagree with the API response behind it.
export function MetricCard({ icon, label, value, raw, format, sublabel, hint, tone }) {
  const animated = useCountUp(typeof raw === "number" ? raw : null);
  const shown = typeof raw === "number" && format ? format(animated) : value;

  return html`
    <div class="panel kpi-card stack gap-8 ${tone ? `kpi-${tone}` : ""}">
      <div class="row" style=${{ justifyContent: "space-between" }}>
        <span class="text-muted text-small">
          ${label}${hint ? html`<abbr class="hint-mark" title=${hint}>?</abbr>` : ""}
        </span>
        <div style=${{ color: "var(--text-muted)" }}><${Icon} name=${icon} size=${16} /></div>
      </div>
      <div class="text-kpi">${shown}</div>
      <div class="text-muted text-small">${sublabel}</div>
    </div>
  `;
}
