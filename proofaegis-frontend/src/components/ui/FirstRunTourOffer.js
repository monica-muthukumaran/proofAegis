// FirstRunTourOffer.js — a one-line offer of the guided tour, shown once.
//
// The tour is where ProofAegis actually explains itself: ten steps over the
// real UI covering documents, extraction, matching, the evidence graph,
// citations, the draft, and the audit trail. Before this, a signed-in
// newcomer met it only as one button among several on a dense dashboard, and
// most would never press it — so the product's own explanation went unread
// and the app opened straight into undefined jargon.
//
// Deliberately a strip, not a modal: it should be impossible to miss and
// trivial to dismiss. Dismissal is remembered per browser, and both the
// storage read and write are guarded, so a private window degrades to
// "offer it again" rather than throwing.
import { html, useState } from "../../lib.js";
import { Icon } from "./primitives.js";
import { hasSeenTour, markTourSeen } from "../../lib/tourState.js";

export function FirstRunTourOffer({ onStartTour }) {
  const [dismissed, setDismissed] = useState(() => hasSeenTour());

  if (dismissed) return null;

  const dismiss = () => {
    markTourSeen();
    setDismissed(true);
  };

  return html`
    <div class="panel row gap-16"
      style=${{ padding: "14px 18px", flexWrap: "wrap", borderColor: "var(--accent)" }}
      role="region" aria-label="Guided tour offer">
      <div style=${{ color: "var(--accent)", flex: "none" }}><${Icon} name="play" size=${18} /></div>
      <div class="stack gap-2" style=${{ flex: 1, minWidth: 220 }}>
        <span style=${{ fontWeight: 700 }}>New to ProofAegis? Take the two-minute walkthrough.</span>
        <span class="text-muted text-small">
          It follows one blocked invoice from its source documents to a cited resolution draft,
          so the rest of this screen makes sense.
        </span>
      </div>
      <button class="btn btn-primary btn-sm" onClick=${() => { markTourSeen(); onStartTour(); }}>
        Start walkthrough
      </button>
      <button class="btn btn-ghost btn-sm" onClick=${dismiss} aria-label="Dismiss the guided tour offer">
        Not now
      </button>
    </div>
  `;
}
