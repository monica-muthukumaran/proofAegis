// The ProofAegis mark.
//
// The product had no logo — the sidebar, the entry screen and the sign-in
// card all used the generic `shield` icon from the feather set, which is the
// same glyph the ErrorState uses. A product whose front door wears a stock
// icon reads as a template.
//
// The mark is a shield (the "aegis") whose interior is a page with a rule
// struck through it and a mark of assent beside it — the product's actual
// claim, that a document was checked and the check is recorded. It is drawn
// on a 24-unit grid so it sits on the same optical size as the icon set it
// appears beside.
import { html } from "../../lib.js";

export function Logo({ size = 32, withWordmark = false, tagline = null, id = "pa" }) {
  // Gradient ids must be unique per instance: two <defs> sharing an id on one
  // page means the second mark silently renders with the first one's fill.
  const gid = `${id}-grad`;

  const mark = html`
    <svg class="brand-mark" width=${size} height=${size} viewBox="0 0 24 24"
      fill="none" role="img" aria-label="ProofAegis">
      <defs>
        <linearGradient id=${gid} x1="4" y1="1" x2="20" y2="23" gradientUnits="userSpaceOnUse">
          <stop stop-color="var(--brand-grad-a)" />
          <stop offset="1" stop-color="var(--brand-grad-b)" />
        </linearGradient>
      </defs>
      <path d="M12 1.6 3.4 4.7v6.6c0 5.6 4.3 9.4 8.6 11.1 4.3-1.7 8.6-5.5 8.6-11.1V4.7Z"
        fill=${`url(#${gid})`} />
      <path d="M9.1 7.6h4.4l2.4 2.4v6.4H9.1Z" fill="#fff" fill-opacity=".92" />
      <path d="M13.5 7.6v2.4h2.4" fill="#fff" fill-opacity=".55" />
      <path d="M10.6 12.4h3.8M10.6 14.5h2.4" stroke="var(--brand-grad-a)"
        stroke-width="1.1" stroke-linecap="round" opacity=".75" />
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
