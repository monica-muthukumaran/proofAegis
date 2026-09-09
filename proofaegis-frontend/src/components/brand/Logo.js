// The ProofAegis mark.
//
// REDESIGNED. The first mark was a shield with a small page floating inside
// it — two separate objects, one containing the other, which is a lot of
// detail to carry at 16px and says "security product that has documents".
//
// This one collapses the two into a single shape: the page IS the shield. A
// document with a folded corner, whose base comes to a protective point. One
// silhouette, readable at favicon size, and it states the actual product
// rather than a category — evidence that defends a decision.
//
// The fold is the tell. It is what stops the silhouette reading as a generic
// shield, and it is the only piece of the mark that costs nothing at small
// sizes because it sits on the outline rather than inside it.
import { html } from "../../lib.js";

export function Logo({ size = 32, withWordmark = false, tagline = null, id = "pa" }) {
  // Gradient ids must be unique per instance: two <defs> sharing an id on one
  // page means the second mark silently renders with the first one's fill.
  const gid = `${id}-grad`;

  const mark = html`
    <svg class="brand-mark" width=${size} height=${size} viewBox="0 0 24 24"
      fill="none" role="img" aria-label="ProofAegis">
      <defs>
        <linearGradient id=${gid} x1="4" y1="2" x2="20" y2="23" gradientUnits="userSpaceOnUse">
          <stop stop-color="var(--brand-grad-a)" />
          <stop offset="1" stop-color="var(--brand-grad-b)" />
        </linearGradient>
      </defs>

      <!-- The page-shield: square shoulders, folded top-right corner, and a
           base that tapers to a point instead of closing flat. -->
      <path
        d="M4 2.6 H13.4 L20 9.2 V13.4 C20 18.4 16.4 21.6 12 23.1 C7.6 21.6 4 18.4 4 13.4 Z"
        fill=${`url(#${gid})`} />

      <!-- The fold. Lighter rather than white so the mark stays one object. -->
      <path d="M13.4 2.6 V9.2 H20 Z" fill="#fff" fill-opacity=".38" />

      <!-- Two ruled lines: this is a record, not a badge. -->
      <path d="M8 12.9 H15.4 M8 16.1 H12.4" stroke="#fff" stroke-width="1.7"
        stroke-linecap="round" opacity=".95" />
    </svg>
  `;

  if (!withWordmark) return mark;

  return html`
    <div class="brand-lockup">
      ${mark}
      <div style=${{ minWidth: 0 }}>
        <div class="brand-name" style=${{ fontSize: Math.round(size * 0.47) }}>ProofAegis</div>
        ${tagline ? html`<div class="brand-tag">${tagline}</div>` : null}
      </div>
    </div>
  `;
}

// The uppercase brand line used above a hero or a form title.
export function BrandEyebrow({ children = "ProofAegis", size = 16 }) {
  return html`
    <span class="brand-eyebrow">
      <${Logo} size=${size} id="eyebrow" />
      ${children}
    </span>
  `;
}
