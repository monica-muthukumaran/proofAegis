// AgentBadge.js — says whether a model is actually running, and which one.
//
// The mode banner already reported "Gemini off — deterministic extraction",
// which answered half the question. It never named the model, and it said
// nothing at all when a model WAS running — so the informative case was the
// silent one. For a product whose whole claim is that a reviewer can check
// what produced a figure, "some model did it" fails the same test an uncited
// number does.
//
// Rules this component keeps, in the spirit of ModeBanner beside it:
//
//   * It reports; it never assumes. Every fact comes from /api/settings/mode.
//     When the backend has not answered, it says so rather than guessing.
//   * Configured is not running. A key can be present while mock mode means
//     no model is ever called; `live` comes from the backend's single
//     `gemini_active` verdict, and every agent row is stamped from that same
//     verdict so the badge and the list can never disagree.
//   * An older backend that does not send `agents` still gets a correct
//     badge — it just cannot offer the per-agent breakdown, and says so
//     instead of inventing one.
import { html, useState, useEffect, useRef } from "../../lib.js";
import { Icon } from "./primitives.js";

// The order the pipeline actually runs in, so the list reads as a sequence
// rather than as whatever order the server serialised.
const STAGE_ORDER = ["extract", "reason", "investigate", "resolve"];
const STAGE_LABEL = {
  extract: "Extraction",
  reason: "Reasoning",
  investigate: "Investigation",
  resolve: "Resolution",
};

function byStage(agents) {
  const groups = new Map();
  for (const stage of STAGE_ORDER) groups.set(stage, []);
  for (const agent of agents) {
    if (!groups.has(agent.stage)) groups.set(agent.stage, []);
    groups.get(agent.stage).push(agent);
  }
  return [...groups.entries()].filter(([, list]) => list.length);
}

export function AgentBadge({ mode, demo = false, unreachable = false }) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef(null);

  // Dismiss on outside click and on Escape. Both, because a popover that only
  // closes one way is the kind of thing that traps a keyboard user.
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target)) setOpen(false);
    };
    const onKey = (e) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const agents = (mode && Array.isArray(mode.agents)) ? mode.agents : [];

  // Where the calls go. Not derivable from the model name — "gemini-3.5-flash"
  // is the same string on Vertex and on the AI Studio Developer API — and the
  // difference decides which project is billed and which credential
  // authenticates. An older backend omits the field; that reads as "not
  // stated" rather than as a default, because guessing here is exactly the
  // kind of confident falsehood this panel exists to avoid.
  const routing = mode && mode.ai_routing;
  const ROUTING_LABEL = {
    vertex: "Vertex AI",
    developer_api: "AI Studio Developer API",
  };

  // Three states, deliberately distinct. "Unknown" is not folded into "off":
  // a banner that reports a model as disabled when it simply could not ask is
  // making a claim it has not checked.
  let state;
  if (unreachable || (!mode && !demo)) state = "unknown";
  else if (demo || !mode || mode.gemini_active !== true) state = "off";
  else state = "live";

  // The headline model is the reasoning one: it is what writes the analysis a
  // reviewer reads. Extraction is named in the breakdown.
  const headlineModel = mode && (mode.reasoning_model || mode.extraction_model);

  const TONE = { live: "badge-verified", off: "badge-neutral", unknown: "badge-neutral" };
  const LABEL = {
    live: headlineModel ? "Agent live" : "Agent live",
    off: "Agent off — deterministic",
    unknown: "Agent status unknown",
  };

  const canExpand = agents.length > 0 || state !== "unknown";

  const explanation = state === "live"
    ? `A model is being called. Reasoning model: ${headlineModel || "unnamed"}.`
    : state === "off"
      ? "No model is being called. Extraction and matching are deterministic."
      : "The backend has not reported its model configuration.";

  // The accessible name has to START with the visible text. A bare `title`
  // becomes the accessible name and REPLACES the label, so a screen-reader
  // user heard "No model is being called…" while the button on screen read
  // "Agent off — deterministic" — two different strings for one control,
  // which is what WCAG 2.5.3 (Label in Name) exists to prevent and which also
  // breaks voice control, where the user says what they can see.
  const accessibleName = [
    LABEL[state],
    state === "live" && headlineModel ? headlineModel : null,
    // The routing chip is visible text on the button, so it belongs in the
    // accessible name for the same reason the label does — see the note above.
    state === "live" && routing ? (routing === "vertex" ? "Vertex" : "AI Studio") : null,
    "—",
    explanation,
    state === "live" && routing ? `Routed via ${ROUTING_LABEL[routing] || routing}.` : null,
  ].filter(Boolean).join(" ");

  return html`
    <span class="agent-badge-wrap" ref=${wrapRef}>
      <button
        type="button"
        class=${`badge ${TONE[state]} agent-badge`}
        aria-expanded=${open}
        aria-haspopup="dialog"
        aria-label=${accessibleName}
        disabled=${!canExpand}
        onClick=${() => setOpen((v) => !v)}
        title=${explanation}>
        <span class=${`agent-dot ${state}`}></span>
        ${LABEL[state]}
        ${state === "live" && headlineModel
          ? html`<span class="mono agent-badge-model">${headlineModel}</span>`
          : null}
        ${state === "live" && routing
          ? html`<span class=${`agent-routing ${routing}`}>${routing === "vertex" ? "Vertex" : "AI Studio"}</span>`
          : null}
        ${canExpand ? html`<${Icon} name="chevronDown" size=${12} className="agent-caret" />` : null}
      </button>

      ${open ? html`
        <div class="agent-pop panel" role="dialog" aria-label="Agent configuration">
          <div class="agent-pop-head">
            <span class=${`agent-dot ${state}`}></span>
            <strong>
              ${state === "live" ? "Models are being called" : null}
              ${state === "off" ? "No model is being called" : null}
              ${state === "unknown" ? "Model configuration unknown" : null}
            </strong>
          </div>

          ${state === "off" ? html`
            <p class="text-muted text-small agent-pop-note">
              ${demo
                ? "The guided tour and demo mode run entirely on seeded data — extraction, matching and every figure on screen are deterministic, and nothing is sent to a model."
                : "Extraction and matching are running deterministically. Figures on screen were computed by code, not generated."}
            </p>
          ` : null}

          ${state === "unknown" ? html`
            <p class="text-muted text-small agent-pop-note">
              The backend has not answered <span class="mono">/api/settings/mode</span>, so which
              model would run cannot be confirmed. Nothing here is being assumed.
            </p>
          ` : null}

          ${state === "live" ? html`
            <div class="agent-routing-row">
              <span class="agent-routing-label">Routed via</span>
              <span class="agent-routing-value">
                ${routing ? ROUTING_LABEL[routing] || routing : "not reported by this backend"}
                ${routing === "vertex" && mode.vertex_location
                  ? html`<span class="mono agent-routing-loc">${mode.vertex_location}</span>`
                  : null}
              </span>
            </div>
            ${routing ? html`
              <p class="text-muted text-small agent-pop-note">
                ${routing === "vertex"
                  ? "Calls authenticate as the runtime service account and bill this Google Cloud project."
                  : "Calls authenticate with GEMINI_API_KEY and bill a separate AI Studio wallet, not this Cloud project."}
              </p>
            ` : null}
          ` : null}

          ${agents.length ? html`
            <div class="agent-pop-list">
              ${byStage(agents).map(([stage, list]) => html`
                <div class="agent-stage" key=${stage}>
                  <div class="agent-stage-label">${STAGE_LABEL[stage] || stage}</div>
                  ${list.map((agent) => html`
                    <div class="agent-row" key=${agent.key}>
                      <span class="agent-row-label">${agent.label}</span>
                      <span class=${`mono agent-row-model ${agent.live ? "" : "is-idle"}`}>
                        ${agent.model || "—"}
                      </span>
                    </div>
                  `)}
                </div>
              `)}
            </div>
            <p class="text-muted text-small agent-pop-note">
              ${state === "live"
                ? "Every model output is checked against the deterministic result; where they disagree, the computed figure is authoritative and the disagreement is recorded in the audit trail."
                : "These are the models that would run once a key is configured and mock mode is off."}
            </p>
          ` : state === "live" ? html`
            <p class="text-muted text-small agent-pop-note">
              This backend reports that a model is active but does not publish a per-agent
              breakdown.
            </p>
          ` : null}
        </div>
      ` : null}
    </span>
  `;
}
