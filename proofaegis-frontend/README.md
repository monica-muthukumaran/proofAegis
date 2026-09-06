# ProofAegis Frontend

Documentation for this client lives in the **project root**, so there is one
copy of everything rather than three that drift apart.

| You want | Read |
|---|---|
| How the client is built — routing, API layer, theme, the evidence graph | [`../ARCHITECTURE_FRONTEND.md`](../ARCHITECTURE_FRONTEND.md) |
| Deploying to Firebase Hosting | [`../DEPLOYMENT_GUIDE.md`](../DEPLOYMENT_GUIDE.md) |
| Using the app | [`../USER_GUIDE.md`](../USER_GUIDE.md) |

## Quick start

```bash
npm install
```
```bash
npm run dev
```

Runs on `http://localhost:5173`, with `/api` proxied to `localhost:8080`.

Sign in with `judge@demo.proofaegis.local` / `demo-only`, or click **Start
guided tour** — no login needed.

## Scripts

```bash
npm run lint
```
```bash
npm run build
```
```bash
npm run deploy
```
```bash
npm run deploy:preview
```

`deploy` builds and pushes to Firebase Hosting. `deploy:preview` gives a
temporary URL and leaves production untouched.

## Environment

Copy `.env.example` to `.env.local` (development) or `.env.production` (build).

**`VITE_API_BASE_URL` stays empty.** Firebase Hosting rewrites `/api/**` to
Cloud Run, so the API is same-origin and needs no URL — and Vite's dev proxy
does the same thing locally.

Leave `VITE_USE_MOCK_DATA=false` unless you deliberately want a bundle that
runs with no backend. Mock data is never shown because a request *failed* —
only because demo mode was turned on. See
[`../ARCHITECTURE_FRONTEND.md` §4](../ARCHITECTURE_FRONTEND.md#4-the-api-layer-and-its-fallback-policy).

## Stylesheets

Three, loaded in this order — the order is what keeps all three free of
`!important`:

| File | Job |
|---|---|
| `styles.css` | structure, layout, components |
| `src/theme-tokens.css` | the palette and type |
| `src/styles-color.css` | categorical colour for the evidence graph |
