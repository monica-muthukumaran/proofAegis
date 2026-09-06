// RegisterToolbar.js — the search/filter/count strip shared by the invoice
// and purchase-order registers, plus the sortable column header.
//
// Both registers filter and sort entirely in the browser. That is not a
// shortcut: routes/exceptions.py returns the whole portfolio in one request
// by design ("no server-side filtering", per the pack), so re-querying per
// keystroke would add latency without adding a single row.
import { html } from "../../lib.js";

export function RegisterToolbar({
  query, setQuery, placeholder, searchLabel,
  status, setStatus, statuses,
  extra, shown, total, unit,
}) {
  return html`
    <div class="row gap-12" style=${{ flexWrap: "wrap" }}>
      <input class="input" style=${{ maxWidth: 320 }} aria-label=${searchLabel}
        placeholder=${placeholder} value=${query} onInput=${(e) => setQuery(e.target.value)} />
      ${statuses && statuses.length ? html`
        <select class="input" style=${{ maxWidth: 200 }} aria-label="Filter by status"
          value=${status} onChange=${(e) => setStatus(e.target.value)}>
          <option value="all">All statuses</option>
          ${statuses.map((s) => html`<option key=${s} value=${s}>${s.replaceAll("_", " ")}</option>`)}
        </select>
      ` : null}
      ${extra || null}
      <span class="text-muted text-small" style=${{ marginLeft: "auto", alignSelf: "center" }}>
        ${shown} of ${total} ${unit}
      </span>
    </div>
  `;
}

/**
 * A sortable <th>. Returns a factory so a table declares its headers as
 * `th("invoice_amount", "Invoiced")` without threading sort state through
 * every call site.
 */
export function makeSortHeader(sortKey, sortDir, setSort) {
  return (key, heading, hint, align) => html`
    <th key=${key} style=${align === "right" ? { textAlign: "right" } : null}
      aria-sort=${sortKey === key ? (sortDir === "asc" ? "ascending" : "descending") : "none"}>
      <button class="sort-button" onClick=${() => setSort(key)} title=${hint || undefined}>
        ${heading}${hint ? html`<abbr class="hint-mark" title=${hint}>?</abbr>` : ""} ${sortKey === key ? (sortDir === "asc" ? "↑" : "↓") : ""}
      </button>
    </th>
  `;
}
