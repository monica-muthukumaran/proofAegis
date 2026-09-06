# Frontend Architecture

**ProofAegis client — React 19 + Vite, no JSX, no build-time template compiler.**

Everything below describes code in `proofaegis-frontend/` today. File paths and
line counts were read out of the repository.

---

## Contents

1. [Stack, and one unusual choice](#1-stack-and-one-unusual-choice)
2. [File map](#2-file-map)
3. [Routing and the shell](#3-routing-and-the-shell)
4. [The API layer and its fallback policy](#4-the-api-layer-and-its-fallback-policy)
5. [Authentication](#5-authentication)
6. [Screens](#6-screens)
7. [The evidence graph](#7-the-evidence-graph)
8. [The trust row](#8-the-trust-row)
9. [Theme and colour system](#9-theme-and-colour-system)
10. [Charts](#10-charts)
11. [Accessibility](#11-accessibility)
12. [Build and deploy](#12-build-and-deploy)

---

## 1. Stack, and one unusual choice

| Concern | Choice |
|---|---|
| Framework | React 19 |
| Templating | **`htm`** — tagged template literals, no JSX |
| Build | Vite 7 |
| Routing | ~30 lines of `history.pushState` in `pages/App.js` |
| State | React hooks. No Redux, no Zustand, no query library |
| Styling | Three plain CSS files, custom properties |
| Auth | Firebase Auth, with a demo-auth fallback |
| Charts | Hand-written SVG. No charting library |

**Why `htm` instead of JSX.** Every component is written as:

```js
return html`
  <div class="panel stack gap-12">
    <${Badge} tone="exception">${matchResult.exception_type}<//>
  </div>
`;
```

`htm` binds JSX-like syntax to `React.createElement` at runtime using template
literals, so the source needs no transform to run in a browser. The practical
payoff is that any file in `src/` can be opened, read, and reasoned about
without a mental JSX-to-JS compilation step, and a stack trace points at the
line you actually wrote. The cost is that component references need the
`<${Component}>` / `<//>` closing form, which is unfamiliar for about ten
minutes.

Total: **~6,300 lines of JS across 52 files**, **795 lines of CSS**.

---

## 2. File map

```
proofaegis-frontend/
├── index.html                    single entry, mounts #root
├── vite.config.js                dev server + /api proxy to :8080
├── firebase.json                 Hosting config + Cloud Run rewrite
├── styles.css              (132) structure, layout, components
│
└── src/
    ├── main.js                   boot: theme → AuthProvider → App
    ├── lib.js                    html/React/ReactDOM re-export
    ├── theme-tokens.css    (366) the palette and type
    ├── styles-color.css    (297) categorical colour for the graph
    │
    ├── pages/
    │   ├── App.js          (223) routing, tour orchestration, palette
    │   ├── Dashboard.js    (206) KPIs, priority case, recent activity
    │   ├── Analytics.js    (192) the argument for the product
    │   ├── ExceptionDetail.js (159) 7 tabs
    │   ├── LoginScreen.js   (95)
    │   ├── SignupScreen.js  (76)
    │   ├── EntryScreen.js   (61) tour vs sign-in
    │   ├── Settings.js      (47) read-only tolerance rules
    │   └── ExceptionQueue.js (39)
    │
    ├── components/
    │   ├── exceptions/
    │   │   ├── CreateExceptionModal.js (329) upload + live progress
    │   │   ├── MatchWorkspace.js       (275) the comparison table
    │   │   ├── DocumentsTab.js         (161)
    │   │   ├── AddDocumentsModal.js    (157)
    │   │   ├── ExceptionTable.js       (155) sort + filter, client-side
    │   │   ├── DocumentPreview.js      (152) PDF beside extracted fields
    │   │   ├── ToleranceBand.js        (140) the variance drawn to scale
    │   │   ├── HypothesisPanel.js      (132) agent 4
    │   │   ├── TrustRow.js              (92) the guardrail, visible
    │   │   ├── ExceptionSummary.js      (86)
    │   │   ├── InvestigationTrace.js    (84)
    │   │   └── ExceptionStatus.js       (52)
    │   ├── graph/
    │   │   ├── EvidenceGraph.js        (346) the product's argument
    │   │   ├── GraphLegend.js           (29)
    │   │   └── EvidenceDetailsDrawer.js (27)
    │   ├── analytics/
    │   │   ├── AccuracyTable.js        (231) the eval, on screen
    │   │   ├── DisagreementLedger.js   (154) AI vs deterministic
    │   │   ├── CrossCasePanel.js       (125) the headline
    │   │   ├── VendorRiskChart.js      (116)
    │   │   ├── TrendChart.js           (113)
    │   │   └── AgeingChart.js           (90)
    │   ├── dashboard/                        MetricCard, charts, timeline
    │   ├── resolutions/                      ResolutionAssistant, DraftEditor
    │   ├── layout/AppShell.js          (121) sidebar + topbar
    │   ├── tour/                             GuidedTour + 10 steps
    │   └── ui/
    │       ├── CommandPalette.js       (154) Ctrl/Cmd-K
    │       ├── primitives.js           (139) Badge, Icon, Skeleton, ErrorState
    │       ├── ModeBanner.js            (93) live vs demo indicator
    │       └── FirstRunTourOffer.js     (48)
    │
    ├── services/
    │   ├── api.js            (409) the ONLY module that knows URL shapes
    │   ├── AuthContext.js    (185) Firebase or demo auth
    │   └── firebaseAuth.js    (37)
    │
    ├── lib/
    │   ├── theme.js           (86) light / dark / system
    │   ├── useCountUp.js      (58) animated figures
    │   ├── labels.js          (31) shared copy
    │   └── tourState.js       (27)
    │
    └── data/mockData.js      (218) demo-mode fixtures
```

---

## 3. Routing and the shell

No router library. `pages/App.js` holds ~30 lines:

```js
function routeFromLocation() {
  const parts = window.location.pathname.replace(/^\/+|\/+$/g, "").split("/").filter(Boolean);
  if (parts[0] === "exceptions" && parts[1]) return { view: "exception-detail", exceptionId: parts[1] };
  if (["dashboard","exceptions","analytics","settings","login","signup"].includes(parts[0]))
    return { view: parts[0], exceptionId: null };
  return { view: "entry", exceptionId: null };
}
```

Views: `entry`, `login`, `signup`, `dashboard`, `exceptions`,
`exception-detail`, `analytics`, `settings`. Real URLs — `/exceptions/EXC-2026-0001`
is shareable and survives a refresh, because Firebase Hosting rewrites `**` to
`/index.html`.

`PROTECTED_VIEWS` gates the five app views behind a signed-in user, an active
guided tour, or a post-tour guest preview.

`AppShell` provides the sidebar (Dashboard / Exceptions / Analytics / Settings),
the topbar (command palette trigger, mode banner, theme toggle, tour, account),
and a mobile drawer below 1000px.

---

## 4. The API layer and its fallback policy

`services/api.js` is the only module that knows the backend's URL shape. It
mirrors the Flask blueprints exactly — no invented endpoints.

Every call returns `{ data, source, ... }` where `source` is one of:

| `source` | Meaning |
|---|---|
| `live` | the backend answered |
| `mock` | demo/mock mode is **deliberately** on |
| `error` | a real failure; `status` and `error` describe it, `data` is `null` |

### 4.1 The policy that matters

**Mock data is shown in exactly two situations, both chosen deliberately:**

1. `VITE_USE_MOCK_DATA=true` at build time, or
2. the user turned on demo mode (the guided tour does this so it can run with
   no backend at all).

**It is never shown because a request failed.** A 401, 403, 404, 409, 422 or
500 is a real answer from a real server and is surfaced as an error, and so is
an unreachable backend.

The previous behaviour — falling back to mock on any non-2xx — meant an expired
token in front of a judge rendered a complete, confident dashboard of
fabricated numbers with **no indication anything was wrong**. That failure mode
is worse than an error message.

### 4.2 Timeouts, chosen per operation

| Operation | Timeout |
|---|---|
| Reads | 10s |
| Analytics overview | 20s |
| Gemini-backed generation | 90s |
| Uploads | 300s |

A blanket 4s timeout used to abort real generate calls mid-flight and then
display mock content, leaving the UI permanently out of step with what the
backend had actually saved.

### 4.3 404 as a legitimate state

`getReasoning`, `getHypotheses`, `getResolution` and `getTrustCheck` translate
a 404 into `{ data: null, notGenerated: true }` rather than an error. "Nothing
has been generated on this case yet" is a real state that must reach the UI so
the Generate button appears.

### 4.4 Uploads

`uploadDocuments` uses `XMLHttpRequest` rather than `fetch` — the only way to
get real upload progress, and a multi-megabyte batch deserves a real progress
bar rather than an indeterminate spinner. `Content-Type` is never set on
`FormData`; the browser must add the multipart boundary itself.

HTTP **207** (some files accepted, some rejected) is treated as success for the
batch; the caller shows the per-file outcome.

---

## 5. Authentication

`services/AuthContext.js` runs one of two modes:

- **Firebase Auth** when `VITE_FIREBASE_API_KEY` is set. Real accounts; the ID
  token is attached to every request.
- **Demo auth** when it is blank. A `sessionStorage`-backed account —
  `judge@demo.proofaegis.local` / `demo-only` — so the app runs with zero
  Firebase setup.

`sessionStorage`, never `localStorage`: a demo session should not outlive the
tab.

`api.setIdTokenProvider()` lets the plain (non-React) API module attach a fresh
ID token to every request without importing React state.

---

## 6. Screens

### Entry
The frame: *"What passes is scarier than what fails."* Two doors — a
two-minute guided tour needing no login, or sign in.

### Dashboard
Four KPI cards (open exceptions, value on hold, awaiting action, average match
score), the highest-priority case, exception-type distribution, recent
activity. `ModeBanner` shows live-vs-demo, storage backend, and whether Gemini
is on — so nobody mistakes deterministic output for model output.

### Exception Queue
Sortable, filterable table. **Filtering and sorting are client-side** — the
list is already one request, and re-fetching on every keystroke would be
slower and chattier for a few hundred rows. Row rails are colour-coded by risk;
identifiers are monospaced.

### Exception Detail — seven tabs

| Tab | Contents |
|---|---|
| **Summary** | what was found, in a sentence, with what is outstanding |
| **Documents** | every document, its extraction, confidence, and a preview |
| **Match** | cross-case banner, tolerance bands, **trust row**, comparison table, line-by-line |
| **Evidence graph** | the provenance chain, five columns |
| **Investigate** | agent 4 — ranked candidate explanations |
| **Resolution** | cited draft; every claim links to its source |
| **Audit trail** | every state change, actor and timestamp |

The Investigate tab sits between the evidence and the draft because that is a
reviewer's own order of work: read what was found, decide what to check, then
write to somebody about it.

### Analytics — ordered as the pitch

1. **Cross-case panel** — what a per-invoice check would have missed. The only
   figure on the page a commercial product does not already produce, so it
   leads.
2. **Portfolio KPIs** — invoices analysed, clean rate, exception rate, value at
   risk.
3. **Disagreement ledger** — how often the guardrail fired.
4. **Accuracy table** — the eval results, with every disagreement named.
5. Vendor risk, trend, ageing — the substrate that makes the first four
   trustworthy.

### Settings
Read-only view of the resolved tolerance rules and which rule applied.

---

## 7. The evidence graph

`components/graph/EvidenceGraph.js` (346 lines). The product's argument:
**every finding traces back to a document somebody can open.**

Five columns, left to right:

```
Source documents → Extracted values → Rule applied → Findings → Routing
```

Nodes and edges arrive from `graph_service.py` exactly as computed. This file
does layout and presentation only, and must never add, merge, or relabel a
node.

### 7.1 Six things that make it readable

1. **Self-sizing canvas.** Width comes from the column count
   (`COLUMN_WIDTH = 268`), height from the busiest column
   (`ROW_HEIGHT = 132`), and it scrolls horizontally when that exceeds the
   panel. A fixed viewBox was the original bug: four columns across whatever
   width the panel had gave each column ~150px, nodes are 214px wide and
   centred, so **every node overlapped its neighbours on both sides**.
   Shrinking the nodes to fit would have solved the overlap by making the
   labels unreadable — the same problem wearing a different hat.
2. **Path highlighting.** Hovering or selecting dims the canvas and lights only
   that node's chain — itself, everything it touches, and everything those
   touch. Two hops, which is exactly the depth of this graph.
3. **Type is visible, not inferred.** Each node carries a 4px coloured header
   strip *and* a spelled-out type label. Colour is never the only distinguisher
   — which matters for colour-vision deficiency and for a projector.
4. **Directed, coloured edges.** Horizontal-tangent bezier curves with
   arrowheads, in the **source node's** hue, so a chain reads as one colour
   resolving into the finding's red.
5. **Banded columns** with pill headers, so the reading order is drawn rather
   than implied.
6. **Draggable nodes** and a text view, so a dense case can be untangled or
   read linearly.

### 7.2 Colour

Three categorical hues plus one reserved status colour, validated as a set
against both surfaces (all-pairs, CVD and normal vision):

| Node type | Light | Dark |
|---|---|---|
| Source document | `#2a78d6` blue | `#3987e5` |
| Extracted value | `#1baf7a` aqua | `#199e70` |
| Rule applied | `#eda100` amber (dashed border) | `#c98500` |
| Finding | `var(--exception)` rust | same token |
| Routing | `var(--muted)` neutral | same token |

A fourth *categorical* hue does not survive the dark-mode all-pairs gate beside
blue. `finding` is therefore not one — it aliases the theme's signal colour,
which is correct rather than a workaround: **a finding IS a status**, and its
red must be the same red as "high risk" in the queue.

Routing is deliberately neutral. It is an outcome, not a kind of evidence, and
giving it a hue would make the graph look like it has five subjects when it has
four.

---

## 8. The trust row

`components/exceptions/TrustRow.js`. On the Match tab:

```
AI-STATED (INJECTED)   COMPUTED IN CODE   DIFFERENCE
    ₹31,200                ₹25,000        ₹6,200 (24.8%)
    ── struck through ──   ── highlighted ──

  ⛨ Deterministic value used. The AI's figure was discarded.

  Injected fault — a figure corrupted on purpose so the check can be
  watched running. Not model output.
```

The provenance line is not decoration. There are three genuinely different
things this row can describe, and conflating them would be the exact dishonesty
the row exists to rule out:

| Case | Line shown |
|---|---|
| Live model, agreed | "Stated by the reasoning model on this case." |
| Live model, overridden | same — and this is the real event |
| Fault injection | "Injected fault … Not model output." |
| Fallback answered | "The model did not answer … Nothing here is evidence about the model." |

---

## 9. Theme and colour system

Three stylesheets, loaded in this order — the order is what keeps all three
free of `!important`:

| File | Job |
|---|---|
| `styles.css` | structure, layout, components |
| `src/theme-tokens.css` | the palette and type, plus corrections to anything that hardcoded a colour before a theme existed |
| `src/styles-color.css` | the graph's categorical hues, on top, because they are identity rather than chrome |

### 9.1 The rule the palette is built around

**Rust is reserved for risk.**

Primary actions are **dark ink**, not red. High risk, a breached variance, the
marker outside its tolerance band, a finding node's border, a worsening month
— those are red, and nothing else ever is. A red button would put the loudest
colour on screen on every panel, and the exceptions would stop standing out.

### 9.2 Contrast is solved, not eyeballed

Every signal token is the **minimum** step that clears 4.5:1 against every
surface it is actually used on, in both modes. Eyeballing had put three of them
between 4.1 and 4.5 — which looks fine and is not.

Both modes currently pass with **zero contrast failures**, measured by walking
every text node and compositing translucent backgrounds before comparing.

### 9.3 Dark mode

Three states: `light`, `dark`, and `system` (the default). An explicit choice
stamps `data-theme` on `<html>`; `system` stamps nothing and lets
`prefers-color-scheme` decide.

The dark token block is written **twice**, deliberately:

```css
:root[data-theme="dark"] { ... }                    /* the toggle */
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]) { ... }           /* the OS setting */
}
```

`:root:not([data-theme="light"])` matches whenever no explicit light theme is
stamped — which is *always*, unless the user chose light. Outside a media query
it therefore paints **every** visitor dark regardless of their OS. It only
means "system default, and the system is dark" inside the media query, and the
`:not()` is what lets an explicit light choice still win on a dark OS.

Dark values are *selected* for the dark surface, not flipped from light. The
primary action inverts to a light surface with dark text — a near-black button
on a near-black page would disappear, which is the usual way a dark mode built
by inversion goes wrong.

### 9.4 Typography

One family throughout: **DM Sans**. Headings lean on size and weight rather
than a display serif, which is what makes a dense finance screen read as one
document rather than a magazine.

Identifiers — case numbers, invoice and PO references, filenames, settings
paths — get a **monospace** system stack with tabular figures and
`white-space: nowrap`. These are read character by character and often retyped
or grepped for; `EXC-2026-0001` broken over three lines at a hyphen is
unreadable and unselectable.

---

## 10. Charts

Hand-written SVG, no library. Three of them:

- **`VendorRiskChart`** — exception rate against value at risk. Ranking on
  either number alone hides one of two different problems: a high rate on small
  invoices, and a low rate on large ones.
- **`TrendChart`** — monthly volume split clean/exception, with the rate
  overlaid.
- **`AgeingChart`** — open cases bucketed against the 14-day SLA.

All three read colours from CSS custom properties, so they follow the theme
without a JS palette. Animations are presentation only — nothing depends on one
completing, so `prefers-reduced-motion` loses movement and nothing else.

---

## 11. Accessibility

- Every interactive element is a real `<button>` or `<a>`; graph nodes carry
  `role="button"`, `tabIndex`, and Enter/Space handlers.
- Focus rings are 2px in the signal colour with a 2px offset — a focus ring
  *is* "look here".
- Tabs use `role="tablist"` / `role="tab"` / `aria-selected`.
- Scrollable regions get `role="region"`, `aria-label` and `tabIndex="0"`.
- Colour is never the sole carrier of meaning: badges pair a tint with a word,
  graph nodes pair a hue with a spelled-out type.
- Minimum touch target 44px.
- Wide content scrolls inside its own container; the page body never scrolls
  horizontally.

---

## 12. Build and deploy

```bash
npm install
npm run dev        # localhost:5173, /api proxied to :8080
npm run lint       # eslint, currently clean
npm run build      # → dist/
npm run deploy     # build + firebase deploy --only hosting
```

Current production bundle: **~484 kB JS (141 kB gzip)**, **~33 kB CSS
(7.4 kB gzip)**.

### Environment

| Variable | Purpose |
|---|---|
| `VITE_API_BASE_URL` | leave **blank** in production — Hosting rewrites `/api/**` to Cloud Run, same origin |
| `VITE_USE_MOCK_DATA` | `true` only to build a no-backend demo bundle |
| `VITE_FIREBASE_*` | web app config; public values, but never server secrets |

Relative URLs go through Vite's `/api` dev proxy locally and Firebase Hosting's
Cloud Run rewrite in production, so **no environment value or cross-origin
request is necessary in either environment**.

---

## See also

- [`ARCHITECTURE_BACKEND.md`](ARCHITECTURE_BACKEND.md)
- [`GOOGLE_STACK.md`](GOOGLE_STACK.md)
- [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md)
- [`USER_GUIDE.md`](USER_GUIDE.md)
