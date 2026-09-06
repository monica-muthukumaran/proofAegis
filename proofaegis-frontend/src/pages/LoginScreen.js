import { html, useState } from "../lib.js";
import { useAuth } from "../services/AuthContext.js";
import { Icon } from "../components/ui/primitives.js";

export function LoginScreen({ onBackToTour, onSignedIn, onCreateAccount }) {
  const { signIn, continueAsDemo, resetPassword, loading, error, demoCredentials, isFirebaseMode } = useAuth();
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
    <div class="centered-screen">
      <div class="panel stack gap-24" style=${{ width: 440, maxWidth: "94vw", padding: 32 }}>
        <div class="stack gap-8">
          <div class="row gap-8" style=${{ color: "var(--accent)" }}>
            <${Icon} name="shield" size=${18} />
            <span class="text-small" style=${{ fontWeight: 700, letterSpacing: "0.04em", textTransform: "uppercase" }}>ProofAegis</span>
          </div>
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

        ${!isFirebaseMode ? html`<button class="btn btn-secondary btn-block" onClick=${handleDemo} disabled=${loading}>
          ${loading ? "Loading…" : "Continue with demo workspace"}
        </button>` : null}
        <button class="btn btn-ghost btn-block" onClick=${onCreateAccount} disabled=${loading}>Create an account</button>
        ${!isFirebaseMode ? html`<div class="panel-elevated text-small text-muted stack gap-4" style=${{ padding: "10px 12px" }}>
          <div style=${{ fontWeight: 600, color: "var(--text-secondary)" }}>Demo workspace — not production authentication</div>
          <div>Email: ${demoCredentials.email}</div>
          <div>Password: ${demoCredentials.password}</div>
        </div>` : null}

        <button class="btn btn-ghost btn-block" onClick=${onBackToTour}>
          <${Icon} name="arrowLeft" size=${15} /> Back to guided tour
        </button>
      </div>
    </div>
  `;
}
