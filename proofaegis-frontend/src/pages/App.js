import { html, useState, useEffect } from "../lib.js";
import * as api from "../services/api.js";
import { useAuth } from "../services/AuthContext.js";
import { EntryScreen } from "../pages/EntryScreen.js";
import { LoginScreen } from "../pages/LoginScreen.js";
import { SignupScreen } from "../pages/SignupScreen.js";
import { Dashboard } from "../pages/Dashboard.js";
import { ExceptionQueue } from "../pages/ExceptionQueue.js";
import { ExceptionDetail } from "../pages/ExceptionDetail.js";
import { Settings } from "../pages/Settings.js";
import { Analytics } from "../pages/Analytics.js";
import { Invoices } from "../pages/Invoices.js";
import { PurchaseOrders } from "../pages/PurchaseOrders.js";
import { Vendors } from "../pages/Vendors.js";
import { AppShell } from "../components/layout/AppShell.js";
import { GuidedTour } from "../components/tour/GuidedTour.js";
import { TOUR_STEPS, TOUR_EXCEPTION_ID } from "../components/tour/tourSteps.js";
import { CreateExceptionModal } from "../components/exceptions/CreateExceptionModal.js";
import { markTourSeen } from "../lib/tourState.js";
import { CommandPalette } from "../components/ui/CommandPalette.js";

const PROTECTED_VIEWS = new Set([
  "dashboard", "exceptions", "exception-detail", "invoices", "purchase-orders",
  "vendors", "analytics", "settings",
]);

const ROUTED_VIEWS = [
  "dashboard", "exceptions", "invoices", "purchase-orders", "vendors",
  "analytics", "settings", "login", "signup",
];

// The registers are records, not work items, so the topbar names them
// plainly. "Exception" stays singular on a detail view because the title
// describes what is open, not where you are.
const VIEW_TITLES = {
  dashboard: "Dashboard", exceptions: "Exception Queue", "exception-detail": "Exception",
  invoices: "Invoices", "purchase-orders": "Purchase Orders", vendors: "Vendors",
  analytics: "Analytics", settings: "Settings",
};

function routeFromLocation() {
  const parts = window.location.pathname.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
  if (parts[0] === "exceptions" && parts[1]) return { view: "exception-detail", exceptionId: parts[1] };
  if (ROUTED_VIEWS.includes(parts[0])) return { view: parts[0], exceptionId: null };
  return { view: "entry", exceptionId: null };
}

function pathFor(view, exceptionId) {
  if (view === "exception-detail") return `/exceptions/${exceptionId || TOUR_EXCEPTION_ID}`;
  return view === "entry" ? "/" : `/${view}`;
}

export function App() {
  const { user } = useAuth();
  const initialRoute = routeFromLocation();
  const [view, setView] = useState(initialRoute.view);
  const [selectedExceptionId, setSelectedExceptionId] = useState(initialRoute.exceptionId);
  const [guestPreview, setGuestPreview] = useState(false);

  const [tourActive, setTourActive] = useState(false);
  const [tourStepIndex, setTourStepIndex] = useState(0);
  const [tourTab, setTourTab] = useState(null);

  const [createModalOpen, setCreateModalOpen] = useState(false);

  // Set when arriving at the queue from a vendor card. The queue owns its own
  // search box, so this is a seed value rather than controlled state — the
  // analyst can clear or edit it like anything else they typed.
  const [queuePrefill, setQueuePrefill] = useState("");

  // The palette searches cases, so it needs them. Fetched once when a signed-in
  // session starts rather than on every open — the list is already the queue's
  // single request and this reuses the same shape.
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [paletteCases, setPaletteCases] = useState([]);

  // Route guard: protected views require either a signed-in user or an
  // active/just-finished guided-tour guest preview.
  useEffect(() => {
    if (PROTECTED_VIEWS.has(view) && !user && !guestPreview && !tourActive) {
      setView("login");
    }
  }, [view, user, guestPreview, tourActive]);

  // Demo mode is on exactly when nobody is signed in AND we are in a
  // guest-facing context (the guided tour, or post-tour exploring). Deriving
  // it from state rather than toggling it at each transition is what stops it
  // leaking: previously startTour() switched it on and only sign-in switched
  // it off, so a signed-in user who ran the tour left the silent mock
  // fallback armed for the rest of the session — the exact behaviour the
  // API-client rewrite existed to remove.
  useEffect(() => {
    api.setDemoMode(!user && (tourActive || guestPreview));
  }, [user, tourActive, guestPreview]);

  useEffect(() => {
    if (!user && !guestPreview) return;
    let mounted = true;
    api.listExceptions().then((r) => {
      if (mounted && r.source !== "error") setPaletteCases(r.data || []);
    });
    return () => { mounted = false; };
  }, [user, guestPreview]);

  // Cmd+K on macOS, Ctrl+K elsewhere. Suppressed during the guided tour,
  // which owns the screen and its own keyboard handling.
  useEffect(() => {
    const onKeyDown = (event) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        if (!tourActive) setPaletteOpen((v) => !v);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [tourActive]);

  useEffect(() => {
    const onPopState = () => {
      const route = routeFromLocation();
      setView(route.view);
      setSelectedExceptionId(route.exceptionId);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  useEffect(() => {
    const path = pathFor(view, selectedExceptionId);
    if (window.location.pathname !== path) window.history.pushState({}, "", path);
  }, [view, selectedExceptionId]);

  const navigate = (target) => {
    setSelectedExceptionId(null);
    if (target !== "exceptions") setQueuePrefill("");
    setView(target);
  };

  // A vendor card hands the queue a search term instead of a filter param:
  // the backend returns the whole portfolio in one request and the queue
  // already searches vendor names locally, so this needs no new endpoint and
  // leaves the analyst holding an editable query rather than a locked filter.
  const openVendorExceptions = (vendorName) => {
    setSelectedExceptionId(null);
    setQueuePrefill(vendorName || "");
    setView("exceptions");
  };

  const openException = (id) => {
    setSelectedExceptionId(id);
    setView("exception-detail");
  };

  // --- Guided tour control ---
  // The tour must run with no backend, so it is the one place that turns on
  // demo mode — explicitly, never as a silent reaction to a failed request.
  const startTour = () => {
    setTourStepIndex(0);
    setTourActive(true);
  };

  const handleTourEnterRoute = (route) => {
    if (route.view === "dashboard") {
      setSelectedExceptionId(null);
      setTourTab(null);
      setView("dashboard");
    } else if (route.view === "exception-detail") {
      setSelectedExceptionId(TOUR_EXCEPTION_ID);
      setTourTab(route.tab || "summary");
      setView("exception-detail");
    }
  };

  const tourNext = () => setTourStepIndex((i) => Math.min(i + 1, TOUR_STEPS.length - 1));
  const tourBack = () => setTourStepIndex((i) => Math.max(i - 1, 0));
  const tourRestart = () => setTourStepIndex(0);
  const tourExitToEntry = () => { markTourSeen(); setTourActive(false); setGuestPreview(false); setView("entry"); setSelectedExceptionId(null); };
  const tourFinishExplore = () => { markTourSeen(); setTourActive(false); setGuestPreview(true); setView("dashboard"); setSelectedExceptionId(null); };
  const tourGoToSignIn = () => { setTourActive(false); setGuestPreview(false); setView("login"); setSelectedExceptionId(null); };

  // --- Page rendering ---
  let pageContent = null;

  if (view === "entry") {
    pageContent = html`<${EntryScreen} onStartTour=${startTour} onSignIn=${() => setView("login")} onSignUp=${() => setView("signup")} onSignedIn=${() => { setGuestPreview(false); setView("dashboard"); }} />`;
  } else if (view === "login") {
    pageContent = html`<${LoginScreen} onBackToTour=${startTour} onCreateAccount=${() => setView("signup")} onSignedIn=${() => { setGuestPreview(false); setView("dashboard"); }} />`;
  } else if (view === "signup") {
    pageContent = html`<${SignupScreen} onBackToLogin=${() => setView("login")} onSignedUp=${() => { setGuestPreview(false); setView("dashboard"); }} />`;
  } else if (view === "dashboard") {
    pageContent = html`
      <${AppShell} activeView="dashboard" navigate=${navigate} title="Dashboard" onStartTour=${startTour}>
        <${Dashboard} openException=${openException} onCreateException=${() => setCreateModalOpen(true)} onStartTour=${startTour} navigateToQueue=${() => navigate("exceptions")} />
      <//>
    `;
  } else if (view === "exceptions") {
    pageContent = html`
      <${AppShell} activeView="exceptions" navigate=${navigate} title="Exception Queue" onStartTour=${startTour}>
        <${ExceptionQueue} openException=${openException} initialQuery=${queuePrefill} />
      <//>
    `;
  } else if (view === "exception-detail") {
    pageContent = html`
      <${AppShell} activeView="exceptions" navigate=${navigate} title="Exception" onStartTour=${startTour}>
        <${ExceptionDetail}
          exceptionId=${selectedExceptionId || TOUR_EXCEPTION_ID}
          onBack=${() => (tourActive ? null : navigate("exceptions"))}
          forcedTab=${tourActive ? tourTab : null}
        />
      <//>
    `;
  } else if (view === "invoices") {
    pageContent = html`
      <${AppShell} activeView="invoices" navigate=${navigate} title=${VIEW_TITLES.invoices} onStartTour=${startTour}>
        <${Invoices} openException=${openException} />
      <//>
    `;
  } else if (view === "purchase-orders") {
    pageContent = html`
      <${AppShell} activeView="purchase-orders" navigate=${navigate} title=${VIEW_TITLES["purchase-orders"]} onStartTour=${startTour}>
        <${PurchaseOrders} openException=${openException} />
      <//>
    `;
  } else if (view === "vendors") {
    pageContent = html`
      <${AppShell} activeView="vendors" navigate=${navigate} title=${VIEW_TITLES.vendors} onStartTour=${startTour}>
        <${Vendors} onViewExceptions=${openVendorExceptions} />
      <//>
    `;
  } else if (view === "analytics") {
    pageContent = html`
      <${AppShell} activeView="analytics" navigate=${navigate} title="Analytics" onStartTour=${startTour}>
        <${Analytics} />
      <//>
    `;
  } else if (view === "settings") {
    pageContent = html`
      <${AppShell} activeView="settings" navigate=${navigate} title="Settings" onStartTour=${startTour}>
        <${Settings} />
      <//>
    `;
  }

  // The `key` is what makes the route transition work at all. Without it React
  // reconciles the old view's DOM into the new one, so the animation class is
  // already on the element and never restarts — the page would swap silently,
  // which is exactly the behaviour this replaces. Keying on the view name
  // forces an unmount/remount, and the entrance runs once per navigation.
  //
  // The detail view is keyed on the case id too, so moving between two cases
  // transitions rather than mutating in place — which previously made a
  // different invoice's figures appear under the heading you were reading.
  const routeKey = view === "exception-detail" ? `${view}:${selectedExceptionId}` : view;

  return html`<div class="app-root">
    <div class="route-enter" key=${routeKey}>${pageContent}</div>
    ${tourActive ? html`
      <${GuidedTour}
        stepIndex=${tourStepIndex}
        onNext=${tourNext}
        onBack=${tourBack}
        onSkip=${tourExitToEntry}
        onClose=${tourExitToEntry}
        onRestart=${tourRestart}
        onFinish=${tourFinishExplore}
        onGoToSignIn=${tourGoToSignIn}
        onEnterRoute=${handleTourEnterRoute}
      />
    ` : null}
    ${!tourActive ? html`
      <${CommandPalette}
        open=${paletteOpen}
        onClose=${() => setPaletteOpen(false)}
        exceptions=${paletteCases}
        onNavigate=${navigate}
        onOpenException=${openException}
        onNewCase=${() => setCreateModalOpen(true)}
      />
    ` : null}
    ${!tourActive ? html`
      <${CreateExceptionModal}
        open=${createModalOpen}
        onClose=${() => setCreateModalOpen(false)}
        onOpenExisting=${(id) => { setCreateModalOpen(false); openException(id); }}
      />
    ` : null}
  </div>`;
}
