import { html, useState } from "../lib.js";
import { Icon } from "../components/ui/primitives.js";
import { Logo } from "../components/brand/Logo.js";
import { HeroArt } from "../components/brand/HeroArt.js";
import { useReveal } from "../lib/useReveal.js";
import { useAuth } from "../services/AuthContext.js";

// The three claims under the hero. Kept to facts the product can actually
// demonstrate two clicks later — a landing page that promises something the
// app does not show is the fastest way to lose a reviewer.
const PROOF_POINTS = [
  {
    icon: "layers",
    title: "Cross-case checks",
    body: "Duplicate billing and split orders a per-invoice system cannot see, because it only ever looks at one invoice.",
  },
  {
    icon: "file",
    title: "Traced to the page",
    body: "Every figure carries the document and the line it came from. Open the page and read it yourself.",
  },
  {
    icon: "history",
    title: "The whole argument, recorded",
    body: "What the model said, what the code computed, and which one was used — kept for the audit, not summarised away.",
  },
];

export function EntryScreen({ onStartTour, onSignIn, onSignUp, onSignedIn }) {
  // One click into the real workspace. Previously the only ways past this
  // screen were the tour and a password form, and in a live Firebase build
  // the sign-in screen offered no demo path at all — so a first-time visitor
  // with no account could not reach the product, only the tour of it.
  const { continueAsDemo, demoAvailable, loading } = useAuth();
  const [entering, setEntering] = useState(false);
  const proofRef = useReveal({ stagger: 70 });

  const handleEnterDemo = async () => {
    setEntering(true);
    const result = await continueAsDemo();
    setEntering(false);
    if (result.ok && onSignedIn) onSignedIn();
    else if (!result.ok) onSignIn();
  };

  return html`
    <div class="ambient grain" style=${{ minHeight: "100dvh", background: "var(--bg)" }}>
      <div style=${{ maxWidth: 1180, margin: "0 auto", padding: "clamp(20px,4vw,40px) clamp(16px,4vw,40px) 72px" }}>

        <header class="row" style=${{ justifyContent: "space-between", marginBottom: "clamp(32px,6vw,72px)" }}>
          <${Logo} size=${34} withWordmark=${true} />
          <div class="row gap-8">
            <button class="btn btn-ghost btn-sm" onClick=${onSignIn}>Sign in</button>
            <button class="btn btn-secondary btn-sm" onClick=${onSignUp}>Create account</button>
          </div>
        </header>

        <section class="hero-grid" style=${{ marginBottom: "clamp(48px,8vw,96px)" }}>
          <div class="stack gap-24">
            <span class="brand-eyebrow">Evidence-led exception management</span>
            <h1 class="hero-title">What passes is scarier than what fails.</h1>
            <p class="hero-sub">
              Most AP automation decides what to approve. ProofAegis investigates what
              failed — and what shouldn't have passed. Every finding traces to a page
              you can open.
            </p>

            <div class="row gap-12" style=${{ flexWrap: "wrap" }}>
              ${demoAvailable ? html`
                <button class="btn btn-primary" onClick=${handleEnterDemo} disabled=${entering || loading}>
                  ${entering
                    ? html`<span class="row gap-8"><span class="spinner"></span>Opening workspace…</span>`
                    : html`<span class="row gap-8">Open the demo workspace<${Icon} name="arrowRight" size=${16} className="icon-shift" /></span>`}
                </button>
              ` : null}
              <button class=${`btn ${demoAvailable ? "btn-secondary" : "btn-primary"}`} onClick=${onStartTour}>
                <${Icon} name="play" size=${15} /> Take the two-minute tour
              </button>
            </div>

            <p class="text-muted text-small" style=${{ display: "flex", alignItems: "center", gap: 7 }}>
              <${Icon} name="check" size=${14} style=${{ color: "var(--verified)" }} />
              ${demoAvailable
                ? "No sign-up. Synthetic data throughout."
                : "No login required for the tour. Synthetic data throughout."}
            </p>
          </div>

          <${HeroArt} />
        </section>

        <section ref=${proofRef} class="stack gap-16"
          style=${{ display: "grid", gridTemplateColumns: "repeat(auto-fit,minmax(260px,1fr))", gap: 16, marginBottom: "clamp(40px,6vw,72px)" }}>
          ${PROOF_POINTS.map((p) => html`
            <div class="panel stack gap-12" key=${p.title} style=${{ padding: 24 }}>
              <div style=${{
                width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center",
                borderRadius: 11, color: "var(--brand)", background: "var(--brand-soft)",
                border: "1px solid var(--brand-line)",
              }}>
                <${Icon} name=${p.icon} size=${19} />
              </div>
              <h3 class="text-section-title">${p.title}</h3>
              <p class="text-secondary" style=${{ margin: 0 }}>${p.body}</p>
            </div>
          `)}
        </section>

        <section class="row gap-16" style=${{ alignItems: "stretch", flexWrap: "wrap", justifyContent: "center" }}>
          <div class="panel panel-interactive stack gap-16" style=${{ padding: 28, flex: "1 1 340px", maxWidth: 420 }}
            onClick=${onStartTour}>
            <div style=${{
              width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center",
              borderRadius: 12, color: "var(--brand)", background: "var(--brand-soft)",
              border: "1px solid var(--brand-line)",
            }}>
              <${Icon} name="play" size=${20} />
            </div>
            <div class="stack gap-8">
              <h3 class="text-section-title">Guided tour</h3>
              <p class="text-secondary">Walk one blocked invoice from its source documents to a cited resolution draft.</p>
            </div>
            <button class="btn btn-primary btn-block" onClick=${onStartTour}>
              Start guided tour <${Icon} name="arrowRight" size=${15} className="icon-shift" />
            </button>
            <ul class="stack gap-8" style=${{ listStyle: "none", padding: 0, margin: 0 }}>
              ${[
                "No login required.",
                "Uses synthetic data.",
                "Takes approximately two minutes.",
                "Includes evidence graph and source citations.",
              ].map((t) => html`
                <li class="row gap-8 text-secondary text-small" key=${t}>
                  <${Icon} name="check" size=${14} style=${{ color: "var(--verified)", flex: "none" }} />${t}
                </li>
              `)}
            </ul>
          </div>

          <div class="panel stack gap-16" style=${{ padding: 28, flex: "1 1 340px", maxWidth: 420 }}>
            <div style=${{
              width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center",
              borderRadius: 12, color: "var(--accent-2)", background: "var(--panel-elevated)",
              border: "1px solid var(--line)",
            }}>
              <${Icon} name="building" size=${20} />
            </div>
            <div class="stack gap-8">
              <h3 class="text-section-title">Your workspace</h3>
              <p class="text-secondary">Open your workspace to review, upload, and resolve invoice exceptions.</p>
            </div>
            ${demoAvailable ? html`
              <button class="btn btn-primary btn-block" onClick=${handleEnterDemo} disabled=${entering || loading}>
                ${entering ? html`<span class="row gap-8"><span class="spinner"></span>Opening workspace…</span>` : "Open the demo workspace"}
              </button>
            ` : null}
            <button class="btn btn-secondary btn-block" onClick=${onSignIn}>Sign in</button>
            <button class="btn btn-ghost btn-block" onClick=${onSignUp}>Create an account</button>
            <p class="text-muted text-small">
              ${demoAvailable
                ? "The demo workspace signs in to a real account holding synthetic data. No sign-up needed."
                : "Sign in to open your workspace."}
            </p>
          </div>
        </section>

        <p class="text-muted text-small" style=${{ textAlign: "center", marginTop: 40 }}>
          Demo data is synthetic and not for financial processing.
        </p>
      </div>
    </div>
  `;
}
