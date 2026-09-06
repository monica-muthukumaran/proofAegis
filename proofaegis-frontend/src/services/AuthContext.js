// AuthContext.js — demo-auth by default; swaps to real Firebase Auth
// automatically when window.__FIREBASE_CONFIG__ is set (see
// firebaseAuth.js). Every consumer (AppShell, App's route guard,
// LoginScreen) only ever calls useAuth() — nothing else in the app
// touches storage or knows which auth provider is active.
import { html, createContext, useContext, useState, useEffect } from "../lib.js";
import * as api from "./api.js";
import {
  isFirebaseConfigured, firebaseSignIn, firebaseSignUp, firebaseSignOut,
  onFirebaseAuthChanged, getCurrentIdToken, toAppUser, initializeFirebaseAuth, sendResetEmail,
} from "./firebaseAuth.js";

const DEMO_EMAIL = "judge@demo.proofaegis.local";
const DEMO_PASSWORD = "demo-only";
const SESSION_KEY = "proofaegis_demo_session"; // sessionStorage only — never localStorage
const DEMO_USERS_KEY = "proofaegis_demo_users";

const AuthContext = createContext(null);
const FIREBASE_MODE = isFirebaseConfigured();

function readSession() {
  try {
    const raw = sessionStorage.getItem(SESSION_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

function readDemoUsers() {
  try {
    const raw = sessionStorage.getItem(DEMO_USERS_KEY);
    return raw ? JSON.parse(raw) : {};
  } catch {
    return {};
  }
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => (FIREBASE_MODE ? null : readSession()));
  const [loading, setLoading] = useState(FIREBASE_MODE); // Firebase's own auth-state check on first load
  const [error, setError] = useState(null);

  // Demo-auth mode: persist to sessionStorage only.
  useEffect(() => {
    if (FIREBASE_MODE) return;
    if (user) sessionStorage.setItem(SESSION_KEY, JSON.stringify(user));
    else sessionStorage.removeItem(SESSION_KEY);
  }, [user]);

  // Firebase mode: subscribe to the SDK's own session restoration.
  useEffect(() => {
    if (!FIREBASE_MODE) return;
    let unsubscribe = () => {};
    initializeFirebaseAuth()
      .then(() => { unsubscribe = onFirebaseAuthChanged((firebaseUser) => { setUser(toAppUser(firebaseUser)); setLoading(false); }); })
      .catch(() => { setError("Firebase Authentication could not start. Check the environment variables."); setLoading(false); });
    return () => { if (unsubscribe) unsubscribe(); };
  }, []);

  const signIn = async (email, password) => {
    setLoading(true);
    setError(null);

    if (FIREBASE_MODE) {
      try {
        const firebaseUser = await firebaseSignIn(email, password);
        setUser(toAppUser(firebaseUser));
        setLoading(false);
        return { ok: true };
      } catch {
        setLoading(false);
        const message = "Could not sign in with that email and password.";
        setError(message);
        return { ok: false, error: message };
      }
    }

    // Demo-auth path (default — no Firebase project configured).
    await new Promise((r) => setTimeout(r, 450)); // simulated network latency for a real loading state
    setLoading(false);
    const normalizedEmail = email.trim().toLowerCase();
    const demoUsers = readDemoUsers();
    const account = normalizedEmail === DEMO_EMAIL && password === DEMO_PASSWORD
      ? { email: DEMO_EMAIL, name: "Demo Reviewer" }
      : demoUsers[normalizedEmail]?.password === password ? demoUsers[normalizedEmail] : null;
    if (account) {
      setUser({ email: account.email, name: account.name, workspace: "Demo Finance Workspace" });
      return { ok: true };
    }
    const message = "Invalid email or password for this demo workspace.";
    setError(message);
    return { ok: false, error: message };
  };

  const signUp = async (name, email, password) => {
    setLoading(true);
    setError(null);

    if (FIREBASE_MODE) {
      try {
        const firebaseUser = await firebaseSignUp(name, email, password);
        setUser(toAppUser(firebaseUser));
        setLoading(false);
        return { ok: true };
      } catch (e) {
        setLoading(false);
        const message = e?.code === "auth/email-already-in-use"
          ? "An account already exists for that email. Sign in instead."
          : e?.code === "auth/weak-password"
            ? "Choose a stronger password with at least 6 characters."
            : "Could not create your account. Check your details and try again.";
        setError(message);
        return { ok: false, error: message };
      }
    }

    await new Promise((r) => setTimeout(r, 450));
    const normalizedEmail = email.trim().toLowerCase();
    const demoUsers = readDemoUsers();
    if (normalizedEmail === DEMO_EMAIL || demoUsers[normalizedEmail]) {
      const message = "An account already exists for that email. Sign in instead.";
      setLoading(false);
      setError(message);
      return { ok: false, error: message };
    }
    demoUsers[normalizedEmail] = { email: normalizedEmail, name: name.trim(), password };
    sessionStorage.setItem(DEMO_USERS_KEY, JSON.stringify(demoUsers));
    setUser({ email: normalizedEmail, name: name.trim(), workspace: "Demo Finance Workspace" });
    setLoading(false);
    return { ok: true };
  };

  const continueAsDemo = async () => {
    if (FIREBASE_MODE) {
      // No real demo account by default in a live Firebase project — surface
      // this clearly rather than silently pretending to sign in.
      setError("Demo workspace login isn't available once a real Firebase project is configured. Use a real account.");
      return { ok: false, error: "demo_unavailable_in_firebase_mode" };
    }
    return signIn(DEMO_EMAIL, DEMO_PASSWORD);
  };

  const signOut = async () => {
    if (FIREBASE_MODE) {
      await firebaseSignOut();
    }
    setUser(null);
  };

  const resetPassword = async (email) => {
    if (!FIREBASE_MODE) return { ok: false, error: "Password reset is available after Firebase Authentication is configured." };
    try {
      await sendResetEmail(email.trim());
      return { ok: true };
    } catch (e) {
      const message = e?.code === "auth/user-not-found" ? "No account was found for that email address." : "We could not send the reset email. Check the address and try again.";
      setError(message);
      return { ok: false, error: message };
    }
  };

  // Used by services/api.js to attach `Authorization: Bearer <token>` on
  // every request. Returns null in demo-auth mode — the backend's
  // require_auth decorator is lenient by default (config.AUTH_REQUIRED),
  // so requests with no token still work exactly as before.
  const getIdToken = async () => (FIREBASE_MODE ? getCurrentIdToken() : null);

  useEffect(() => {
    api.setIdTokenProvider(getIdToken);
  }, []);

  const value = {
    user, loading, error, signIn, signUp, continueAsDemo, signOut, resetPassword, getIdToken,
    isFirebaseMode: FIREBASE_MODE,
    demoCredentials: { email: DEMO_EMAIL, password: DEMO_PASSWORD },
  };
  return html`<${AuthContext.Provider} value=${value}>${children}<//>`;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
