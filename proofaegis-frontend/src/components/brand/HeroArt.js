// The entry-screen illustration.
//
// It is not decoration standing in for a screenshot. It draws the product's
// one claim, in the order the product actually performs it:
//
//   documents arrive  ->  values are pulled out of them  ->  a rule is
//   applied  ->  a finding falls out, carrying the money and pointing back
//   at the page it came from.
//
// The animation exists to make that ORDER readable. Each stage pops in on a
// stagger and each connector draws itself, so watching it once tells you the
// direction of the argument — which a static diagram of five boxes does not.
// It plays through once (~1.6s) and then holds; only the finding keeps a slow
// pulse, because it is the thing the product wants you to look at.
//
// Every colour is a token, and the ones that carry meaning are the SAME
// tokens the real evidence graph uses: --viz-document for a page,
// --viz-value for something extracted, --viz-rule for a policy, --exception
// for a finding. The illustration and the product agree, so the vocabulary a
// visitor learns here still holds once they are inside.
import { html } from "../../lib.js";

// A page in the stack. `lines` is how many ruled lines to draw on it.
//
// The nesting is load-bearing, not tidiness. `.art-piece` animates `transform`
// in CSS, and a CSS transform BEATS an SVG `transform` presentation attribute
// on the same element — with `fill-mode:both` the animation's final
// `transform:none` then wins permanently, which collapsed every piece of this
// illustration onto the origin. Position goes on an outer <g> as an attribute;
// the inner <g> owns the animation and nothing else.
function Page({ x, y, rotate, lines = 0, i, opacity = 1 }) {
  return html`
    <g transform=${`translate(${x} ${y}) rotate(${rotate})`}>
    <g class="art-piece" style=${{ "--i": i }} opacity=${opacity}>
      <rect x="3" y="4" width="104" height="132" rx="8" class="art-shadow" />
      <rect width="104" height="132" rx="8" class="art-surface" />
      <rect width="104" height="132" rx="8" class="art-line" />
      <rect x="0" y="0" width="104" height="6" rx="3" class="art-doc" />
      ${lines ? html`
        <g class="art-muted" opacity=".5">
          ${Array.from({ length: lines }, (_, n) => html`
            <rect key=${n} x="14" y=${26 + n * 15} width=${n % 3 === 2 ? 42 : 76} height="5" rx="2.5" />
          `)}
        </g>
      ` : null}
    </g>
    </g>
  `;
}

// A rounded chip carrying a label and a figure. Same nesting rule as Page.
function Chip({ x, y, w = 132, h = 54, i, hue, label, value, dashed = false }) {
  return html`
    <g transform=${`translate(${x} ${y})`}>
    <g class="art-piece" style=${{ "--i": i }}>
      <rect x="2" y="3" width=${w} height=${h} rx="10" class="art-shadow" />
      <rect width=${w} height=${h} rx="10" class="art-surface" />
      <rect width=${w} height=${h} rx="10" fill="none" stroke=${hue} stroke-width="1.6"
        stroke-dasharray=${dashed ? "5 4" : "none"} />
      <rect x="0" y="0" width="4" height=${h} rx="2" fill=${hue} />
      <text x="15" y="21" font-size="9.5" font-weight="700" letter-spacing="1.1"
        fill=${hue} font-family="var(--font)">${label}</text>
      <text x="15" y="40" font-size="15" font-weight="700" class="art-ink"
        font-family="var(--font)" style=${{ fontVariantNumeric: "tabular-nums" }}>${value}</text>
    </g>
    </g>
  `;
}

// A connector. `len` must be >= the path's real length for the draw-on
// animation; overestimating just means the dash starts further offscreen.
function Wire({ d, i, len = 260, cls = "art-brand-stroke" }) {
  return html`<path d=${d} class=${`${cls} art-path`} style=${{ "--i": i, "--len": len }} />`;
}

export function HeroArt() {
  return html`
    <svg class="hero-art" viewBox="0 96 560 300" fill="none"
      role="img"
      aria-label="Three source documents feed extracted values into a matching rule, which produces a priced exception traced back to page two.">

      <!-- Stage 1 — the documents -->
      <g class="art-float" style=${{ "--i": 0 }}>
        <${Page} x=${16} y=${168} rotate=${-9} i=${0} opacity=${0.55} />
        <${Page} x=${40} y=${144} rotate=${-4} i=${1} opacity=${0.8} />
        <${Page} x=${66} y=${120} rotate=${2} i=${2} lines=${6} />
      </g>
      <text x="104" y="330" text-anchor="middle" font-size="10" font-weight="700"
        letter-spacing="1.2" class="art-muted" font-family="var(--font)">SOURCE PAGES</text>

      <!-- Stage 2 — what was pulled out of them -->
      <${Wire} i=${2} len=${190}
        d="M188 176 C 232 176 232 108 268 108" />
      <${Wire} i=${3} len=${190}
        d="M188 196 C 232 196 232 210 268 210" />

      <${Chip} x=${268} y=${80}  i=${3} hue="var(--viz-value)" label="INVOICE" value="₹4,86,200" />
      <${Chip} x=${268} y=${182} i=${4} hue="var(--viz-value)" label="PO" value="₹4,52,000" />

      <!-- Stage 3 — the rule that judged them -->
      <${Chip} x=${268} y=${284} i=${5} hue="var(--viz-rule)" dashed=${true}
        label="TOLERANCE" value="± 2.0%" />

      <!-- Stage 4 — the finding -->
      <${Wire} i=${5} len=${180} d="M400 107 C 442 107 442 168 466 178" cls="art-finding-stroke" />
      <${Wire} i=${6} len=${180} d="M400 209 C 442 209 442 190 466 186" cls="art-finding-stroke" />
      <${Wire} i=${7} len=${180} d="M400 311 C 448 311 448 210 466 196" cls="art-finding-stroke" />

      <g transform="translate(452 118)">
      <g class="art-piece" style=${{ "--i": 8 }}>
        <rect x="3" y="5" width="96" height="150" rx="12" class="art-shadow" />
        <rect width="96" height="150" rx="12" class="art-surface" />
        <rect width="96" height="150" rx="12" fill="none" class="art-finding-stroke" />
        <circle cx="48" cy="40" r="17" fill="var(--exception-soft)" class="art-ping" />
        <path d="M48 31v12M48 49v.5" stroke="var(--exception)" stroke-width="2.6"
          stroke-linecap="round" />
        <text x="48" y="82" text-anchor="middle" font-size="9.5" font-weight="700"
          letter-spacing="1" class="art-finding" font-family="var(--font)">OVERBILLED</text>
        <text x="48" y="104" text-anchor="middle" font-size="16" font-weight="700"
          class="art-finding" font-family="var(--font)"
          style=${{ fontVariantNumeric: "tabular-nums" }}>₹34,200</text>
        <line x1="18" y1="118" x2="78" y2="118" stroke="var(--line)" stroke-width="1" />
        <text x="48" y="136" text-anchor="middle" font-size="9" font-weight="600"
          class="art-muted" font-family="var(--font)">traced to page 2</text>
      </g>
      </g>

      <!-- The trace back. This is the line that matters: the finding points
           at the page it came from, which is the whole argument. -->
      <${Wire} i=${9} len=${420} cls="art-brand-stroke"
        d="M500 274 C 500 348 300 356 150 320 C 118 312 104 306 100 292" />
      <text x="300" y="374" text-anchor="middle" font-size="10" font-weight="700"
        letter-spacing="1.1" fill="var(--brand)" font-family="var(--font)"
        class="art-piece" style=${{ "--i": 10 }}>EVERY FINDING TRACES BACK</text>
    </svg>
  `;
}

// A smaller mark used on empty states — the same vocabulary, one document and
// one verdict, sized for a 180px slot.
export function SpotArt({ tone = "empty" }) {
  const hue = tone === "empty" ? "var(--viz-value)" : "var(--exception)";
  return html`
    <svg class="spot-art" viewBox="0 0 180 150" fill="none" aria-hidden="true">
      <g transform="translate(30 14) rotate(-5)"><g class="art-piece" style=${{ "--i": 0 }}>
        <rect x="3" y="4" width="84" height="108" rx="8" class="art-shadow" />
        <rect width="84" height="108" rx="8" class="art-surface" />
        <rect width="84" height="108" rx="8" class="art-line" />
        <rect width="84" height="5" rx="2.5" class="art-doc" />
        <g class="art-muted" opacity=".45">
          ${[0, 1, 2, 3].map((n) => html`
            <rect key=${n} x="12" y=${24 + n * 16} width=${n === 3 ? 34 : 60} height="5" rx="2.5" />
          `)}
        </g>
      </g></g>
      <g transform="translate(104 78)"><g class="art-piece" style=${{ "--i": 2 }}>
        <circle cx="24" cy="24" r="24" fill=${hue} opacity=".14" />
        <circle cx="24" cy="24" r="24" fill="none" stroke=${hue} stroke-width="1.6" />
        ${tone === "empty"
          ? html`<path d="M15 24.5l6.5 6.5L34 18.5" stroke=${hue} stroke-width="2.6"
              stroke-linecap="round" stroke-linejoin="round" fill="none" />`
          : html`<path d="M24 14v13M24 33v.5" stroke=${hue} stroke-width="2.8"
              stroke-linecap="round" fill="none" />`}
      </g></g>
    </svg>
  `;
}
