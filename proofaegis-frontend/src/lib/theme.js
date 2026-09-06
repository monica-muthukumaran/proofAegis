// theme.js — light / dark / system.
//
// Three states, not two. "System" is the default and the honest one: most
// people have already told their OS what they want, and an app that ignores
// that and forces light is the one that feels dated. An explicit choice
// stamps data-theme on <html> and wins; system stamps nothing and lets the
// prefers-color-scheme media query decide.
//
// Every storage access is guarded — private windows and blocked site data
// make these throw rather than return null, and a theme preference is not
// worth crashing a finance tool over.
const STORAGE_KEY = "proofaegis_theme";
const VALID = new Set(["light", "dark", "system"]);

const listeners = new Set();

export function getStoredTheme() {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    return VALID.has(stored) ? stored : "system";
  } catch {
    return "system";
  }
}

/** What the user will actually see right now, resolving "system". */
export function resolvedTheme(theme = getStoredTheme()) {
  if (theme === "system") {
    try {
      return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    } catch {
      return "light";
    }
  }
  return theme;
}

export function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === "system") {
    // Remove the attribute entirely rather than setting it to "system" —
    // the CSS keys off its absence to hand control to the media query.
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", theme);
  }
  // Lets the browser paint form controls, scrollbars, and the space beyond
  // the page in the matching scheme.
  root.style.colorScheme = resolvedTheme(theme);
}

export function setTheme(theme) {
  const next = VALID.has(theme) ? theme : "system";
  try {
    localStorage.setItem(STORAGE_KEY, next);
  } catch {
    // Preference simply will not survive a reload.
  }
  applyTheme(next);
  listeners.forEach((fn) => fn(next));
  return next;
}

export function onThemeChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Called once at startup, before first paint, to avoid a light flash. */
export function initTheme() {
  const theme = getStoredTheme();
  applyTheme(theme);

  // While on "system", follow the OS if the user changes it mid-session.
  try {
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = () => {
      if (getStoredTheme() === "system") applyTheme("system");
    };
    if (query.addEventListener) query.addEventListener("change", onChange);
    else if (query.addListener) query.addListener(onChange);
  } catch {
    // No matchMedia: the stored theme still applies, just without following.
  }
  return theme;
}
