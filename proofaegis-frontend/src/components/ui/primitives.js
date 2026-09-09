import { html, React, useEffect, useRef, createPortal } from "../../lib.js";
import { SpotArt } from "../brand/HeroArt.js";

// A tiny inline-SVG icon set — no external icon font/network dependency,
// and keeps the "professional icons only, no emoji" rule easy to honor.
export function Icon({ name, size = 18, className = "" }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: "1.8", strokeLinecap: "round", strokeLinejoin: "round", className: `icon ${className}` };
  const paths = {
    layers: html`<polygon points="12 2 2 7 12 12 22 7 12 2"/><polyline points="2 17 12 22 22 17"/><polyline points="2 12 12 17 22 12"/>`,
    grid: html`<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>`,
    inbox: html`<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z"/>`,
    file: html`<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8Z"/><polyline points="14 2 14 8 20 8"/>`,
    graph: html`<circle cx="6" cy="6" r="2.5"/><circle cx="18" cy="6" r="2.5"/><circle cx="12" cy="18" r="2.5"/><line x1="8" y1="7.5" x2="10.3" y2="16"/><line x1="16" y1="7.5" x2="13.7" y2="16"/><line x1="8.4" y1="6" x2="15.6" y2="6"/>`,
    note: html`<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>`,
    clock: html`<circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/>`,
    check: html`<polyline points="20 6 9 17 4 12"/>`,
    arrowRight: html`<line x1="5" y1="12" x2="19" y2="12"/><polyline points="12 5 19 12 12 19"/>`,
    arrowLeft: html`<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>`,
    close: html`<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>`,
    chevronDown: html`<polyline points="6 9 12 15 18 9"/>`,
    plus: html`<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>`,
    upload: html`<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/>`,
    play: html`<polygon points="5 3 19 12 5 21 5 3"/>`,
    logout: html`<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>`,
    shield: html`<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10Z"/>`,
    zoomIn: html`<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="11" y1="8" x2="11" y2="14"/><line x1="8" y1="11" x2="14" y2="11"/>`,
    zoomOut: html`<circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/><line x1="8" y1="11" x2="14" y2="11"/>`,
    maximize: html`<path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/>`,
    history: html`<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><polyline points="12 7 12 12 16 14"/>`,
    settings: html`<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1Z"/>`,
    building: html`<rect x="4" y="2" width="16" height="20"/><line x1="9" y1="6" x2="9" y2="6.01"/><line x1="15" y1="6" x2="15" y2="6.01"/><line x1="9" y1="10" x2="9" y2="10.01"/><line x1="15" y1="10" x2="15" y2="10.01"/><line x1="9" y1="14" x2="9" y2="14.01"/><line x1="15" y1="14" x2="15" y2="14.01"/>`,
  };
  return React.createElement("svg", common, ...React.Children.toArray(paths[name] || paths.file));
}

export function Badge({ tone = "neutral", children }) {
  return html`<span class="badge badge-${tone}"><span class="badge-dot" style=${{ background: "currentColor" }}></span>${children}</span>`;
}

export function Skeleton({ width = "100%", height = "16px", style = {} }) {
  return html`<div class="skeleton" style=${{ width, height, ...style }}></div>`;
}

// `icon` is kept for callers that pass one, but the default is now the drawn
// spot illustration: a 56px grey circle around a feather glyph is the same
// empty state every dashboard has had since 2016, and it says nothing about
// what this product does with a document.
export function EmptyState({ icon = null, title, description, action }) {
  return html`
    <div class="stack gap-16" style=${{ alignItems: "center", textAlign: "center", padding: "48px 24px" }}>
      ${icon
        ? html`<div class="panel-elevated" style=${{ width: 56, height: 56, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 999, color: "var(--text-muted)" }}>
            <${Icon} name=${icon} size=${26} />
          </div>`
        : html`<${SpotArt} tone="empty" />`}
      <div class="stack gap-8" style=${{ alignItems: "center" }}>
        <h3 class="text-section-title">${title}</h3>
        <p class="text-secondary" style=${{ maxWidth: 380 }}>${description}</p>
      </div>
      ${action}
    </div>
  `;
}

// A real failure, shown as one. Nothing in this app should quietly replace a
// failed request with sample data — a wrong number in an AP tool is worse
// than a visible error.
export function ErrorState({ title = "Something went wrong", message, onRetry, compact = false }) {
  if (compact) {
    return html`
      <div class="row gap-8" style=${{ alignItems: "center", flexWrap: "wrap" }}>
        <${Badge} tone="exception">${title}<//>
        <span class="text-muted text-small">${message}</span>
        ${onRetry ? html`<button class="btn btn-ghost btn-sm" onClick=${onRetry}>Retry</button>` : null}
      </div>
    `;
  }
  return html`
    <div class="stack gap-16" style=${{ alignItems: "center", textAlign: "center", padding: "44px 24px" }}>
      <${SpotArt} tone="error" />
      <div class="stack gap-8" style=${{ alignItems: "center" }}>
        <h3 class="text-section-title">${title}</h3>
        <p class="text-secondary" style=${{ maxWidth: 420 }}>${message}</p>
      </div>
      ${onRetry ? html`<button class="btn btn-secondary" onClick=${onRetry}>Try again</button>` : null}
    </div>
  `;
}

export function ProgressBar({ value = 0, tone = "accent", label }) {
  const pct = Math.max(0, Math.min(100, Math.round(value)));
  return html`
    <div class="stack gap-4" style=${{ width: "100%" }}>
      ${label ? html`<div class="row" style=${{ justifyContent: "space-between" }}>
        <span class="text-muted text-small">${label}</span>
        <span class="text-muted text-small">${pct}%</span>
      </div>` : null}
      <div role="progressbar" aria-valuenow=${pct} aria-valuemin="0" aria-valuemax="100"
        style=${{ height: 6, borderRadius: 999, background: "var(--surface-3, rgba(148,163,184,0.2))", overflow: "hidden" }}>
        <div style=${{ width: `${pct}%`, height: "100%", background: `var(--${tone})`, transition: "width .25s ease" }}></div>
      </div>
    </div>
  `;
}

// `label` names the dialog for assistive tech. It used to be the hardcoded
// string "Dialog" for every caller, which tells a screen-reader user that
// something opened and nothing about what — on a screen that may have several
// different modals, that is the difference between orientation and a guess.
export function Modal({ open, onClose, children, wide = false, label = "Dialog" }) {
  const modalRef = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => { if (event.key === "Escape") onClose && onClose(); };
    document.addEventListener("keydown", onKeyDown);
    const timer = window.setTimeout(() => modalRef.current?.focus(), 0);
    return () => { document.removeEventListener("keydown", onKeyDown); window.clearTimeout(timer); };
  }, [open, onClose]);
  if (!open) return null;
  // Portalled to document.body — see the note in lib.js. Rendered in place it
  // inherits whichever ancestor happens to hold a transform, an overflow or a
  // stacking context, and this app has all three above different callers.
  return createPortal(html`
    <div class="overlay-backdrop" onClick=${(e) => { if (e.target === e.currentTarget) onClose && onClose(); }} role="presentation">
      <div class="modal-center" style=${wide ? { width: 640 } : {}} role="dialog" aria-modal="true" aria-label=${label} tabIndex="-1" ref=${modalRef}>${children}</div>
    </div>
  `, document.body);
}

export function Drawer({ open, onClose, title, children }) {
  const drawerRef = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => { if (event.key === "Escape") onClose && onClose(); };
    document.addEventListener("keydown", onKeyDown);
    const timer = window.setTimeout(() => drawerRef.current?.focus(), 0);
    return () => { document.removeEventListener("keydown", onKeyDown); window.clearTimeout(timer); };
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(html`
    <div class="overlay-backdrop" onClick=${(e) => { if (e.target === e.currentTarget) onClose && onClose(); }}>
      <div class="drawer" role="dialog" aria-modal="true" aria-label=${title} tabIndex="-1" ref=${drawerRef}>
        <div class="row" style=${{ justifyContent: "space-between", marginBottom: 18 }}>
          <h3 class="text-section-title">${title}</h3>
          <button class="btn btn-ghost btn-sm" onClick=${onClose} aria-label="Close"><${Icon} name="close" size=${16} /></button>
        </div>
        ${children}
      </div>
    </div>
  `, document.body);
}
