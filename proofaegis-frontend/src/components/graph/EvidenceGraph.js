import { html, useState, useMemo, useRef, useCallback } from "../../lib.js";
import { GraphLegend } from "./GraphLegend.js";
import { Icon } from "../ui/primitives.js";

// The graph is the product's argument: every finding traces back to a document
// somebody can open. Making that argument LAND, rather than look like tangled
// string, is what this component is for.
//
//   1. PATH HIGHLIGHTING. Hovering or selecting a node dims the canvas and
//      lights only that node's evidence chain. This is the interaction the
//      demo turns on — "click the finding, watch it resolve to two PDFs".
//   2. TYPE IS VISIBLE, not inferred. Each node carries a coloured header
//      strip and a spelled-out type. Colour alone never distinguishes them,
//      which matters both for colour-vision deficiency and for a projector.
//   3. DIRECTED, COLOURED EDGES. A curve leaves each node horizontally and
//      arrives with an arrowhead, in the source node's own hue, so a chain
//      reads as one colour resolving into the finding's red.
//   4. BANDED COLUMNS. The left-to-right reading order — document, value,
//      rule, finding — is drawn rather than implied.
//   5. DRAGGABLE NODES, so a reviewer can untangle a dense case themselves.
//
// None of this touches the graph's CONTENTS. Layout and presentation live
// here; nodes and edges arrive from graph_service.py exactly as computed, and
// this file must never add, merge, or relabel one.
const COLUMN_ORDER = ["document", "extracted_value", "business_rule", "finding", "routing"];

// The canvas sizes itself to its contents rather than to a fixed box, and
// then scrolls. A fixed viewBox was the reason the graph was hard to read:
// four columns divided across whatever width the panel happened to be gave
// each column about 150px, the nodes are 214px wide and centred on their
// column, so every node overlapped its neighbours on both sides. Shrinking
// the nodes to fit would have solved the overlap by making the labels
// unreadable, which is the same problem wearing a different hat.
//
// So the width is derived from how many columns there are and the height from
// the busiest column, with a horizontal scroll when that exceeds the panel.
// A dense case gets a wider canvas instead of a tighter one.
const COLUMN_WIDTH = 268;   // node width plus the gutter a bezier needs
const ROW_HEIGHT = 132;     // the tallest node this graph produces, plus air
const HEADER_ROOM = 78;     // space above the first row for the column title
const MIN_CANVAS_H = 480;

const COLUMN_TITLE = {
  document: "Source documents",
  extracted_value: "Extracted values",
  business_rule: "Rule applied",
  finding: "Findings",
  // Where the case goes next. The graph used to stop at the finding, which
  // left it silent on the question a reviewer actually has once they believe
  // the finding.
  routing: "Routing",
};

// What the node's own header says it is. Spelled out rather than a colour
// swatch, because a reader who cannot separate the hues still has to be able
// to read the graph.
const TYPE_LABEL = {
  document: "Document",
  extracted_value: "Extracted",
  business_rule: "Rule",
  finding: "Finding",
  routing: "Routing",
};

// Node type -> the CSS custom property carrying its hue. The mapping is not
// one-to-one with the type names, so it lives here once rather than being
// re-derived with a nested ternary at each of the four places that needs it.
const TYPE_TOKEN = {
  document: "--viz-document",
  extracted_value: "--viz-value",
  business_rule: "--viz-rule",
  finding: "--viz-finding",
  routing: "--viz-routing",
};

function layout(nodes) {
  const byType = {};
  COLUMN_ORDER.forEach((t) => (byType[t] = []));
  nodes.forEach((n) => {
    if (!byType[n.type]) byType[n.type] = [];
    byType[n.type].push(n);
  });

  const columns = COLUMN_ORDER.filter((t) => byType[t] && byType[t].length > 0);
  const busiest = columns.reduce((most, t) => Math.max(most, byType[t].length), 0);

  const width = Math.max(COLUMN_WIDTH * columns.length, 640);
  const height = Math.max(MIN_CANVAS_H, HEADER_ROOM + busiest * ROW_HEIGHT + 40);
  const colWidth = width / columns.length;

  const positioned = {};
  const headers = [];

  columns.forEach((type, colIdx) => {
    const items = byType[type];
    // Centre of this column. Nodes are centred on it, so a column has to be
    // at least as wide as a node — which is what COLUMN_WIDTH guarantees.
    const x = colWidth * (colIdx + 0.5);
    // Rows are inset from the top so a node never collides with its column
    // heading, and spread across what is left. The old formula divided the
    // full height, which put the first node of a one-node column directly
    // behind the title.
    const usable = height - HEADER_ROOM - 30;
    const rowGap = usable / (items.length + 1);
    headers.push({ type, x, width: colWidth });
    items.forEach((n, i) => {
      positioned[n.id] = { x, y: HEADER_ROOM + rowGap * (i + 1) };
    });
  });
  return { positioned, headers, width, height };
}

/** A horizontal-tangent cubic bezier: leaves one node sideways, arrives at the
 *  next the same way, so crossings read as flow instead of noise. */
function edgePath(a, b) {
  const dx = Math.max(48, Math.abs(b.x - a.x) * 0.48);
  return `M ${a.x} ${a.y} C ${a.x + dx} ${a.y}, ${b.x - dx} ${b.y}, ${b.x} ${b.y}`;
}

/** Splits a node's label into the thing and, when it has one, its value.
 *  graph_service puts the figure in `detail`; showing it at body size beside a
 *  bolder label is what makes a number readable across a room. */
function nodeValue(node) {
  if (!node.detail) return null;
  // A detail that leads with a currency or a sign is a figure; anything else
  // is prose and stays in the smaller muted style.
  return /^[₹$€]|^[+-]?[\d,.]+%?$/.test(node.detail.trim()) ? node.detail : null;
}

export function EvidenceGraph({ graph, onSelectNode }) {
  const [scale, setScale] = useState(1);
  const [selectedId, setSelectedId] = useState(null);
  const [hoveredId, setHoveredId] = useState(null);
  const [textFallback, setTextFallback] = useState(false);
  const [dragOffsets, setDragOffsets] = useState({});
  const canvasRef = useRef(null);
  const dragState = useRef(null);

  const { positioned, headers, width: CANVAS_W, height: CANVAS_H } =
    useMemo(() => layout(graph.nodes), [graph]);

  const nodeById = useMemo(() => {
    const map = {};
    graph.nodes.forEach((n) => { map[n.id] = n; });
    return map;
  }, [graph]);

  // Adjacency, built once: what each node connects to in either direction.
  const neighbours = useMemo(() => {
    const map = {};
    graph.edges.forEach((e) => {
      (map[e.source] = map[e.source] || new Set()).add(e.target);
      (map[e.target] = map[e.target] || new Set()).add(e.source);
    });
    return map;
  }, [graph]);

  // The focused node's chain: itself, everything it touches, and everything
  // those touch — two hops, which is exactly the depth of this graph
  // (finding -> value -> document / rule).
  const focusId = hoveredId || selectedId;
  const activeNodes = useMemo(() => {
    if (!focusId) return null;
    const reached = new Set([focusId]);
    (neighbours[focusId] || new Set()).forEach((first) => {
      reached.add(first);
      (neighbours[first] || new Set()).forEach((second) => reached.add(second));
    });
    return reached;
  }, [focusId, neighbours]);

  const positionOf = useCallback((id) => {
    const base = positioned[id];
    if (!base) return null;
    const offset = dragOffsets[id];
    if (!offset) return base;
    return { x: base.x + offset.x, y: base.y + offset.y };
  }, [positioned, dragOffsets]);

  const handleSelect = (node) => {
    setSelectedId(node.id);
    onSelectNode && onSelectNode(node);
  };

  // --- dragging -----------------------------------------------------------
  const onPointerDown = (event, nodeId) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    dragState.current = {
      nodeId,
      startX: event.clientX,
      startY: event.clientY,
      scaleX: CANVAS_W / rect.width,
      scaleY: CANVAS_H / rect.height,
      origin: dragOffsets[nodeId] || { x: 0, y: 0 },
      moved: false,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onPointerMove = (event) => {
    const drag = dragState.current;
    if (!drag) return;
    const dx = (event.clientX - drag.startX) * drag.scaleX / scale;
    const dy = (event.clientY - drag.startY) * drag.scaleY / scale;
    if (Math.abs(dx) > 2 || Math.abs(dy) > 2) drag.moved = true;
    setDragOffsets((prev) => ({
      ...prev,
      [drag.nodeId]: { x: drag.origin.x + dx, y: drag.origin.y + dy },
    }));
  };

  const onPointerUp = (event, node) => {
    const drag = dragState.current;
    dragState.current = null;
    try { event.currentTarget.releasePointerCapture(event.pointerId); } catch { /* already released */ }
    // A drag must not also count as a click, or moving a node opens its drawer.
    if (drag && !drag.moved) handleSelect(node);
  };

  const resetView = () => {
    setScale(1);
    setDragOffsets({});
    setSelectedId(null);
  };

  if (graph.nodes.length === 0) {
    return html`<p class="text-muted">No evidence graph available for this exception.</p>`;
  }

  const dimmed = (id) => activeNodes && !activeNodes.has(id);

  return html`
    <div class="stack gap-12">
      <div class="row gap-8" style=${{ flexWrap: "wrap" }}>
        <${GraphLegend} />
        <div class="row gap-4" style=${{ marginLeft: "auto" }}>
          <button class="btn btn-ghost btn-sm" onClick=${() => setScale((s) => Math.max(0.5, s - 0.15))} aria-label="Zoom out"><${Icon} name="zoomOut" size=${15} /></button>
          <button class="btn btn-ghost btn-sm" onClick=${() => setScale((s) => Math.min(1.8, s + 0.15))} aria-label="Zoom in"><${Icon} name="zoomIn" size=${15} /></button>
          <button class="btn btn-ghost btn-sm" onClick=${resetView} aria-label="Reset view"><${Icon} name="maximize" size=${15} /> Fit<//>
          <button class="btn btn-ghost btn-sm" onClick=${() => setTextFallback((v) => !v)}>${textFallback ? "Show graph" : "Text view"}<//>
        </div>
      </div>

      ${!textFallback ? html`
        <p class="text-muted text-small">
          Hover any node to light up its evidence chain. Click to open its source, drag to rearrange.
        </p>
      ` : null}

      ${textFallback ? html`
        <div class="panel-elevated stack gap-8" style=${{ padding: 16 }}>
          ${graph.nodes.map((n) => html`
            <div key=${n.id} class="text-small">
              <span class="type-dot" style=${{ background: `var(${TYPE_TOKEN[n.type] || "--viz-routing"})` }}></span>
              <strong>[${TYPE_LABEL[n.type] || n.type.replaceAll("_", " ")}]</strong> ${n.label}${n.detail ? ` — ${n.detail}` : ""}
            </div>
          `)}
          <hr class="hairline" />
          ${graph.edges.map((e) => html`
            <div key=${e.id} class="text-muted text-small">
              ${(nodeById[e.source] || {}).label || e.source} → (${e.relationship.replaceAll("_", " ")}) → ${(nodeById[e.target] || {}).label || e.target}
            </div>
          `)}
        </div>
      ` : html`
        <div class="graph-scroll">
          <div class="graph-canvas ${focusId ? "has-focus" : ""}" ref=${canvasRef}
            onPointerMove=${onPointerMove}
            style=${{ width: `${CANVAS_W}px`, height: `${CANVAS_H}px` }}>
            <div style=${{ position: "absolute", inset: 0, transform: `scale(${scale})`, transformOrigin: "center", transition: "transform 0.18s ease" }}>

            ${headers.map((h, index) => html`
              <div key=${`band-${h.type}`} class="graph-column-band ${index % 2 ? "alt" : ""}"
                style=${{
                  left: `${((h.x - h.width / 2) / CANVAS_W) * 100}%`,
                  width: `${(h.width / CANVAS_W) * 100}%`,
                }}></div>
            `)}

            <svg viewBox="0 0 ${CANVAS_W} ${CANVAS_H}" preserveAspectRatio="none"
              style=${{ position: "absolute", inset: 0, width: "100%", height: "100%" }}>
              <defs>
                ${Object.entries(TYPE_TOKEN).map(([type, token]) => html`
                  <marker key=${type} id=${`arrow-${type}`} viewBox="0 0 10 10"
                    refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse">
                    <path d="M 0 1 L 9 5 L 0 9 z" fill=${`var(${token})`} />
                  </marker>
                `)}
              </defs>
              ${graph.edges.map((e) => {
                const a = positionOf(e.source); const b = positionOf(e.target);
                if (!a || !b) return null;
                const sourceType = (nodeById[e.source] || {}).type || "document";
                const active = activeNodes && activeNodes.has(e.source) && activeNodes.has(e.target);
                return html`<path key=${e.id} d=${edgePath(a, b)} fill="none"
                  marker-end=${`url(#arrow-${sourceType})`}
                  class="graph-edge typed-${sourceType} ${activeNodes ? (active ? "active" : "dimmed") : ""}">
                  <title>${e.relationship.replaceAll("_", " ")}</title>
                </path>`;
              })}
            </svg>

            ${headers.map((h) => html`
              <div key=${h.type} class="graph-column-title"
                style=${{ left: `${(h.x / CANVAS_W) * 100}%` }}>${COLUMN_TITLE[h.type] || h.type}</div>
            `)}

            ${graph.nodes.map((n) => {
              const pos = positionOf(n.id);
              if (!pos) return null;
              const value = nodeValue(n);
              return html`
                <div
                  key=${n.id}
                  class="graph-node graph-node-${n.type} ${selectedId === n.id ? "selected" : ""} ${dimmed(n.id) ? "dimmed" : ""}"
                  style=${{ left: `${(pos.x / CANVAS_W) * 100}%`, top: `${(pos.y / CANVAS_H) * 100}%` }}
                  onPointerDown=${(e) => onPointerDown(e, n.id)}
                  onPointerUp=${(e) => onPointerUp(e, n)}
                  onMouseEnter=${() => setHoveredId(n.id)}
                  onMouseLeave=${() => setHoveredId(null)}
                  onFocus=${() => setHoveredId(n.id)}
                  onBlur=${() => setHoveredId(null)}
                  onKeyDown=${(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleSelect(n); } }}
                  tabIndex="0"
                  role="button"
                  aria-label=${`${TYPE_LABEL[n.type] || n.type}: ${n.label}${n.detail ? `, ${n.detail}` : ""}`}
                >
                  <div class="graph-node-head">${TYPE_LABEL[n.type] || n.type.replaceAll("_", " ")}</div>
                  <div class="graph-node-body">
                    ${n.label}
                    ${value
                      ? html`<span class="graph-node-value">${value}</span>`
                      : n.detail ? html`<div class="graph-node-detail">${n.detail}</div>` : null}
                  </div>
                </div>
              `;
              })}
            </div>
          </div>
        </div>
      `}
    </div>
  `;
}
