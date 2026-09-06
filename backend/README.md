# ProofAegis Backend

Documentation for this service lives in the **project root**, so there is one
copy of everything rather than three that drift apart.

| You want | Read |
|---|---|
| How the backend is built — modules, matching, agents, data model, every endpoint | [`../ARCHITECTURE_BACKEND.md`](../ARCHITECTURE_BACKEND.md) |
| Google services, commands, links | [`../GOOGLE_STACK.md`](../GOOGLE_STACK.md) |
| Running it locally, and deploying it | [`../DEPLOYMENT_GUIDE.md`](../DEPLOYMENT_GUIDE.md) |
| Limitations, stated plainly | [`../README.md`](../README.md) |

## Quick start

```bash
python -m venv venv
```
```bash
source venv/Scripts/activate
```
```bash
pip install -r requirements.txt
```
```bash
python app.py
```

Runs on `http://localhost:8080`. With no cloud credentials it uses an
in-memory datastore and on-disk file storage — fully working, nothing to
configure.

## Tests

```bash
python -m pytest -q
```

**185 tests.** The suite pins `STORAGE_BACKEND=local` and `USE_MOCK_DATA=true`,
so a machine holding real credentials can never have a test run reach a live
bucket.

## Evals

Two harnesses, kept apart so a failure is never ambiguous between "read the
document wrong" and "reasoned about it wrong".

```bash
python -m eval.run_eval --count 320 --json data/generated/eval_report.json
```
```bash
python -m eval.extraction_eval --json data/generated/extraction_report.json
```

Ground truth comes from an independent reading of the documented policy, not
from the code being graded — see
[`../ARCHITECTURE_BACKEND.md` §13](../ARCHITECTURE_BACKEND.md#13-the-eval-harness).

## Synthetic data

```bash
python scripts/generate_synthetic_data.py --count 320
```
```bash
python scripts/generate_synthetic_pdfs.py
```
```bash
python scripts/generate_synthetic_pdfs.py --all-layouts --out data/layout_variants
```

> Synthetic data only. No real company, contract, or payment is represented.
