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
//   * The synthetic-data label appears whenever the data on screen IS
//     synthetic, and only then. It used to be unconditional, which was true
//     while there was one shared demo workspace and became a lie the moment a
//     signed-in user got their own: every case in Alice's workspace is one she
//     uploaded herself. The backend answers this at /api/settings/mode
//     (`synthetic_data`), so the banner reports rather than assumes — and when
//     it cannot know (backend unreachable, frontend demo mode), it keeps the
//     label, because an unlabelled synthetic figure is the worse mistake.
import { html, useState, useEffect } from "../../lib.js";
import * as api from "../../services/api.js";
import { Badge, Icon } from "./primitives.js";
import { AgentBadge } from "./AgentBadge.js";

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
    // The agent badge replaces what used to be a lone "Gemini off" chip. That
    // chip only ever appeared when a model was NOT running, so the case a
    // reviewer most needs to see — a model IS running, and here is which one —
    // was the one that rendered nothing. AgentBadge reports both, and names
    // the model in either direction.
    badges.push(html`<${AgentBadge} key="agent" mode=${mode} demo=${demo} />`);
  } else if (mode) {
    badges.push(html`<${Badge} key="down" tone="exception">API unreachable<//>`);
    // Unreachable is not the same as off: without an answer we cannot say
    // what would run, and the badge says exactly that rather than guessing.
    badges.push(html`<${AgentBadge} key="agent" mode=${null} demo=${demo} unreachable=${true} />`);
  }

  // `=== false` and not a falsy check: an older backend omits the field
  // entirely, and "not stated" must keep the label rather than drop it.
  const knownReal = mode && mode.reachable && mode.synthetic_data === false;
  if (demo || !knownReal) {
    badges.push(html`<${Badge} key="synth" tone="neutral">Synthetic data only<//>`);
  } else if (mode.workspace_id) {
    badges.push(html`<${Badge} key="ws" tone="verified">Your workspace<//>`);
  }

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
