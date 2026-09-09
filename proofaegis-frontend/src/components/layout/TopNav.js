// TopNav.js — the single navigation surface, on every screen.
//
// Replaces the left sidebar and the thin topbar that sat beside it. One bar
// means the workspace gets the full width for tables and the evidence graph,
// which are the two screens that were actually short of room, and it means a
// signed-out visitor and a signed-in analyst see the same header rather than
// two unrelated layouts.
//
// It also fixes a real dead end. The sign-in and sign-up screens had no route
// home at all: the only ways out were "Back to guided tour" (which starts the
// tour) and "Create an account" (which is the other auth screen). A visitor
// who clicked Sign in from the landing page could not get back to it. The
// brand mark is now a link on every screen, and it is the fix for that.
//
// WHAT "HOME" MEANS DEPENDS ON WHO IS ASKING
//
// Signed out, home is the landing page — the pitch. Signed in, home is the
// dashboard, because a landing page is not a place a working analyst ever
// wants to be returned to. `onHome` resolves that; this component just calls
// it.
import { html, React, useState, useEffect, useRef } from "../../lib.js";
import { Icon, Badge } from "../ui/primitives.js";
import { Logo } from "../brand/Logo.js";
import { AboutDeveloperLink } from "../about/AboutDeveloper.js";
import { getStoredTheme, setTheme, resolvedTheme, onThemeChange } from "../../lib/theme.js";
import { useAuth } from "../../services/AuthContext.js";

// Cycles light -> dark -> system. Three states because "system" is the
// default and needs to be reachable again once someone has overridden it.
const THEME_ORDER = ["light", "dark", "system"];
const THEME_ICON = { light: "zoomIn", dark: "shield", system: "grid" };
const THEME_LABEL = { light: "Light", dark: "Dark", system: "System" };

function ThemeToggle() {
  const [theme, setLocalTheme] = useState(() => getStoredTheme());
  useEffect(() => onThemeChange(setLocalTheme), []);

  const next = THEME_ORDER[(THEME_ORDER.indexOf(theme) + 1) % THEME_ORDER.length];
  return html`
    <button class="btn btn-ghost btn-sm" onClick=${() => setTheme(next)}
      title=${`Theme: ${THEME_LABEL[theme]}${theme === "system" ? ` (currently ${resolvedTheme()})` : ""}. Click for ${THEME_LABEL[next]}.`}
      aria-label=${`Switch theme to ${THEME_LABEL[next]}`}>
      <${Icon} name=${THEME_ICON[theme]} size=${15} />
      <span class="theme-label">${THEME_LABEL[theme]}</span>
    </button>
  `;
}

// Four top-level destinations, not seven. The three registers are records
// ABOUT the work rather than the work itself, so they collapse into one
// menu — which is the same grouping the sidebar used, just folded up. Settings
// moves into the account menu, where every other product keeps it.
const NAV = [
  { key: "dashboard", label: "Dashboard", icon: "grid" },
  { key: "exceptions", label: "Exceptions", icon: "inbox" },
  {
    key: "records",
    label: "Records",
    icon: "layers",
    children: [
      { key: "invoices", label: "Invoices", icon: "file" },
      { key: "purchase-orders", label: "Purchase Orders", icon: "layers" },
      { key: "vendors", label: "Vendors", icon: "building" },
    ],
  },
  { key: "analytics", label: "Analytics", icon: "graph" },
];

const RECORD_KEYS = new Set(["invoices", "purchase-orders", "vendors"]);

// Shared dismiss behaviour for the two dropdowns. Outside click AND Escape,
// because a menu that only closes one way strands a keyboard user.
function useDismiss(open, close) {
  const ref = useRef(null);
  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e) => { if (ref.current && !ref.current.contains(e.target)) close(); };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);
  return ref;
}

function RecordsMenu({ activeView, navigate }) {
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  const active = RECORD_KEYS.has(activeView);

  return html`
    <div class="nav-menu-wrap" ref=${ref}>
      <button type="button" class=${`nav-link ${active ? "active" : ""}`}
        aria-expanded=${open} aria-haspopup="true"
        onClick=${() => setOpen((v) => !v)}>
        <${Icon} name="layers" size=${16} />
        <span>Records</span>
        <${Icon} name="chevronDown" size=${13} className="nav-caret" />
      </button>
      ${open ? html`
        <div class="nav-dropdown" role="menu">
          ${NAV[2].children.map((item) => html`
            <button key=${item.key} type="button" role="menuitem"
              class=${`nav-dropdown-item ${activeView === item.key ? "active" : ""}`}
              onClick=${() => { setOpen(false); navigate(item.key); }}>
              <${Icon} name=${item.icon} size=${15} />${item.label}
            </button>
          `)}
        </div>
      ` : null}
    </div>
  `;
}

function AccountMenu({ navigate }) {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));

  return html`
    <div class="nav-menu-wrap" ref=${ref}>
      <button class="btn btn-secondary btn-sm" aria-expanded=${open} aria-haspopup="true"
        onClick=${() => setOpen((v) => !v)}>
        <span class="account-label">${user ? user.name : "Account"}</span>
        <${Icon} name="chevronDown" size=${13} className="nav-caret" />
      </button>
      ${open ? html`
        <div class="nav-dropdown nav-dropdown-right" role="menu">
          ${user ? html`<div class="nav-dropdown-head">${user.email}</div>` : null}
          <!-- The workspace chip lived in the sidebar. It is a fact about
               what you are looking at, so it follows the account rather than
               disappearing with the sidebar. -->
          <div class="nav-dropdown-head" style=${{ paddingTop: 0 }}>
            <${Badge} tone="accent">Synthetic workspace<//>
          </div>
          <button type="button" role="menuitem" class="nav-dropdown-item"
            onClick=${() => { setOpen(false); navigate("settings"); }}>
            <${Icon} name="settings" size=${15} />Settings
          </button>
          <div class="nav-dropdown-item nav-dropdown-static">
            <${AboutDeveloperLink} />
          </div>
          <button type="button" role="menuitem" class="nav-dropdown-item"
            onClick=${() => { setOpen(false); signOut(); }}>
            <${Icon} name="logout" size=${15} />Sign out
          </button>
        </div>
      ` : null}
    </div>
  `;
}

function MobileAccountActions({ onNavigate }) {
  const { user, signOut } = useAuth();
  return html`
    <${React.Fragment}>
      ${user ? html`<div class="nav-mobile-label">${user.email}</div>` : null}
      <div class="nav-mobile-item nav-dropdown-static"><${AboutDeveloperLink} /></div>
      <button type="button" role="menuitem" class="nav-mobile-item" onClick=${() => { onNavigate("dashboard"); signOut(); }}>
        <${Icon} name="logout" size=${16} />Sign out
      </button>
    <//>
  `;
}

/**
 * @param {"public"|"app"} variant  which side of sign-in this is
 * @param {function} onHome         resolves "home" for the current auth state
 */
export function TopNav({
  variant = "app",
  activeView = null,
  navigate = () => {},
  onHome = () => {},
  onStartTour = null,
  onSignIn = null,
  onSignUp = null,
}) {
  const [menuOpen, setMenuOpen] = useState(false);

  const go = (key) => { setMenuOpen(false); navigate(key); };

  // data-tour="product-introduction" moved here from the sidebar workspace
  // card, which no longer exists. The tour's opening step is the product
  // introduction, so the brand mark is a better anchor for it anyway.
  const brand = html`
    <button type="button" class="nav-brand" onClick=${onHome}
      data-tour="product-introduction"
      aria-label="ProofAegis — go to home">
      <${Logo} size=${30} withWordmark=${true} id="nav" />
    </button>
  `;

  if (variant === "public") {
    return html`
      <header class="topnav topnav-public">
        <div class="topnav-inner">
          ${brand}
          <div class="grow"></div>
          <${ThemeToggle} />
          ${onSignIn ? html`<button class="btn btn-ghost btn-sm" onClick=${onSignIn}>Sign in</button>` : null}
          ${onSignUp ? html`<button class="btn btn-secondary btn-sm" onClick=${onSignUp}>Create account</button>` : null}
        </div>
      </header>
    `;
  }

  return html`
    <header class="topnav">
      <div class="topnav-inner">
        ${brand}

        <nav class="nav-links" aria-label="Primary">
          ${NAV.map((item) => (item.children
            ? html`<${RecordsMenu} key=${item.key} activeView=${activeView} navigate=${go} />`
            : html`
              <button key=${item.key} type="button"
                class=${`nav-link ${activeView === item.key ? "active" : ""}`}
                aria-current=${activeView === item.key ? "page" : null}
                onClick=${() => go(item.key)}>
                <${Icon} name=${item.icon} size=${16} />
                <span>${item.label}</span>
              </button>
            `))}
        </nav>

        <div class="grow"></div>

        <button class="btn btn-secondary btn-sm palette-trigger"
          onClick=${() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }))}
          aria-label="Open command palette">
          <${Icon} name="zoomIn" size=${14} />
          <span class="palette-trigger-label">Search</span>
          <kbd class="kbd">${navigator.platform.toLowerCase().includes("mac") ? "⌘" : "Ctrl"} K</kbd>
        </button>

        <${ThemeToggle} />

        ${onStartTour ? html`
          <button class="btn btn-ghost btn-sm tour-trigger nav-wide-only" onClick=${onStartTour}>
            <${Icon} name="play" size=${15} /> <span class="tour-label">Guided tour</span>
          </button>
        ` : null}

        <span class="nav-wide-only"><${AccountMenu} navigate=${go} /></span>

        <button class="btn btn-ghost btn-sm nav-burger" onClick=${() => setMenuOpen((v) => !v)}
          aria-expanded=${menuOpen} aria-label="Menu">
          <${Icon} name="grid" size=${18} />
        </button>
      </div>

      ${menuOpen ? html`
        <div class="nav-mobile" role="menu">
          ${NAV.flatMap((item) => (item.children
            ? [html`<div class="nav-mobile-label" key=${item.key}>${item.label}</div>`,
               ...item.children.map((c) => html`
                 <button key=${c.key} type="button" role="menuitem"
                   class=${`nav-mobile-item ${activeView === c.key ? "active" : ""}`}
                   onClick=${() => go(c.key)}>
                   <${Icon} name=${c.icon} size=${16} />${c.label}
                 </button>`)]
            : [html`
              <button key=${item.key} type="button" role="menuitem"
                class=${`nav-mobile-item ${activeView === item.key ? "active" : ""}`}
                onClick=${() => go(item.key)}>
                <${Icon} name=${item.icon} size=${16} />${item.label}
              </button>`]))}
          <button type="button" role="menuitem" class="nav-mobile-item"
            onClick=${() => go("settings")}>
            <${Icon} name="settings" size=${16} />Settings
          </button>

          <!-- The tour and the account actions are hidden from the bar at this
               width — six controls do not fit beside a wordmark on a phone —
               so they have to reappear here or they become unreachable. -->
          <div class="nav-mobile-divider"></div>
          ${onStartTour ? html`
            <button type="button" role="menuitem" class="nav-mobile-item"
              onClick=${() => { setMenuOpen(false); onStartTour(); }}>
              <${Icon} name="play" size=${16} />Guided tour
            </button>
          ` : null}
          <${MobileAccountActions} onNavigate=${go} />
        </div>
      ` : null}
    </header>
  `;
}

export function AppShell({ activeView, navigate, onStartTour, onHome, children }) {
  return html`
    <div class="app-shell">
      <${TopNav} variant="app" activeView=${activeView} navigate=${navigate}
        onStartTour=${onStartTour} onHome=${onHome} />
      <div class="main-content">
        <div class="page-body">${children}</div>
      </div>
    </div>
  `;
}
