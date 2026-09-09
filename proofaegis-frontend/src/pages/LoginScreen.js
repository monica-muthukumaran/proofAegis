import { html, useState } from "../lib.js";
import { useAuth } from "../services/AuthContext.js";
import { Icon } from "../components/ui/primitives.js";
import { Logo } from "../components/brand/Logo.js";
import { TopNav } from "../components/layout/TopNav.js";

export function LoginScreen({ onBackToTour, onSignedIn, onCreateAccount, onHome }) {
  const { signIn, continueAsDemo, resetPassword, loading, error, demoCredentials, demoAvailable, isFirebaseMode } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [localError, setLocalError] = useState(null);
  const [notice, setNotice] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLocalError(null);
    if (!email || !password) {
      setLocalError("Enter both email and password.");
      return;
    }
    const result = await signIn(email, password);
    if (result.ok) onSignedIn();
  };

  const handleDemo = async () => {
    setLocalError(null);
    const result = await continueAsDemo();
    if (result.ok) onSignedIn();
  };
  const handleReset = async () => {
    setLocalError(null); setNotice(null);
    if (!email) { setLocalError("Enter your email address first."); return; }
    const result = await resetPassword(email);
    if (result.ok) setNotice("Password-reset email sent. Check your inbox and spam folder.");
    else setLocalError(result.error);
  };

  return html`
    <div class="auth-screen ambient">
      <${TopNav} variant="public" onHome=${onHome} />
      <div class="centered-screen" style=${{ minHeight: "auto", flex: 1 }}>
      <div class="panel stack gap-24" style=${{ width: 440, maxWidth: "94vw", padding: 32 }}>
        <div class="stack gap-8">
          <span class="brand-eyebrow"><${Logo} size=${18} id="auth" />ProofAegis</span>
          <h1 class="text-section-title" style=${{ fontSize: 24 }}>Sign in to your ProofAegis workspace</h1>
          <p class="text-secondary">Review blocked invoices, inspect source evidence, and manage resolution actions.</p>
        </div>

        <form class="stack gap-16" onSubmit=${handleSubmit}>
          <div>
            <label class="field-label" for="login-email">Email</label>
            <input id="login-email" class="input" type="email" placeholder="you@company.com" value=${email}
              onInput=${(e) => setEmail(e.target.value)} autocomplete="username" />
          </div>
          <div>
            <label class="field-label" for="login-password">Password</label>
            <input id="login-password" class="input" type="password" placeholder="••••••••" value=${password}
              onInput=${(e) => setPassword(e.target.value)} autocomplete="current-password" />
          </div>

          ${(localError || error) ? html`
            <div class="form-feedback form-feedback-error" role="alert">
              ${localError || error}
            </div>
          ` : null}
          ${notice ? html`<div class="form-feedback form-feedback-success" role="status">${notice}</div>` : null}

          <button class="btn btn-primary btn-block" type="submit" disabled=${loading}>
            ${loading ? "Signing in…" : "Sign in"}
          </button>
        </form>
        ${isFirebaseMode ? html`<button class="text-button" type="button" onClick=${handleReset}>Forgot password?</button>` : null}

        <div class="row gap-12" style=${{ alignItems: "center" }}>
          <hr class="hairline" style=${{ flex: 1 }} />
          <span class="text-muted text-small">or</span>
          <hr class="hairline" style=${{ flex: 1 }} />
        </div>

        ${demoAvailable ? html`<button class="btn btn-secondary btn-block" onClick=${handleDemo} disabled=${loading}>
          ${loading ? "Loading…" : "Continue with demo workspace"}
        </button>` : null}
        <button class="btn btn-ghost btn-block" onClick=${onCreateAccount} disabled=${loading}>Create an account</button>
        ${demoAvailable ? html`<div class="panel-elevated text-small text-muted stack gap-4" style=${{ padding: "10px 12px" }}>
          <div style=${{ fontWeight: 600, color: "var(--text-secondary)" }}>
            ${isFirebaseMode ? "Demo workspace — synthetic data only" : "Demo workspace — not production authentication"}
          </div>
          <div>Email: ${demoCredentials.email}</div>
          <div>Password: ${demoCredentials.password}</div>
        </div>` : null}

        <!-- Two ways out, and the first one is the fix for a dead end: this
             screen previously offered only "Back to guided tour" (which starts
             the tour) and "Create an account" (the other auth screen), so a
             visitor who clicked Sign in could not get back to the landing
             page at all. The nav brand above does it too; this is the
             in-context affordance for someone who has scrolled the card. -->
        <div class="row gap-8" style=${{ justifyContent: "center", flexWrap: "wrap" }}>
          <button class="btn btn-ghost btn-sm" onClick=${onHome}>
            <${Icon} name="arrowLeft" size=${15} /> Back to home
          </button>
          <button class="btn btn-ghost btn-sm" onClick=${onBackToTour}>
            <${Icon} name="play" size=${15} /> Guided tour
          </button>
        </div>
        </div>
      </div>
    </div>
  `;
}
