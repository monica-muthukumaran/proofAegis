// ModeBanner.js — says out loud what the app is actually connected to.
//
// The old banner inferred "backend offline" from a failed request, which
// conflated three very different situations: the server is down, you are
// signed out, and the server is deliberately serving seeded data. This asks
// the backend directly (/api/health, then /api/settings/mode) and reports
// what it says.
//
// Rules this component exists to keep honest:
//   * Demo mode is never entered silently. If the backend is unreachable the
//     banner says so and OFFERS demo mode as a button; it does not switch.
//   * A live backend running on seeded data still says "seeded data".
//   * The synthetic-data label is always visible, because the data always is.
import { html, useState, useEffect } from "../../lib.js";
import * as api from "../../services/api.js";
import { Badge, Icon } from "./primitives.js";

export function ModeBanner({ compact = false }) {
  const [mode, setMode] = useState(null);
  const [checking, setChecking] = useState(true);
  const [demo, setDemo] = useState(api.isDemoMode());

  const check = async () => {
    setChecking(true);
    const health = await api.checkBackend();
    if (health.reachable) {
      const detail = await api.getMode();
      setMode({ reachable: true, ...(detail.source === "live" ? detail.data : health.data) });
    } else {
      setMode({ reachable: false, error: health.error });
    }
    setChecking(false);
  };

  useEffect(() => {
    check();
    return api.onModeChange(setDemo);
  }, []);

  const enableDemo = () => {
    api.setDemoMode(true);
    setDemo(true);
  };

  if (checking && !mode) {
    return html`<${Badge} tone="neutral">Checking backend…<//>`;
  }

  const badges = [];

  if (demo) {
    badges.push(html`<${Badge} key="demo" tone="warning">Demo mode — seeded sample data<//>`);
  }

  if (mode && mode.reachable) {
    badges.push(html`<${Badge} key="api" tone="verified">API connected<//>`);
    if (mode.mock_mode) {
      badges.push(html`<${Badge} key="seed" tone="warning">Backend serving seeded data<//>`);
    }
    if (mode.storage_backend) {
      badges.push(html`<${Badge} key="store" tone="neutral">
        Storage: ${mode.storage_backend === "gcs" ? `Cloud Storage (${mode.storage_bucket || "bucket"})` : "local disk"}
      <//>`);
    }
    // gemini_active, not gemini_configured: a key can be present while mock
    // mode means no model is ever called.
    if (mode.gemini_active === false) {
      badges.push(html`<${Badge} key="ai" tone="neutral">Gemini off — deterministic extraction<//>`);
    }
  } else if (mode) {
    badges.push(html`<${Badge} key="down" tone="exception">API unreachable<//>`);
  }

  badges.push(html`<${Badge} key="synth" tone="neutral">Synthetic data only<//>`);

  return html`
    <div class="row gap-8" style=${{ flexWrap: "wrap", alignItems: "center" }}>
      ${badges}
      ${mode && !mode.reachable && !demo ? html`
        <span class="text-muted text-small">${mode.error}</span>
        <button class="btn btn-ghost btn-sm" onClick=${check}>Retry</button>
        <button class="btn btn-secondary btn-sm" onClick=${enableDemo}>
          <${Icon} name="play" size=${14} /> Continue in demo mode
        </button>
      ` : null}
      ${!compact && mode && mode.reachable && !checking ? html`
        <button class="btn btn-ghost btn-sm" onClick=${check} aria-label="Re-check backend connection">
          <${Icon} name="history" size=${14} />
        </button>
      ` : null}
    </div>
  `;
}
