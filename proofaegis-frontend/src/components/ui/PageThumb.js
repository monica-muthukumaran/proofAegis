// Document page thumbnails.
//
// The product's claim is that every finding traces to a page you can open.
// Until now the only way to see a page was to open a modal — so the claim was
// asserted in prose on the entry screen and then never shown again. A
// thumbnail puts the page beside the finding: its shape, its header block,
// and a rust rule marking the line the finding sits on.
//
// DRAWN, NOT FETCHED, BY DEFAULT
//
// These are generated from the document's own metadata — kind, page count,
// and which line the finding cites — so a case with no stored render still
// shows a correct page shape instead of a broken image or a grey box. When a
// real render exists (`src`), it replaces the drawing and the drawing becomes
// the loading and error state for it. That ordering matters in an AP tool: a
// thumbnail that fails to load must not leave a hole where evidence should
// be.
//
// Nothing here invents content. The lines are ruled placeholders at fixed
// positions, never sampled text — a thumbnail that rendered plausible-looking
// figures would be a fabricated document, which is exactly the thing this
// product exists to catch.
import { html, useState } from "../../lib.js";

const KIND_HUE = {
  invoice: "var(--viz-document)",
  purchase_order: "var(--viz-rule)",
  goods_receipt: "var(--viz-value)",
  contract: "var(--muted)",
  default: "var(--viz-document)",
};

const KIND_LABEL = {
  invoice: "INV",
  purchase_order: "PO",
  goods_receipt: "GRN",
  contract: "DOC",
};

// Ruled lines at fixed fractions of the page height. Two short lines and a
// block, which is the silhouette of almost any commercial document.
const RULES = [0.30, 0.38, 0.46, 0.58, 0.66, 0.74];

/**
 * @param {string}  kind      invoice | purchase_order | goods_receipt | contract
 * @param {number}  width     rendered width in px; height follows A4 ratio
 * @param {?string} src       URL of a real page render, when one exists
 * @param {?number} flagAt    0-1 down the page — where the cited line sits.
 *                            Draws the rust rule. Omit for no flag.
 * @param {?string} label     overrides the corner tag
 * @param {?func}   onOpen    makes the thumbnail a button
 * @param {?string} alt       accessible name; required when onOpen is set
 */
export function PageThumb({
  kind = "invoice",
  width = 54,
  src = null,
  flagAt = null,
  label = null,
  onOpen = null,
  alt = null,
}) {
  const [failed, setFailed] = useState(false);
  const height = Math.round(width * 1.414); // A4
  const hue = KIND_HUE[kind] || KIND_HUE.default;
  const tag = label || KIND_LABEL[kind] || "DOC";

  const showImage = src && !failed;

  const inner = html`
    <div class="page-thumb" style=${{ width, height }}>
      ${showImage
        ? html`<img src=${src} alt="" loading="lazy" decoding="async"
            onError=${() => setFailed(true)} />`
        : html`
          <svg viewBox="0 0 100 141" fill="none" aria-hidden="true"
            preserveAspectRatio="xMidYMid slice">
            <rect width="100" height="141" fill="var(--surface)" />
            <rect width="100" height="7" fill=${hue} />
            <rect x="10" y="16" width="34" height="8" rx="2" fill=${hue} opacity=".28" />
            <rect x="60" y="17" width="30" height="5" rx="2.5" fill="var(--muted)" opacity=".3" />
            <g fill="var(--muted)" opacity=".26">
              ${RULES.map((r, n) => html`
                <rect key=${n} x="10" y=${r * 141} width=${n % 3 === 2 ? 44 : 80} height="4" rx="2" />
              `)}
            </g>
            <rect x="10" y="118" width="26" height="4" rx="2" fill="var(--muted)" opacity=".22" />
            <rect x="62" y="115" width="28" height="9" rx="2" fill=${hue} opacity=".2" />
          </svg>
        `}
      ${flagAt != null ? html`
        <div class="page-thumb-flag" style=${{ top: `${Math.min(0.93, Math.max(0.06, flagAt)) * 100}%` }}></div>
      ` : null}
      <span style=${{
        position: "absolute", left: 3, bottom: 3,
        padding: "1px 4px", borderRadius: 3,
        background: "var(--surface)", border: "1px solid var(--line)",
        color: hue, fontSize: 7.5, fontWeight: 700, letterSpacing: ".05em",
        lineHeight: 1.4,
      }}>${tag}</span>
    </div>
  `;

  if (!onOpen) return inner;

  return html`
    <button type="button" class="page-thumb-btn" onClick=${onOpen}
      aria-label=${alt || `Open ${tag} source page`} title=${alt || `Open ${tag} source page`}>
      ${inner}
    </button>
  `;
}

/**
 * Several pages, fanned. Renders the front page as a real thumbnail and the
 * rest as the two card edges behind it, so the count reads without drawing
 * five full miniatures.
 */
export function PageThumbStack({ documents = [], width = 54, onOpen = null }) {
  if (!documents.length) return null;
  const [front, ...rest] = documents;
  return html`
    <div class="row gap-8" style=${{ alignItems: "center" }}>
      <span class=${rest.length ? "thumb-stack" : ""}>
        <${PageThumb}
          kind=${front.kind || front.document_type}
          width=${width}
          src=${front.thumbnail_url || null}
          flagAt=${front.flag_at ?? null}
          onOpen=${onOpen ? () => onOpen(front) : null}
          alt=${front.filename ? `Open ${front.filename}` : null}
        />
      </span>
      ${rest.length ? html`
        <span class="text-muted text-small">+${rest.length}</span>
      ` : null}
    </div>
  `;
}
