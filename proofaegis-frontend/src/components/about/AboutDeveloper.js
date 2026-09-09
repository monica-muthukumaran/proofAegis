// AboutDeveloper.js — who built this.
//
// Deliberately quiet. It sits as one line of small muted text in the entry
// footer and under the sidebar workspace card, and it opens a dialog only
// when someone asks for it. A product that is making claims about other
// people's invoices should not be shouting about its author on the same
// screen, but a reviewer looking at a portfolio piece should never have to
// dig through a README to find out who to contact.
import { html, React, useState } from "../../lib.js";
import { Modal, Icon } from "../ui/primitives.js";

// ---------------------------------------------------------------------------
// EDIT HERE. This is the whole of the personal detail in the app.
// ---------------------------------------------------------------------------
export const DEVELOPER = {
  name: "Monica Muthukumaran",

  // On the wording: "Agentic AI Explorer" was the first draft, and the
  // hesitation behind it was the right instinct — "Explorer" is vague enough
  // that a reader cannot tell whether it means shipped-in-production or
  // read-a-blog-post, and vagueness in a claim about your own experience
  // reads worse than the plain version.
  //
  // "building agentic AI" is the honest and stronger phrasing: it is present
  // tense, it is demonstrably true (this app is the evidence), and it claims
  // exactly what is true without implying professional tenure. Anyone
  // evaluating it can click through to a working multi-agent system, which is
  // a better credential than an adjective.
  //
  // Other honest options, if a different register suits better:
  //   "Full-stack web developer · learning agentic AI in the open"
  //   "Full-stack web developer. Currently building agentic systems."
  //   "Full-stack web developer + Agentic AI Explorer"   (the original)
  title: "Full-stack web developer, building agentic AI",

  email: "monicamuthukumaran7@gmail.com",

  // A placeholder portrait ships at this path so nothing is ever broken or
  // empty. TO REPLACE IT, either:
  //   * overwrite public/developer.svg with your own file, or
  //   * drop e.g. public/developer.jpg in and change this string to
  //     "/developer.jpg".
  // If the file is ever missing the component falls back to the initials
  // below rather than rendering a broken image.
  photo: "/developer.svg",
  initials: "MM",

  // One line about the project, in the first person. Kept short: the dialog
  // is a business card, not a CV.
  note: "ProofAegis is a personal project — an evidence-led exception "
    + "workflow for accounts payable, where every figure on screen traces "
    + "back to the document page it came from.",
};

function Portrait({ size = 84 }) {
  const [failed, setFailed] = useState(false);

  // Note there is no loading="lazy" here, and that is deliberate. This image
  // only exists inside a dialog the user has just chosen to open, so it is on
  // screen the instant it is in the DOM: deferring it buys nothing and costs a
  // visible pop-in on a card whose entire content is one face and three lines.
  // (It also does not reliably un-defer inside a freshly inserted fixed-position
  // overlay, which is how this was caught — the portrait simply never loaded.)
  // Lazy loading is for images a reader may never scroll to.
  if (DEVELOPER.photo && !failed) {
    return html`
      <img
        class="dev-portrait"
        src=${DEVELOPER.photo}
        alt=${`Portrait of ${DEVELOPER.name}`}
        width=${size}
        height=${size}
        decoding="async"
        onError=${() => setFailed(true)}
      />
    `;
  }

  // The fallback is a real design rather than a grey box, so a missing file
  // degrades to something that still looks deliberate.
  return html`
    <div class="dev-portrait dev-portrait-initials" style=${{ width: size, height: size }}
      role="img" aria-label=${`${DEVELOPER.name}, no portrait on file`}>
      ${DEVELOPER.initials}
    </div>
  `;
}

/**
 * The trigger. Renders as one line of small, muted text.
 *
 * @param {string} className extra classes for placement by the caller
 * @param {string} label     override the trigger wording
 */
export function AboutDeveloperLink({ className = "", label = "About the developer" }) {
  const [open, setOpen] = useState(false);

  return html`
    <${React.Fragment}>
      <button
        type="button"
        class=${`about-dev-trigger ${className}`}
        onClick=${() => setOpen(true)}
        aria-haspopup="dialog">
        ${label}
      </button>

      <${Modal} open=${open} onClose=${() => setOpen(false)} label="About the developer">
        <div class="dev-card">
          <button class="btn btn-ghost btn-sm dev-close" onClick=${() => setOpen(false)}
            aria-label="Close">
            <${Icon} name="close" size=${16} />
          </button>

          <div class="dev-head">
            <${Portrait} size=${84} />
            <div class="stack gap-4" style=${{ minWidth: 0 }}>
              <h3 class="dev-name">${DEVELOPER.name}</h3>
              <p class="dev-title">${DEVELOPER.title}</p>
            </div>
          </div>

          <p class="dev-note">${DEVELOPER.note}</p>

          <div class="dev-contact">
            <span class="dev-contact-label">Contact</span>
            <a class="dev-contact-value mono" href=${`mailto:${DEVELOPER.email}`}>
              ${DEVELOPER.email}
            </a>
          </div>
        </div>
      <//>
    <//>
  `;
}
