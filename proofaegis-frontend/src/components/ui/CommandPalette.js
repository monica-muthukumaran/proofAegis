// CommandPalette.js — ⌘K / Ctrl+K.
//
// At three cases, navigation was a sidebar. At four hundred, finding
// "the BlueWave invoice from last week" through a sidebar, a queue, a filter
// and a scroll is four interactions too many. This is one.
//
// Searches vendors, invoice numbers, exception ids and types alongside the
// app's own destinations, and ranks a prefix match above a substring one so
// typing an invoice number puts it first rather than eighth.
import { html, useState, useEffect, useRef, useMemo, createPortal } from "../../lib.js";
import { Icon, Badge } from "./primitives.js";

const NAV_COMMANDS = [
  { id: "nav-dashboard", kind: "page", label: "Dashboard", hint: "Overview and priority case", view: "dashboard" },
  { id: "nav-exceptions", kind: "page", label: "Exception Queue", hint: "Triage every open case", view: "exceptions" },
  { id: "nav-invoices", kind: "page", label: "Invoices", hint: "Every invoice ingested, cleared and blocked", view: "invoices" },
  { id: "nav-purchase-orders", kind: "page", label: "Purchase Orders", hint: "Billed against ordered, per PO", view: "purchase-orders" },
  { id: "nav-vendors", kind: "page", label: "Vendors", hint: "Ranked by value at risk", view: "vendors" },
  { id: "nav-analytics", kind: "page", label: "Analytics", hint: "Vendor risk and trends", view: "analytics" },
  { id: "nav-settings", kind: "page", label: "Settings", hint: "Tolerance rules", view: "settings" },
];

const MAX_RESULTS = 8;

function score(haystack, needle) {
  if (!haystack) return -1;
  const text = String(haystack).toLowerCase();
  const index = text.indexOf(needle);
  if (index === -1) return -1;
  // Prefix beats substring; earlier beats later.
  return index === 0 ? 1000 : 500 - index;
}

export function CommandPalette({ open, onClose, exceptions, onNavigate, onOpenException, onNewCase }) {
  const [query, setQuery] = useState("");
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      const timer = window.setTimeout(() => inputRef.current && inputRef.current.focus(), 20);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [open]);

  const results = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const actions = [
      ...NAV_COMMANDS,
      { id: "action-new-case", kind: "action", label: "New case from PDFs", hint: "Upload invoice and supporting documents", action: "new-case" },
    ];

    if (!needle) {
      return actions.slice(0, MAX_RESULTS);
    }

    const scored = [];
    actions.forEach((c) => {
      const s = Math.max(score(c.label, needle), score(c.hint, needle));
      if (s > 0) scored.push({ ...c, _score: s + 200 }); // destinations rank slightly high
    });

    (exceptions || []).forEach((e) => {
      const s = Math.max(
        score(e.exception_id, needle),
        score(e.invoice_id, needle),
        score(e.vendor_name, needle),
        score(e.exception_type, needle),
      );
      if (s > 0) {
        scored.push({
          id: e.exception_id,
          kind: "case",
          label: `${e.invoice_id || e.exception_id} · ${e.vendor_name || "Unknown vendor"}`,
          hint: e.exception_type ? String(e.exception_type).replaceAll("_", " ") : "not analysed",
          tone: e.exception_type === "no_exception" ? "verified" : "exception",
          exceptionId: e.exception_id,
          _score: s,
        });
      }
    });

    scored.sort((a, b) => b._score - a._score);
    return scored.slice(0, MAX_RESULTS);
  }, [query, exceptions]);

  useEffect(() => { setCursor(0); }, [query]);

  const run = (item) => {
    if (!item) return;
    onClose();
    if (item.kind === "case") onOpenException(item.exceptionId);
    else if (item.action === "new-case") onNewCase();
    else if (item.view) onNavigate(item.view);
  };

  const onKeyDown = (event) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setCursor((c) => Math.min(c + 1, results.length - 1));
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    } else if (event.key === "Enter") {
      event.preventDefault();
      run(results[cursor]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      onClose();
    }
  };

  if (!open) return null;

  return createPortal(html`
    <div class="overlay-backdrop palette-backdrop" role="presentation"
      onClick=${(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div class="palette" role="dialog" aria-modal="true" aria-label="Command palette">
        <div class="palette-input-row">
          <${Icon} name="zoomIn" size=${17} />
          <input ref=${inputRef} class="palette-input" type="text"
            placeholder="Search cases, vendors, invoices, or jump to a page…"
            aria-label="Search cases and pages"
            value=${query}
            onInput=${(e) => setQuery(e.target.value)}
            onKeyDown=${onKeyDown} />
          <kbd class="kbd">Esc</kbd>
        </div>

        <div class="palette-results" role="listbox">
          ${results.length === 0 ? html`
            <div class="palette-empty text-muted text-small">No matches for “${query}”.</div>
          ` : results.map((item, i) => html`
            <button key=${item.id} role="option" aria-selected=${i === cursor}
              class="palette-item ${i === cursor ? "active" : ""}"
              onMouseEnter=${() => setCursor(i)}
              onClick=${() => run(item)}>
              <${Icon} name=${item.kind === "case" ? "file" : item.kind === "action" ? "upload" : "arrowRight"} size=${15} />
              <span class="palette-label">${item.label}</span>
              ${item.kind === "case"
                ? html`<${Badge} tone=${item.tone}>${item.hint}<//>`
                : html`<span class="text-muted text-small">${item.hint}</span>`}
            </button>
          `)}
        </div>

        <div class="palette-footer text-muted text-small">
          <span><kbd class="kbd">↑</kbd><kbd class="kbd">↓</kbd> navigate</span>
          <span><kbd class="kbd">↵</kbd> open</span>
        </div>
      </div>
    </div>
  `, document.body);
}
