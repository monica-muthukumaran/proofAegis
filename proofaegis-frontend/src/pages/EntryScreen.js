import { html } from "../lib.js";
import { Icon } from "../components/ui/primitives.js";

export function EntryScreen({ onStartTour, onSignIn, onSignUp }) {
  return html`
    <div class="centered-screen">
      <div style=${{ width: "100%", maxWidth: 880 }} class="stack gap-24">
        <div class="stack gap-12" style=${{ textAlign: "center", alignItems: "center" }}>
          <div class="row gap-8" style=${{ color: "var(--accent)" }}>
            <${Icon} name="shield" size=${20} />
            <span class="text-small" style=${{ fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase" }}>ProofAegis</span>
          </div>
          <h1 class="text-page-title" style=${{ maxWidth: 700 }}>What passes is scarier than what fails.</h1>
          <p class="text-secondary" style=${{ maxWidth: 560, fontSize: 16 }}>
            Most AP automation decides what to approve. ProofAegis investigates what failed — and what shouldn't have passed. Every finding traces to a page you can open.
          </p>
        </div>

        <div class="row gap-16" style=${{ alignItems: "stretch", flexWrap: "wrap", justifyContent: "center" }}>
          <div class="panel stack gap-16" style=${{ padding: 28, flex: "1 1 360px", maxWidth: 400 }}>
            <div class="panel-elevated" style=${{ width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 12, color: "var(--accent)" }}>
              <${Icon} name="play" size=${20} />
            </div>
            <div class="stack gap-8">
              <h3 class="text-section-title">Guided Tour</h3>
              <p class="text-secondary">Explore ProofAegis with a prepared invoice exception and sample documents.</p>
            </div>
            <button class="btn btn-primary btn-block" onClick=${onStartTour}>Start guided tour</button>
            <ul class="stack gap-8" style=${{ listStyle: "none", padding: 0, margin: 0 }}>
              ${[
                "No login required.",
                "Uses synthetic data.",
                "Takes approximately two minutes.",
                "Includes evidence graph and source citations.",
              ].map((t) => html`
                <li class="row gap-8 text-secondary text-small" key=${t}>
                  <${Icon} name="check" size=${14} style=${{ color: "var(--verified)" }} />${t}
                </li>
              `)}
            </ul>
          </div>

          <div class="panel stack gap-16" style=${{ padding: 28, flex: "1 1 360px", maxWidth: 400 }}>
            <div class="panel-elevated" style=${{ width: 44, height: 44, display: "flex", alignItems: "center", justifyContent: "center", borderRadius: 12, color: "var(--accent-2)" }}>
              <${Icon} name="building" size=${20} />
            </div>
            <div class="stack gap-8">
              <h3 class="text-section-title">Sign In</h3>
              <p class="text-secondary">Open your workspace to review, upload, and resolve invoice exceptions.</p>
            </div>
            <button class="btn btn-secondary btn-block" onClick=${onSignIn}>Sign in</button>
            <button class="btn btn-ghost btn-block" onClick=${onSignUp}>Create an account</button>
            <p class="text-muted text-small">Uses a demo workspace in this build — see the sign-in screen for demo credentials.</p>
          </div>
        </div>

        <p class="text-muted text-small" style=${{ textAlign: "center" }}>Demo data is synthetic and not for financial processing.</p>
      </div>
    </div>
  `;
}
