// tourState.js — remembers whether this browser has seen the guided tour.
//
// Lives in its own module rather than in App.js so the dashboard's tour offer
// can read it without importing the page that renders the dashboard, which
// would be a module cycle.
//
// A per-browser convenience, so localStorage is the right home — and every
// access is guarded, because private windows and blocked site data make these
// calls throw rather than return null. Failing to read simply means the offer
// shows again, which is the harmless direction to fail in.
const TOUR_SEEN_KEY = "proofaegis_tour_seen";

export function hasSeenTour() {
  try {
    return localStorage.getItem(TOUR_SEEN_KEY) === "true";
  } catch {
    return false;
  }
}

export function markTourSeen() {
  try {
    localStorage.setItem(TOUR_SEEN_KEY, "true");
  } catch {
    // Nothing to do — the offer simply shows again next visit.
  }
}
