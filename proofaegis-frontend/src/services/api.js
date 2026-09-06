// api.js — the ONLY module that knows about the backend's URL shape.
// Mirrors backend/routes/exceptions.py, routes/settings.py, and
// routes/dashboard.py exactly — no invented endpoints.
//
// FALLBACK POLICY (this is the important part of this file)
//
// Mock data is shown in exactly two situations, both of them chosen
// deliberately:
//
//   1. VITE_USE_MOCK_DATA=true at build time, or
//   2. the user turned on demo mode (the guided tour does this so it can run
//      with no backend at all).
//
// It is NOT shown because a request failed. A 401, 403, 404, 409, 422 or 500
// is a real answer from a real server and gets surfaced as an error, and so
// does an unreachable backend. The previous behaviour — falling back to mock
// on any non-2xx — meant an expired token in front of a judge rendered a
// complete, confident dashboard of fabricated numbers with no indication
// anything was wrong. That failure mode is worse than an error message.
//
// Every call returns { data, source, ... } where source is one of:
//   "live"  — the backend answered
//   "mock"  — demo/mock mode is deliberately on
//   "error" — a real failure; `status` and `error` describe it, data is null
import * as mock from "../data/mockData.js";

// Firebase Hosting forwards /api/* to Cloud Run in production. Relative URLs
// also go through Vite's /api development proxy locally, so no environment
// value or cross-origin request is necessary in either environment.
const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL || "";
const BASE_URL = `${configuredBaseUrl.replace(/\/$/, "")}/api`;

const BUILD_MOCK_MODE = import.meta.env.VITE_USE_MOCK_DATA === "true";

// Reads are quick; Gemini-backed generation and multi-file uploads are not.
// The old blanket 4s timeout aborted real generate calls mid-flight and then
// displayed mock content, leaving the UI permanently out of step with what
// the backend had actually saved.
const READ_TIMEOUT_MS = 10000;
const GENERATE_TIMEOUT_MS = 90000;
const UPLOAD_TIMEOUT_MS = 300000;

// --- demo mode ------------------------------------------------------------
let demoMode = BUILD_MOCK_MODE;
const modeListeners = new Set();

export function isDemoMode() {
  return demoMode;
}

export function setDemoMode(enabled) {
  demoMode = Boolean(enabled) || BUILD_MOCK_MODE;
  modeListeners.forEach((fn) => fn(demoMode));
}

export function onModeChange(fn) {
  modeListeners.add(fn);
  return () => modeListeners.delete(fn);
}

// Set by AuthContext.js on mount — lets this plain (non-React) module attach
// a fresh Firebase ID token to every request without importing React state.
let idTokenProvider = null;
export function setIdTokenProvider(fn) {
  idTokenProvider = fn;
}

async function authHeaders(extra) {
  const headers = { ...extra };
  if (idTokenProvider) {
    const token = await idTokenProvider();
    if (token) headers["Authorization"] = `Bearer ${token}`;
  }
  return headers;
}

async function tryFetch(path, options = {}) {
  const { timeout = READ_TIMEOUT_MS, body, headers: extraHeaders, ...rest } = options;
  try {
    const isFormData = body instanceof FormData;
    const headers = await authHeaders({
      // Never set Content-Type on FormData — the browser must add the
      // multipart boundary itself or Flask cannot parse the parts.
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...extraHeaders,
    });
    const res = await fetch(BASE_URL + path, {
      ...rest,
      body,
      headers,
      signal: AbortSignal.timeout(timeout),
    });
    const payload = await res.json().catch(() => null);
    if (!res.ok) return { ok: false, status: res.status, data: payload };
    return { ok: true, status: res.status, data: payload };
  } catch (e) {
    const timedOut = e && (e.name === "TimeoutError" || e.name === "AbortError");
    return { ok: false, offline: true, timedOut, error: e };
  }
}

function messageFor(result) {
  if (result.timedOut) return "The server took too long to respond. Try again.";
  if (result.offline) return "Cannot reach the ProofAegis API. Check that the backend is running.";
  const detail = result.data && (result.data.detail || result.data.error);
  const byStatus = {
    401: "Your session has expired. Sign in again.",
    403: "You do not have access to this workspace.",
    404: "Not found.",
    409: "This case is not ready for that yet.",
    422: "The server rejected that request as invalid.",
    500: "The server hit an unexpected error.",
    // A dead backend reaches the browser as a gateway error rather than a
    // connection failure, because something in front of it is still up — the
    // Vite dev proxy locally, Firebase Hosting's Cloud Run rewrite in
    // production. Naming that correctly points at the right thing to restart.
    502: "The ProofAegis API is not responding. It may be starting up or stopped.",
    503: "The ProofAegis API is unavailable. It may be starting up or stopped.",
    504: "The ProofAegis API timed out.",
  };
  return detail || byStatus[result.status] || `Request failed (${result.status}).`;
}

/**
 * Turns a raw fetch result into the { data, source } contract.
 * mockFactory is only ever called when demo/mock mode is deliberately on.
 */
function resolve(result, mockFactory) {
  if (result.ok) return { data: result.data, source: "live", status: result.status };
  if (demoMode && mockFactory) {
    return { data: mockFactory(), source: "mock", demo: true };
  }
  return {
    data: null,
    source: "error",
    status: result.status || 0,
    offline: Boolean(result.offline),
    error: messageFor(result),
    raw: result.data || null,
  };
}

// --- connectivity / mode --------------------------------------------------
let lastKnownMode = null;

export function getLastKnownMode() {
  return lastKnownMode;
}

export async function checkBackend() {
  // /api/health is intentionally unauthenticated, so this is a true
  // connectivity check and never confuses "signed out" with "server down".
  const r = await tryFetch("/health", { timeout: 6000 });
  if (r.ok) {
    lastKnownMode = { ...(lastKnownMode || {}), reachable: true, ...r.data };
    return { reachable: true, data: r.data };
  }
  lastKnownMode = { reachable: false, error: messageFor(r) };
  return { reachable: false, error: messageFor(r) };
}

export async function getMode() {
  const r = await tryFetch("/settings/mode");
  if (r.ok) {
    lastKnownMode = { ...(lastKnownMode || {}), reachable: true, ...r.data };
    return { data: r.data, source: "live" };
  }
  return resolve(r, () => ({ mock_mode: true, datastore: "browser_mock", synthetic_data: true }));
}

// --- exceptions -----------------------------------------------------------
export async function listExceptions() {
  return resolve(await tryFetch("/exceptions"), () => mock.EXCEPTIONS);
}

export async function getException(id) {
  return resolve(await tryFetch(`/exceptions/${id}`),
    () => mock.EXCEPTIONS.find((e) => e.exception_id === id) || null);
}

export async function createException(metadata = {}) {
  return resolve(
    await tryFetch("/exceptions", { method: "POST", body: JSON.stringify(metadata) }),
    null, // creating a case has no meaningful mock — it must really happen
  );
}

/**
 * Uploads any number of PDFs to a case in one request.
 * files: [{ file: File, documentType: string|"auto" }]
 * A case itself has no document limit; this is just one batch.
 */
export async function uploadDocuments(exceptionId, files, { onProgress } = {}) {
  const form = new FormData();
  files.forEach((entry) => {
    form.append("files", entry.file, entry.file.name);
    form.append("document_types", entry.documentType || "auto");
  });

  // XHR rather than fetch: it is the only way to get real upload progress,
  // and a multi-megabyte batch deserves a real progress bar rather than an
  // indeterminate spinner.
  if (typeof onProgress === "function" && typeof XMLHttpRequest !== "undefined") {
    const headers = await authHeaders({});
    return new Promise((resolveP) => {
      const xhr = new XMLHttpRequest();
      xhr.open("POST", BASE_URL + `/exceptions/${exceptionId}/documents`);
      Object.entries(headers).forEach(([k, v]) => xhr.setRequestHeader(k, v));
      xhr.timeout = UPLOAD_TIMEOUT_MS;
      xhr.upload.onprogress = (event) => {
        if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
      };
      xhr.onload = () => {
        let payload = null;
        try { payload = JSON.parse(xhr.responseText); } catch { payload = null; }
        // 207 = some files accepted, some rejected. Still a success for the
        // batch; the caller shows the per-file outcome.
        if (xhr.status >= 200 && xhr.status < 300) {
          resolveP({ data: payload, source: "live", status: xhr.status });
        } else {
          resolveP(resolve({ ok: false, status: xhr.status, data: payload }, null));
        }
      };
      xhr.onerror = () => resolveP(resolve({ ok: false, offline: true }, null));
      xhr.ontimeout = () => resolveP(resolve({ ok: false, offline: true, timedOut: true }, null));
      xhr.send(form);
    });
  }

  return resolve(
    await tryFetch(`/exceptions/${exceptionId}/documents`,
      { method: "POST", body: form, timeout: UPLOAD_TIMEOUT_MS }),
    null,
  );
}

export async function retryDocument(exceptionId, documentId) {
  return resolve(
    await tryFetch(`/exceptions/${exceptionId}/documents/${documentId}/retry`,
      { method: "POST", timeout: GENERATE_TIMEOUT_MS }),
    null,
  );
}

export async function analyzeException(exceptionId) {
  return resolve(
    await tryFetch(`/exceptions/${exceptionId}/analyze`, { method: "POST", timeout: GENERATE_TIMEOUT_MS }),
    null,
  );
}

export async function getReadiness(exceptionId) {
  return resolve(await tryFetch(`/exceptions/${exceptionId}/readiness`), null);
}

/** Authenticated document view. Never a bucket URL. */
export function documentContentPath(exceptionId, documentId) {
  return `${BASE_URL}/exceptions/${exceptionId}/documents/${documentId}/content`;
}

/** Fetches a stored PDF as an object URL the browser can display. */
export async function fetchDocumentBlobUrl(exceptionId, documentId) {
  try {
    const headers = await authHeaders({});
    const res = await fetch(documentContentPath(exceptionId, documentId), {
      headers,
      signal: AbortSignal.timeout(READ_TIMEOUT_MS),
    });
    if (!res.ok) {
      const payload = await res.json().catch(() => null);
      return resolve({ ok: false, status: res.status, data: payload }, null);
    }
    const blob = await res.blob();
    return { data: URL.createObjectURL(blob), source: "live" };
  } catch (e) {
    return resolve({ ok: false, offline: true, error: e }, null);
  }
}

export async function getDocuments(id) {
  return resolve(await tryFetch(`/exceptions/${id}/documents`), () => mock.DOCUMENTS[id] || []);
}

// Polled while an upload batch is being read. The upload request stays open
// for the whole batch, so this is the only way the client can say WHICH
// document is being processed instead of showing a finished bar and the word
// "Processing" for the entire wait.
export async function getProgress(id) {
  return resolve(await tryFetch(`/exceptions/${id}/progress`), () => null);
}

export async function getMatch(id) {
  return resolve(await tryFetch(`/exceptions/${id}/match`), () => mock.MATCH_RESULTS[id] || null);
}

export async function getGraph(id) {
  return resolve(await tryFetch(`/exceptions/${id}/graph`), () => mock.buildEvidenceGraph(id));
}

export async function getReasoning(id) {
  const r = await tryFetch(`/exceptions/${id}/reasoning`);
  // 404 here is the honest "not generated yet" state, not a failure. It must
  // reach the UI so the Generate button appears; substituting mock content
  // made that button unreachable for every seeded case.
  if (!r.ok && r.status === 404) return { data: null, source: "live", notGenerated: true };
  return resolve(r, () => mock.REASONING[id] || null);
}

export async function generateReasoning(id) {
  return resolve(
    await tryFetch(`/exceptions/${id}/reasoning/generate`,
      { method: "POST", timeout: GENERATE_TIMEOUT_MS }),
    () => mock.REASONING[id] || null,
  );
}

/**
 * What the reasoning model said the financial impact was, against what the
 * deterministic layer computed. 404 until the reasoning agent has run on this
 * case — before that there is no model figure to have checked, and showing
 * agreement would be reporting a comparison that never happened.
 */
export async function getTrustCheck(id) {
  const r = await tryFetch(`/exceptions/${id}/trust`);
  if (!r.ok && r.status === 404) return { data: null, source: "live", notChecked: true };
  return resolve(r, () => null);
}

export async function getHypotheses(id) {
  const r = await tryFetch(`/exceptions/${id}/hypotheses`);
  if (!r.ok && r.status === 404) return { data: null, source: "live", notGenerated: true };
  return resolve(r, () => null);
}

export async function generateHypotheses(id) {
  return resolve(
    await tryFetch(`/exceptions/${id}/hypotheses/generate`,
      { method: "POST", timeout: GENERATE_TIMEOUT_MS }),
    null,
  );
}

export async function getResolution(id) {
  const r = await tryFetch(`/exceptions/${id}/resolution`);
  if (!r.ok && r.status === 404) return { data: null, source: "live", notGenerated: true };
  return resolve(r, () => mock.RESOLUTIONS[id] || null);
}

export async function generateResolution(id) {
  return resolve(
    await tryFetch(`/exceptions/${id}/resolution/generate`,
      { method: "POST", timeout: GENERATE_TIMEOUT_MS }),
    () => mock.RESOLUTIONS[id] || null,
  );
}

export async function getAudit(id) {
  return resolve(await tryFetch(`/exceptions/${id}/audit`), () => mock.buildAuditTrail(id));
}

export async function updateStatus(id, status, actor, note) {
  return resolve(
    await tryFetch(`/exceptions/${id}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status, actor, note }),
    }),
    () => ({ exception_id: id, status }),
  );
}

// --- analytics ------------------------------------------------------------
// One round trip: the page shows four linked views of the same population,
// and fetching them separately would let them disagree if a case changed
// mid-render. `days` is the bounded window the backend clamps.
export async function getAnalyticsOverview(days = 365) {
  return resolve(await tryFetch(`/analytics/overview?days=${days}`, { timeout: 20000 }), null);
}

export async function getVendorRisk(days = 365, limit = 25) {
  return resolve(await tryFetch(`/analytics/vendor-risk?days=${days}&limit=${limit}`), null);
}

/** What the cross-case checks caught that a per-invoice system could not. */
export async function getCrossCaseValue(days = 365) {
  return resolve(await tryFetch(`/analytics/cross-case?days=${days}`), null);
}

/** The disagreement ledger — how often the guardrail fired, across the run. */
export async function getTrustLedger() {
  return resolve(await tryFetch("/analytics/trust"), null);
}

/**
 * The last recorded eval run. 404 means nobody has run one, which is a real
 * state the UI reports as "not measured" rather than as an error — the
 * command that produces it is printed instead.
 */
export async function getAccuracy() {
  return resolve(await tryFetch("/analytics/accuracy", { timeout: 20000 }), null);
}

// --- settings / dashboard -------------------------------------------------
export async function getTolerance() {
  return resolve(await tryFetch("/settings/tolerance"), () => mock.TOLERANCE);
}

export async function getDashboardSummary() {
  return resolve(await tryFetch("/dashboard/summary"), () => mock.DASHBOARD_SUMMARY);
}
