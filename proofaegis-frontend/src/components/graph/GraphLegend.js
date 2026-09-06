import { html } from "../../lib.js";

// The swatches read their colour from the same custom properties the nodes
// do, so a legend can never drift out of step with the thing it describes.
// They were hardcoded rgba() literals before, which is how a legend ends up
// claiming "extracted value" is grey on a screen where it is green.
//
// Order matches the graph's left-to-right reading order, because that is the
// order a reader meets these things in.
const LEGEND = [
  { type: "document", label: "Source document", token: "--viz-document" },
  { type: "extracted_value", label: "Extracted value", token: "--viz-value" },
  { type: "business_rule", label: "Rule applied", token: "--viz-rule" },
  { type: "finding", label: "Finding", token: "--viz-finding" },
  { type: "routing", label: "Routing", token: "--viz-routing" },
];

export function GraphLegend() {
  return html`
    <div class="graph-legend" role="list" aria-label="Evidence graph node types">
      ${LEGEND.map((entry) => html`
        <div class="graph-legend-item" role="listitem" key=${entry.type}>
          <span class="graph-legend-swatch" style=${{ background: `var(${entry.token})` }}></span>
          ${entry.label}
        </div>
      `)}
    </div>
  `;
}
