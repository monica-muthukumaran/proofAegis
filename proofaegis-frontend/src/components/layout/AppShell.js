import { html, React, useState, useEffect } from "../../lib.js";
import { useAuth } from "../../services/AuthContext.js";
import { Icon, Badge } from "../ui/primitives.js";
import { Logo } from "../brand/Logo.js";
import { AboutDeveloperLink } from "../about/AboutDeveloper.js";
import { getStoredTheme, setTheme, resolvedTheme, onThemeChange } from "../../lib/theme.js";

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

// Grouped, because the flat list stopped reading as a hierarchy once the
// registers arrived: "Exceptions" is the work, the registers are the records
// that work is about, and Analytics/Settings are neither. The dividers are
// labels, not links — nothing here is a collapsible tree, which would hide
// destinations behind a click for four items.
const NAV_GROUPS = [
  { label: null, items: [
    { key: "dashboard", label: "Dashboard", icon: "grid" },
    { key: "exceptions", label: "Exceptions", icon: "inbox" },
  ] },
  { label: "Records", items: [
    { key: "invoices", label: "Invoices", icon: "file" },
    { key: "purchase-orders", label: "Purchase Orders", icon: "layers" },
    { key: "vendors", label: "Vendors", icon: "building" },
  ] },
  { label: null, items: [
    { key: "analytics", label: "Analytics", icon: "graph" },
    { key: "settings", label: "Settings", icon: "settings" },
  ] },
];

export function Sidebar({ activeView, navigate, mobileOpen, setMobileOpen }) {
  const content = html`
    <div class="sidebar-brand">
      <${Logo} size=${32} withWordmark=${true} tagline="Evidence command center" id="sidebar" />
    </div>
    <nav class="sidebar-nav">
      ${NAV_GROUPS.map((group, gi) => html`
        <${React.Fragment} key=${group.label || `g${gi}`}>
          ${group.label ? html`<div class="sidebar-group-label">${group.label}</div>` : null}
          ${group.items.map((item) => html`
            <a
              key=${item.key}
              class="sidebar-link ${activeView === item.key ? "active" : ""}"
              onClick=${(e) => { e.preventDefault(); navigate(item.key); setMobileOpen(false); }}
              href="#"
            >
              <${Icon} name=${item.icon} size=${17} />
              <span>${item.label}</span>
            </a>
          `)}
        <//>
      `)}
    </nav>
    <div class="grow"></div>
    <div class="panel-elevated stack gap-4" style=${{ padding: "12px 14px" }} data-tour="product-introduction">
      <div class="text-small" style=${{ fontWeight: 600 }}>Demo Finance Workspace</div>
      <${Badge} tone="accent">Synthetic workspace<//>
    </div>
    <div style=${{ padding: "10px 14px 2px" }}>
      <${AboutDeveloperLink} />
    </div>
  `;

  return html`<div class="sidebar-container">
    ${mobileOpen ? html`<div class="sidebar-backdrop" onClick=${() => setMobileOpen(false)}></div>` : null}
    <aside class="sidebar ${mobileOpen ? "open" : ""}">${content}</aside>
  </div>`;
}

export function Topbar({ title, onMenuClick, onStartTour }) {
  const { user, signOut } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);

  return html`
    <header class="topbar">
      <button class="btn btn-ghost btn-sm mobile-menu-btn" onClick=${onMenuClick} aria-label="Open menu">
        <${Icon} name="grid" size=${18} />
      </button>
      <h2 class="topbar-title" style=${{ fontSize: 17 }}>${title}</h2>
      <div class="grow"></div>
      <button class="btn btn-secondary btn-sm palette-trigger"
        onClick=${() => window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", ctrlKey: true }))}
        aria-label="Open command palette">
        <${Icon} name="zoomIn" size=${14} />
        <span class="palette-trigger-label">Search</span>
        <kbd class="kbd">${navigator.platform.toLowerCase().includes("mac") ? "⌘" : "Ctrl"} K</kbd>
      </button>
      <${ThemeToggle} />
      <button class="btn btn-ghost btn-sm tour-trigger" onClick=${onStartTour}>
        <${Icon} name="play" size=${15} /> <span class="tour-label">Guided tour</span>
      </button>
      <div style=${{ position: "relative" }}>
        <button class="btn btn-secondary btn-sm" onClick=${() => setMenuOpen((v) => !v)}>
          ${user ? user.name : "Account"} <${Icon} name="chevronDown" size=${14} />
        </button>
        ${menuOpen ? html`
          <div class="panel-elevated" style=${{ position: "absolute", right: 0, top: "calc(100% + 8px)", width: 220, padding: 8, zIndex: 30 }}>
            <div class="text-muted text-small" style=${{ padding: "8px 10px" }}>${user ? user.email : ""}</div>
            <button class="btn btn-ghost btn-sm btn-block" style=${{ justifyContent: "flex-start" }} onClick=${signOut}>
              <${Icon} name="logout" size=${15} /> Sign out
            </button>
          </div>
        ` : null}
      </div>
    </header>
  `;
}

export function AppShell({ activeView, navigate, title, onStartTour, children }) {
  const [mobileOpen, setMobileOpen] = useState(false);
  return html`
    <div class="app-shell">
      <${Sidebar} activeView=${activeView} navigate=${navigate} mobileOpen=${mobileOpen} setMobileOpen=${setMobileOpen} />
      <div class="main-content">
        <${Topbar} title=${title} onMenuClick=${() => setMobileOpen(true)} onStartTour=${onStartTour} />
        <div class="page-body">${children}</div>
      </div>
    </div>
  `;
}
