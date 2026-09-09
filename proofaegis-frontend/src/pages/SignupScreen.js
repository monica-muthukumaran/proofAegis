import { html, useState } from "../lib.js";
import { useAuth } from "../services/AuthContext.js";
import { Icon } from "../components/ui/primitives.js";
import { Logo } from "../components/brand/Logo.js";
import { TopNav } from "../components/layout/TopNav.js";

export function SignupScreen({ onBackToLogin, onSignedUp, onHome }) {
  const { signUp, loading, error, isFirebaseMode } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [localError, setLocalError] = useState(null);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLocalError(null);
    if (!name.trim() || !email.trim() || !password || !confirmPassword) {
      setLocalError("Complete all fields to create your account.");
      return;
    }
    if (password.length < 6) {
      setLocalError("Password must be at least 6 characters.");
      return;
    }
    if (password !== confirmPassword) {
      setLocalError("Passwords do not match.");
      return;
    }
    const result = await signUp(name, email, password);
    if (result.ok) onSignedUp();
  };

  return html`
    <div class="auth-screen ambient">
      <${TopNav} variant="public" onHome=${onHome} />
      <div class="centered-screen" style=${{ minHeight: "auto", flex: 1 }}>
      <div class="panel stack gap-24" style=${{ width: 440, maxWidth: "94vw", padding: 32 }}>
        <div class="stack gap-8">
          <span class="brand-eyebrow"><${Logo} size=${18} id="auth" />ProofAegis</span>
          <h1 class="text-section-title" style=${{ fontSize: 24 }}>Create your ProofAegis account</h1>
          <p class="text-secondary">Set up your workspace to review and resolve invoice exceptions with evidence.</p>
        </div>

        <form class="stack gap-16" onSubmit=${handleSubmit}>
          <div>
            <label class="field-label" for="signup-name">Full name</label>
            <input id="signup-name" class="input" type="text" placeholder="Your name" value=${name} onInput=${(e) => setName(e.target.value)} autocomplete="name" />
          </div>
          <div>
            <label class="field-label" for="signup-email">Email</label>
            <input id="signup-email" class="input" type="email" placeholder="you@company.com" value=${email} onInput=${(e) => setEmail(e.target.value)} autocomplete="email" />
          </div>
          <div>
            <label class="field-label" for="signup-password">Password</label>
            <input id="signup-password" class="input" type="password" placeholder="At least 6 characters" value=${password} onInput=${(e) => setPassword(e.target.value)} autocomplete="new-password" />
          </div>
          <div>
            <label class="field-label" for="signup-confirm-password">Confirm password</label>
            <input id="signup-confirm-password" class="input" type="password" placeholder="Re-enter your password" value=${confirmPassword} onInput=${(e) => setConfirmPassword(e.target.value)} autocomplete="new-password" />
          </div>

          ${(localError || error) ? html`
            <div class="form-feedback form-feedback-error" role="alert">${localError || error}</div>
          ` : null}

          <button class="btn btn-primary btn-block" type="submit" disabled=${loading}>${loading ? "Creating account…" : "Create account"}</button>
        </form>

        <p class="text-muted text-small">${isFirebaseMode ? "Your account is secured by Firebase Authentication." : "Demo mode stores this account only for the current browser session."}</p>
        <div class="row gap-8" style=${{ justifyContent: "center", flexWrap: "wrap" }}>
          <button class="btn btn-ghost btn-sm" onClick=${onHome}>
            <${Icon} name="arrowLeft" size=${15} /> Back to home
          </button>
          <button class="btn btn-ghost btn-sm" onClick=${onBackToLogin}>Back to sign in</button>
        </div>
        </div>
      </div>
    </div>
  `;
}
