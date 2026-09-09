# Demo Video Guide

A three-minute recording of ProofAegis: what to prepare, what to say, what to
click, and what to do when something goes wrong.

---

## Contents

1. [The shape of it](#1-the-shape-of-it)
2. [What you need](#2-what-you-need)
3. [Pre-flight — 20 minutes before](#3-pre-flight--20-minutes-before)
4. [Recording settings](#4-recording-settings)
5. [The script, beat by beat](#5-the-script-beat-by-beat)
6. [Exact click path](#6-exact-click-path)
7. [Things that will go wrong](#7-things-that-will-go-wrong)
8. [Give these zero seconds](#8-give-these-zero-seconds)
9. [Editing notes](#9-editing-notes)
10. [Final checklist](#10-final-checklist)

---

## 1. The shape of it

| Time | Beat | The line that carries it |
|---|---|---|
| 0:00–0:25 | **The crime** | "Both invoices are perfect. Every AP system pays both." |
| 0:25–1:00 | **The trust moment** | "The AI said ₹31,200. The code said ₹25,000. The code won." |
| 1:00–1:50 | **One hero case** | Upload → evidence graph → click a node to the source PDF |
| 1:50–2:30 | **The cross-case catch** | "No single-invoice check can see this" |
| 2:30–2:50 | **Portfolio analytics** | "Which vendors to audit, and why" |
| 2:50–3:00 | **Limitations** | In your own words |

### The first twenty-five seconds

Open on the crime, not on the control. A judge who has never worked in
accounts payable must understand what is being stolen before they are asked
to care how it is caught — and "three-way match" is a phrase that costs you
the room if it arrives before the story does.

> "A vendor sends you the same bill twice, under two different numbers.
> Both invoices are perfect. The purchase order agrees. The goods receipt
> agrees. Every AP system on the market pays both.
>
> We found nine invoices like that. Eight lakh rupees. Every document on
> every one of them agreed."

Only then: *the reason is that those systems check an invoice against its own
paperwork, and the second copy is in a different file. We read across all of
them.*

**Do not say "three-way match" before 0:25.** The domain vocabulary is what
you explain the mechanism WITH; it is not what you open on.

**Three rules for the whole recording.**

1. **Never say a number that is not on screen.** Every figure in this product
   is computed and visible. Quoting one from memory undoes the entire argument.
2. **The trust moment is now the second beat, not the fourth.** It is the one
   thing no competing project has — every other AI in the room is right for
   three minutes; yours is visibly wrong and gets overruled by code. Showing
   it at 0:25 rather than 1:45 means it lands while attention is highest, and
   it survives a demo that runs out of time.
3. **If you are running long, cut the portfolio tour.** Not the trust moment,
   not the limitations.

---

## 2. What you need

### Software
- Screen recorder — OBS Studio (free), Loom, or QuickTime
- Chrome or Edge at **1920×1080**
- A second terminal window, **not** on screen

### Running services
- Backend on `localhost:8080`
- Frontend on `localhost:5173`
- Or a deployed Firebase Hosting URL

### Files to have ready
`backend/data/synthetic_cases/price_variance_001/` — four PDFs:

```
purchase_order.pdf
vendor_invoice.pdf
goods_receipt_note.pdf
rejection_notice.pdf
```

Generate them if missing:

```bash
cd backend && ./venv/Scripts/python.exe scripts/generate_synthetic_pdfs.py
```

Put that folder somewhere you can reach in **two clicks** from the file picker.
Fumbling in a file dialog costs ten seconds you do not have.

The generator now writes fourteen cases, not three, and drops a `README.md`
beside them naming the expected finding for each. The ones worth knowing about:

| Folder | Shows |
|---|---|
| `price_variance_001` | the hero case — a 10.4% overcharge |
| `clean_match_001` | the control: everything agrees, and the queue says so |
| `unrelated_documents_001` | the product refusing to compute rather than inventing a variance |
| `duplicate_invoice_a` → `_b` | cross-case. Upload in that order |
| `payment_details_changed_a` → `_b` | cross-case. Same vendor, different bank |
| `po_over_billed_a` → `_b` → `_c` | cross-case. 3 × 90 units against an order for 200 |

The `_a`/`_b`/`_c` sets each pass their own three-way match. The finding only
exists because the workspace remembers the earlier upload, which is the whole
claim — so if you demo one cross-case thing, demo one of these.

---

## 3. Pre-flight — 20 minutes before

Work through this in order.

### 3.1 Regenerate the data

```bash
cd backend && ./venv/Scripts/python.exe scripts/generate_synthetic_data.py --count 320
```

The RNG is seeded, so this is reproducible — a demo that reshuffles itself
between rehearsal and recording is not a demo.

### 3.2 Run both evals so the Accuracy table has content

```bash
cd backend && ./venv/Scripts/python.exe -m eval.run_eval --count 320 --json data/generated/eval_report.json
```
```bash
cd backend && ./venv/Scripts/python.exe -m eval.extraction_eval --json data/generated/extraction_report.json
```

Without these, Analytics shows *"No eval run has been recorded"* — a dead panel
in the middle of your strongest section.

### 3.3 Confirm the tests pass

```bash
cd backend && ./venv/Scripts/python.exe -m pytest -q
```

Expect **185 passed**. Worth a glance even though it is not on camera — if
something is broken you want to know now.

### 3.4 Start the backend

```bash
cd backend && ./venv/Scripts/python.exe app.py
```
```bash
curl -s http://localhost:8080/api/health
```

Expect `{"auth_required":false,"mock_mode":true,"status":"ok"}`.

### 3.5 Prime the trust ledger

**Do not skip this.** The ledger counts what *this server process* has run. On
a fresh backend it is all zeros, and your best slide is empty.

```bash
curl -s -X POST http://localhost:8080/api/exceptions/EXC-2026-0001/reasoning/generate > /dev/null
```
```bash
curl -s http://localhost:8080/api/analytics/trust | python -m json.tool
```

You want to see `"overrides_applied": 1` and `"fault_injection": {"injected": 1, "caught": 1}`.

### 3.6 Start the frontend

```bash
cd proofaegis-frontend && npm run dev
```

### 3.7 If you are demoing the deployed version

Cloud Run scales to zero. **Wake it up:**

```bash
curl -s https://proofaegis.web.app/api/health
```

Then hit it twice more. A cold start in the first ten seconds of a recording
reads as "this is slow", which is not the impression you want.

### 3.8 Set up the browser

- Sign in and leave the app on the **Dashboard**
- **Light theme** — it reads better on a projector and in compressed video
- Zoom to **100%**
- Close every other tab
- Hide bookmarks (`Ctrl`/`Cmd` + `Shift` + `B`)
- Dismiss the guided-tour offer banner so it does not appear mid-take
- Turn off notifications

### 3.9 Rehearse once, timed

Three minutes is short. Most first takes run 4:30. The fix is almost always
"stop explaining the UI and say what the finding means".

---

## 4. Recording settings

| Setting | Value |
|---|---|
| Resolution | 1920×1080 |
| Frame rate | 30 fps |
| Audio | 48 kHz, headset or external mic — **not** the laptop mic |
| Cursor highlight | On, if your recorder supports it |
| Webcam | Off, unless the submission asks for it |

Record **system audio off** unless you need it. Keyboard noise is the most
common avoidable problem.

---

## 5. The script, beat by beat

Adapt the words. Keep the structure.

### 0:00–0:20 — The frame

> "Every AP tool checks the invoice in front of it — against the purchase
> order, against the goods receipt. That's table stakes.
>
> The problem is the invoice that passes all three checks and is still wrong.
> A second copy of last month's bill. A supplier whose bank details quietly
> changed. **What passes is scarier than what fails.**
>
> This is ProofAegis."

*On screen: the entry page, then the Dashboard.*

### 0:20–1:00 — One hero case

> "Here's a blocked invoice from Chennai Industrial Supplies. I'll drop in the
> four documents — the invoice, the purchase order, the goods receipt, the
> rejection notice."

*Upload. Let the per-document progress run — it is real, not a spinner.*

> "It's read the PDFs, pulled out the fields, matched them, and found a price
> variance: **₹2,650 billed against ₹2,400 ordered. 10.42%, outside our 5%
> tolerance.**
>
> Every one of those numbers was computed in Python. No model touched them."

*Open the Match tab. Point at the tolerance band.*

> "This is the variance drawn to scale — the shaded zone is what's allowed, the
> marker is where this invoice landed."

*Switch to the Evidence graph.*

> "And this is why you can believe it. Source documents, extracted values, the
> rule that was applied, the finding, and where it routes."

*Hover the finding node — the chain lights up. Click a document node.*

> "Click any node and you land on the page it came from. Every number traces
> back to a document you can open."

### 1:00–1:45 — The cross-case catch

*Go to the Exceptions queue. Open a `duplicate_invoice` or
`payment_details_changed` case.*

> "Now the part a per-invoice system can't do.
>
> This invoice passes its own three-way match. Every comparison agrees. A
> normal AP tool would approve it.
>
> But **the same vendor's bank account changed since their last invoice** —
> and that fact isn't in this case. It's in a different one. You can only see
> it by reading across the whole workspace."

*Point at the cross-case banner at the top of the Match tab.*

> "Same for duplicates, for four instalments that each pass and together exceed
> the order, for a rate creeping three percent a month.
>
> **No single-invoice check can see any of this.**"

*Optional, if you have the time — the Investigate tab:*

> "And here the AI does the one thing it's actually good at: given the finding,
> what would explain it, and what document would settle each explanation. It
> tells you what to check. It never tells you what's true."

### 1:45–2:20 — The trust moment

**Slow down here. This is the beat that lands.**

*Back to EXC-2026-0001, Match tab, scroll to the trust row.*

> "Every AP demo you'll see today shows an AI being right. Here's ours being
> wrong.
>
> The reasoning agent said the financial impact was **₹31,200**. The
> deterministic layer computed **₹25,000**. They disagree by ₹6,200 — nearly
> 25%.
>
> **The code won.** It always wins. There's no gap size where we'd prefer the
> model's number."

*Go to Analytics, scroll to the Disagreement ledger.*

> "And we count it. Across the portfolio: how often the model answered, how
> often it disagreed, how often we overrode it.
>
> We keep three things separate — runs where a model actually answered, runs
> where it was unreachable and a template stood in, and values we corrupted on
> purpose to prove the check fires. Merging those would turn a measurement into
> a marketing number."

*Scroll to the Accuracy table.*

> "And this is measured, not asserted. 320 cases, eleven exception types, one
> command anyone can run. **The harness found five real bugs in our own code**
> — every one is listed, fixed, and has a regression test."

### 2:20–2:45 — Portfolio analytics

*Scroll to the top of Analytics.*

> "Resolving one invoice is reactive. This is where the next ones come from.
>
> Of 77 exceptions in this portfolio, **13 — worth ₹10.66 lakh — came from
> checks that read the rest of the workspace, not the invoice.** And nine of
> those thirteen scored a *full* three-way match on their own documents.
>
> **A per-invoice system would have paid them.**"

*Scroll to Vendors to act on.*

> "Ranked by money at risk, with the reason stated. Every figure on this screen
> is arithmetic over stored outcomes — no model produces a number here."

### 2:45–3:00 — Limitations

**Do not skip this. It is a scoring asset, not an apology.**

> "What we haven't built: the analytics run in Python over Firestore, not
> BigQuery — that's the obvious next step. No credit or debit notes, which
> interact directly with over-billing. No OCR by default, so a scanned PDF is
> refused rather than silently processed. Single workspace, INR only.
>
> All of it is in the README. **ProofAegis investigates what failed — and what
> shouldn't have passed.** Thank you."

---

## 6. Exact click path

Rehearse this until it is muscle memory.

```
 1. Entry page                                    (0:00)
 2. Sign in → Dashboard                           (0:12)
 3. "New case from PDFs"                          (0:20)
 4. Select all 4 PDFs from price_variance_001/
 5. Upload → watch per-document progress
 6. Case opens → Summary tab                      (0:38)
 7. Match tab → tolerance band                    (0:44)
 8. Evidence graph tab                            (0:52)
 9. Hover the Finding node → chain lights up
10. Click a Document node → source detail
11. Top nav → Exceptions                          (1:00)
12. Open a payment_details_changed case
13. Match tab → cross-case banner                 (1:10)
14. (optional) Investigate tab                    (1:30)
15. Command palette Ctrl+K → "EXC-2026-0001"      (1:45)
16. Match tab → scroll to trust row               (1:50)
17. Top nav → Analytics                           (2:05)
18. Scroll to Disagreement ledger
19. Scroll to Measured accuracy                   (2:12)
20. Scroll back to the top — cross-case panel     (2:20)
21. Scroll to Vendors to act on                   (2:35)
22. Hold on the cross-case headline               (2:45)
```

Step 15 uses `Ctrl`/`Cmd` + `K`. It is faster than navigating, and it shows the
palette exists without spending a beat on it.

---

## 7. Things that will go wrong

| Symptom | Cause | Fix |
|---|---|---|
| Trust row missing on EXC-2026-0001 | Reasoning has not been generated in this server process | Run the §3.5 curl. **Check this last, before recording** |
| Disagreement ledger all zeros | Same cause | Same fix |
| *"No eval run has been recorded"* | Eval JSON not written | Run both evals from §3.2 |
| First page load takes 5+ seconds | Cloud Run cold start | Hit `/api/health` three times before recording |
| *"Cannot reach the ProofAegis API"* | Backend not running | Start it; confirm with `curl` |
| Hypotheses say *"generic checklist"* | Gemini unreachable | Fine — it is honest. Either don't dwell, or use it: "with the model down it degrades to a fixed checklist, and says so" |
| Upload seems to hang | Extraction genuinely takes a few seconds | Let it run. The per-document progress is the point |
| Guided-tour banner appears mid-take | Not dismissed | Dismiss before recording |
| Analytics numbers differ from this guide | Portfolio regenerated with a different `--count` | Use `--count 320`, or just read what is on screen |

**If Gemini is down mid-recording, keep going.** The deterministic path handles
everything, the UI labels it honestly, and every number you quote is still
computed. That is the architecture working, not failing.

---

## 8. Give these zero seconds

They are built, they work, and they earn nothing on camera:

- The command palette *as a feature* — use it, don't explain it
- The guided tour
- Animated counters
- Theme toggle
- Sign-up flow
- Settings screen

Every second here is a second not spent on the cross-case catch or the trust
moment.

---

## 9. Editing notes

- **Cut the file picker.** Nobody needs four seconds of a dialog.
- **Do not speed up the upload.** The per-document progress is real work; a
  time-lapse makes it look faked.
- **Hold on the trust row for a full two seconds** before speaking. Let the
  struck-through ₹31,200 land.
- **Zoom in** on the trust row and the cross-case headline if your editor
  allows. They are the two frames worth freezing.
- **Captions** for the two key numbers — ₹10.66L and ₹31,200 → ₹25,000 — help
  if the video is watched without sound.
- **Keep the limitations section.** Cut elsewhere.

### Suggested title and description

> **ProofAegis — AP exception investigation that reads across cases**
>
> Most AP automation decides what to approve. ProofAegis investigates what
> failed — and what shouldn't have passed. Cross-case checks surface ₹10.66L
> that a per-invoice system would have paid, every finding traces to a source
> page, and the deterministic layer overrules the AI in public.
>
> Built with Google ADK, Gemini, Cloud Run, Firestore, Cloud Storage, Firebase
> Auth and Hosting. Synthetic data only.

---

## 10. Final checklist

Run this in the five minutes before you hit record.

```
[ ] Portfolio regenerated (--count 320)
[ ] Both evals run, JSON written
[ ] 231 tests passing
[ ] Backend up — /api/health returns ok
[ ] Trust ledger primed — overrides_applied: 1
[ ] Frontend up
[ ] Deployed service warmed (if demoing deployed)
[ ] Signed in, sitting on Dashboard
[ ] Light theme, 100% zoom
[ ] Tour banner dismissed
[ ] Sample PDFs two clicks away
[ ] Other tabs closed, bookmarks hidden
[ ] Notifications off
[ ] Mic tested
[ ] Rehearsed once, under 3:00
```

---

## See also

- [`PITCH.md`](PITCH.md) — the argument, written out
- [`USER_GUIDE.md`](USER_GUIDE.md) — every feature
- [`DEPLOYMENT_GUIDE.md`](DEPLOYMENT_GUIDE.md) — getting it running
