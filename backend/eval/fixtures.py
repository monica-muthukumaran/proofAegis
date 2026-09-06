"""
fixtures.py — a labelled AP portfolio, built as DOCUMENTS rather than as
answers.

WHY THIS EXISTS, AND WHY IT IS NOT scripts/generate_synthetic_data.py

That script writes a portfolio by choosing an exception type and then writing
that type into the record. It produces a realistic-looking population and it
can measure nothing, because the label and the "prediction" are the same
line of code. Scoring the pipeline against it would report 100% and mean
nothing at all.

This module inverts that. It generates the FIELD VALUES that would appear on
a purchase order, a goods receipt and an invoice, perturbs them with a named
defect, and then says nothing about the outcome. The pipeline reads those
values and decides for itself. Ground truth is the defect that was injected;
the prediction is whatever matching_service.py concludes. When the two
disagree, that is a real result — and several of them do disagree, which is
the point of building it this way.

GROUND TRUTH IS DERIVED FROM THE POLICY, NOT FROM THE MATCHER

A perturbation is not automatically an exception: a 1.4% price rise is inside
a 5% tolerance and the correct answer is `no_exception`. So each defect
declares the magnitude it applied, and `expected_outcome()` below turns that
into the label the DOCUMENTED policy requires — a second, deliberately
naive implementation of the rules, written from the specification rather
than from matching_service.py.

That duplication is the whole value. If the label came from the matcher, the
eval would be a tautology. Because it comes from an independent reading of
the spec, a disagreement means one of the two is wrong, and finding out which
is exactly the work an eval is supposed to cause.

Everything is fabricated and the RNG is seeded, so a reported score is
reproducible by anyone who runs the same command.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

# The vendor population and item catalogue are shared with the portfolio
# generator so the eval describes the same imaginary company the analytics
# screens do.
from scripts.generate_synthetic_data import LINE_ITEMS, SEED, VENDORS

# The workspace policy these fixtures are generated against. Ground truth is
# computed from these numbers, so a fixture set is only valid for the
# tolerance it was built with — run_eval.py applies the same pair to the
# matcher rather than reading the workspace settings, for that reason.
PRICE_TOLERANCE_PERCENT = 5.0
QUANTITY_TOLERANCE_PERCENT = 2.0

# How often a generated invoice carries no defect at all. Exception RATE is
# the headline metric and a rate needs a denominator; a set of nothing but
# defects would also make precision unmeasurable, because there would be no
# negatives to raise a false positive on.
CLEAN_SHARE = 0.58


@dataclass
class Fixture:
    """One scoreable case: the documents, and what should be concluded."""
    case_id: str
    vendor_name: str
    vendor_id: str
    business_unit: str
    created_at: datetime
    invoice: dict
    purchase_order: Optional[dict]
    goods_receipt: Optional[dict]
    # Earlier invoices from the same workspace that this case must be judged
    # against. Only the history-dependent defects populate this, and it is
    # what makes those defects genuinely undetectable from the case alone.
    prior_invoices: list[dict] = field(default_factory=list)
    defect: str = "none"
    defect_detail: dict = field(default_factory=dict)
    # A document condition applied on top of the defect — a vendor name
    # spelled differently, a tax basis that does not line up, a date the
    # extractor could not read. It never changes the correct answer, only
    # whether the pipeline can still reach it. See NOISE_MIX.
    noise: str = "none"
    expected_type: str = "no_exception"
    # Why this label, in one sentence — printed next to every disagreement so
    # a failure is readable without opening the generator.
    expected_because: str = ""


# ---------------------------------------------------------------------------
# The policy, restated
# ---------------------------------------------------------------------------
# Written from the specification, not from matching_service.py. Kept flat and
# obvious on purpose: the moment this starts sharing helpers with the matcher
# it stops being an independent check and becomes an echo.
#
# Precedence mirrors the documented ordering — what a reviewer must act on
# first. A duplicate outranks everything because the correct action is "do not
# pay this at all", which makes every variance on it irrelevant.
POLICY_PRECEDENCE = (
    "duplicate_invoice",
    "po_over_billed",
    "payment_details_changed",
    "tax_total_mismatch",
    "vendor_mismatch",
    "missing_purchase_order",
    "missing_goods_receipt",
    "quantity_variance",
    "price_variance",
    "recurring_suspected",
    "vendor_price_drift",
)


def expected_outcome(defect: str, detail: dict) -> tuple[str, str]:
    """
    (expected_exception_type, one-line justification).

    Returns `no_exception` whenever the injected defect is too small to breach
    the policy. Those cases matter more than the obvious ones: an eval whose
    every positive is a blatant 20% variance never discovers where the
    threshold actually sits.
    """
    if defect == "none":
        return "no_exception", "No defect was injected and every value agrees."

    if defect == "missing_purchase_order":
        return "missing_purchase_order", "No purchase order is on file to match against."

    if defect == "missing_goods_receipt":
        return "missing_goods_receipt", "No goods receipt or service confirmation is on file."

    if defect == "vendor_mismatch":
        return "vendor_mismatch", "The invoicing party differs from the party ordered from."

    if defect == "duplicate_invoice":
        return "duplicate_invoice", "This vendor and invoice number were already recorded."

    if defect == "recurring_billing":
        # The counterweight case. A regular series is NOT a duplicate, and an
        # eval that never generates one cannot detect that the duplicate rule
        # is firing on every retainer in the ledger.
        return ("recurring_suspected",
                "Same vendor and amount on a regular cadence — a billing schedule, not a re-submission.")

    if defect == "po_over_billed":
        return ("po_over_billed",
                "Several invoices, each acceptable alone, together exceed the order value.")

    if defect == "payment_details_changed":
        return ("payment_details_changed",
                "The vendor's bank details differ from those on their previous invoice.")

    if defect == "price_drift":
        return ("vendor_price_drift",
                "A unit price rising every month, each rise inside tolerance and the total above it.")

    if defect == "price_variance":
        breached = abs(detail["percent"]) > PRICE_TOLERANCE_PERCENT
        return (("price_variance", f"Unit price is {detail['percent']:+.2f}% against the order, "
                                   f"outside the {PRICE_TOLERANCE_PERCENT:g}% tolerance.")
                if breached else
                ("no_exception", f"Unit price is {detail['percent']:+.2f}%, inside the "
                                 f"{PRICE_TOLERANCE_PERCENT:g}% tolerance."))

    if defect == "quantity_variance":
        breached = abs(detail["percent"]) > QUANTITY_TOLERANCE_PERCENT
        return (("quantity_variance", f"Invoiced quantity is {detail['percent']:+.2f}% against the "
                                      f"receipt, outside the {QUANTITY_TOLERANCE_PERCENT:g}% tolerance.")
                if breached else
                ("no_exception", f"Invoiced quantity is {detail['percent']:+.2f}%, inside the "
                                 f"{QUANTITY_TOLERANCE_PERCENT:g}% tolerance."))

    if defect == "tax_total_mismatch":
        # Arithmetic on one page. The matcher allows the price tolerance here
        # as a deliberate over-allowance for rounding between systems, so the
        # policy restates the same allowance.
        breached = abs(detail["percent"]) > PRICE_TOLERANCE_PERCENT
        return (("tax_total_mismatch", f"Stated total is {detail['percent']:+.2f}% away from "
                                       f"subtotal + tax.")
                if breached else
                ("no_exception", f"Stated total is {detail['percent']:+.2f}% from subtotal + tax, "
                                 f"within rounding allowance."))

    raise ValueError(f"no policy defined for defect {defect!r}")


# ---------------------------------------------------------------------------
# Defect mix
# ---------------------------------------------------------------------------
# Weighted toward what a real AP function actually sees, with every type
# represented often enough that a per-type recall figure has more than a
# handful of cases behind it.
#
# Note the deliberate inclusion of `recurring_billing`, which is a NEGATIVE
# for the duplicate rule: it exists so the eval can catch the duplicate check
# firing on rent. A defect catalogue containing only true positives cannot
# measure precision.
DEFECT_MIX = (
    ("price_variance", 26),
    ("quantity_variance", 20),
    ("missing_goods_receipt", 15),
    ("missing_purchase_order", 7),
    ("duplicate_invoice", 7),
    ("recurring_billing", 6),
    ("vendor_mismatch", 5),
    ("tax_total_mismatch", 5),
    ("po_over_billed", 5),
    ("payment_details_changed", 3),
    ("price_drift", 3),
)


# ---------------------------------------------------------------------------
# Document conditions that are not defects
# ---------------------------------------------------------------------------
# Everything above generates a clean document carrying one clean defect, and a
# pipeline scored only on that reports a perfect number — because deciding
# whether 2,650 is more than 5% above 2,400 is arithmetic, and arithmetic does
# not have an error rate. A perfect score on an easy set is not a measurement,
# it is a description of the set.
#
# These are the conditions a real AP corpus carries that make the same
# decision hard. None of them changes what the correct answer IS: a 12% price
# variance is still a price variance when the vendor's name is spelled
# differently on the invoice. They change whether the pipeline can still see
# it, which is the thing worth measuring.
#
# They are applied on top of a defect, tracked, and reported in their own
# column, so the headline splits into "on clean documents" and "on documents
# that look like the ones people actually send".
NOISE_MIX = (
    # The same company, written the way two different systems write it. This
    # is the single most common reason a real three-way match fails for no
    # good reason.
    ("vendor_spelling", 30),
    # The order quoted ex-GST, the invoice stated gross. Comparing the two
    # totals is a units error rather than a variance.
    ("tax_basis_mismatch", 22),
    # An itemized document, so the scalar quantity/unit_price pair is absent
    # by design and the comparison has to happen line by line.
    ("itemized_only", 22),
    # A date the extractor could not read. Every history check that depends on
    # WHEN loses its footing.
    ("unreadable_date", 14),
    # A goods receipt that states no quantity — present, but useless.
    ("blank_receipt_quantity", 12),
)

# What share of cases get one. Kept low because these are the exceptions in a
# real corpus, not the norm, and a set where a third of documents are broken
# would understate the pipeline as badly as a clean set overstates it.
NOISE_SHARE = 0.18


def _apply_noise(rng: random.Random, fixture_parts: dict, noise: str) -> dict:
    """
    Degrades the documents without touching the injected defect.

    Returns the parts dict mutated in place. Each branch is a thing that
    genuinely happens to a document between a vendor's billing system and an
    AP inbox — none of them is a corruption invented to make the eval harder.
    """
    invoice = fixture_parts["invoice"]
    purchase_order = fixture_parts["purchase_order"]
    goods_receipt = fixture_parts["goods_receipt"]

    if noise == "vendor_spelling":
        # "Pvt. Ltd." on the order, "Private Limited" on the invoice. Every
        # variant here has to be a genuine textual difference — an earlier
        # version fell back to upper-casing the name, which the comparison
        # already folds away, so the condition was measuring nothing on the
        # vendors whose names carry no suffix to expand.
        name = invoice["vendor_name"]
        variants = [
            name.replace("Pvt. Ltd.", "Private Limited").replace("Ltd.", "Limited"),
            name.replace(" & ", " and "),
            f"M/s {name}",                       # the Indian invoicing convention
            name.replace(".", "").replace(",", ""),
            f"{name.rstrip('.')} .",
        ]
        invoice["vendor_name"] = next((v for v in variants if v != name), f"M/s {name}")

    elif noise == "tax_basis_mismatch":
        # The order is restated ex-tax: subtotal only, no tax line, total
        # equal to the subtotal.
        if purchase_order is not None:
            purchase_order["tax_amount"] = None
            purchase_order["total_amount"] = purchase_order["subtotal"]

    elif noise == "itemized_only":
        # A real multi-line document. The scalar pair is dropped, because
        # filling it with the first row's price beside a row count is exactly
        # the fabrication the extractor refuses to commit.
        for document in (invoice, purchase_order):
            if document is None:
                continue
            document["line_items"] = [{
                "description": document["line_item_description"],
                "quantity": document["quantity"],
                "unit_price": document["unit_price"],
                "amount": round(document["quantity"] * document["unit_price"], 2),
            }]
            document["quantity"] = None
            document["unit_price"] = None

    elif noise == "unreadable_date":
        invoice["invoice_date"] = None

    elif noise == "blank_receipt_quantity":
        if goods_receipt is not None:
            goods_receipt["received_quantity"] = None

    return fixture_parts


def _weighted(rng: random.Random, pairs) -> str:
    total = sum(w for _, w in pairs)
    roll = rng.uniform(0, total)
    upto = 0.0
    for value, weight in pairs:
        upto += weight
        if roll <= upto:
            return value
    return pairs[-1][0]


def _variance_percent(rng: random.Random, tolerance: float) -> float:
    """A perturbation magnitude that straddles the tolerance boundary.

    A third of these land INSIDE the tolerance on purpose. Those are the
    cases that decide whether a threshold is implemented as documented, and
    they are the ones that expose an off-by-one at the boundary — which a
    generator that only ever produced blatant 20% breaches would never reach.
    """
    if rng.random() < 0.33:
        return round(rng.uniform(0.2, tolerance * 0.95), 2)
    return round(rng.uniform(tolerance * 1.05, tolerance * 5), 2)


# ---------------------------------------------------------------------------
# Document construction
# ---------------------------------------------------------------------------
def _bank(rng: random.Random, vendor_id: str) -> dict:
    """Stable per vendor, so a CHANGE is a real event rather than noise."""
    digits = abs(hash(vendor_id)) % 10**10
    return {
        "bank_account_number": f"{digits:010d}",
        "bank_ifsc": f"HDFC0{abs(hash(vendor_id + 'ifsc')) % 10**6:06d}",
        "bank_name": "HDFC Bank",
    }


def _money_shape(quantity: float, unit_price: float, description: str) -> dict:
    """Subtotal, tax and total, consistent with each other by construction.

    Every fixture states tax explicitly so that both sides of a comparison are
    on the same basis. A tax-inclusive total measured against a tax-exclusive
    order is a units error that the matcher correctly refuses to score, and a
    fixture set that produced them at random would be measuring that refusal
    instead of measuring matching.
    """
    subtotal = round(quantity * unit_price, 2)
    tax = round(subtotal * 0.18, 2)
    return {
        "line_item_description": description,
        "quantity": quantity,
        "unit_price": unit_price,
        "subtotal": subtotal,
        "tax_amount": tax,
        "total_amount": round(subtotal + tax, 2),
        "currency": "INR",
    }


def _invoice(number: str, vendor: str, po_number: str, date: datetime,
             quantity: float, unit_price: float, description: str, bank: dict) -> dict:
    return {
        "invoice_number": number,
        "vendor_name": vendor,
        "po_number": po_number,
        "invoice_date": date.date().isoformat(),
        "line_items": [],
        **_money_shape(quantity, unit_price, description),
        **bank,
    }


def _purchase_order(po_number: str, vendor: str, quantity: float, unit_price: float,
                    description: str) -> dict:
    return {
        "po_number": po_number,
        "vendor_name": vendor,
        "line_items": [],
        **_money_shape(quantity, unit_price, description),
    }


def _goods_receipt(po_number: str, quantity: float, date: datetime) -> dict:
    return {
        "receipt_number": f"GRN-{po_number[-5:]}",
        "po_number": po_number,
        "received_quantity": quantity,
        "receipt_date": date.date().isoformat(),
    }


def _prior_record(case_id: str, extraction: dict, uploaded_at: datetime) -> dict:
    """An earlier invoice, in the shape history_service reads."""
    return {
        "document_id": f"DOC-{case_id}-INV",
        "exception_id": case_id,
        "document_type": "vendor_invoice",
        "processing_state": "completed",
        "uploaded_at": uploaded_at.isoformat(),
        "extraction": extraction,
    }


# ---------------------------------------------------------------------------
# One fixture
# ---------------------------------------------------------------------------
def build_fixture(rng: random.Random, index: int, now: datetime, months: int) -> Fixture:
    vendor_id, vendor_name, business_unit, _risk = rng.choice(VENDORS)
    serial = 7000 + index
    case_id = f"EVAL-{serial:05d}"
    po_number = f"PO-2026-{serial:05d}"
    invoice_number = f"INV-2026-{serial:05d}"
    description = rng.choice(LINE_ITEMS)
    bank = _bank(rng, vendor_id)

    # Quantity and price drawn together, so a services line is billed once
    # rather than 250 times. Drawing them independently produces invoices of a
    # size no company has ever raised.
    tier = _weighted(rng, (("consumable", 45), ("equipment", 35), ("service", 20)))
    if tier == "consumable":
        quantity = float(rng.choice([50, 100, 120, 200, 250, 500]))
        unit_price = float(rng.choice([45, 120, 315, 630]))
    elif tier == "equipment":
        quantity = float(rng.choice([5, 10, 25, 40, 50]))
        unit_price = float(rng.choice([850, 1200, 2400, 4500, 9000]))
    else:
        quantity = float(rng.choice([1, 1, 1, 2, 3]))
        unit_price = float(rng.choice([45000, 90000, 180000, 240000]))

    age_days = (rng.random() ** 1.7) * months * 30
    created = now - timedelta(days=age_days, hours=rng.randint(0, 23))

    defect = "none" if rng.random() < CLEAN_SHARE else _weighted(rng, DEFECT_MIX)
    detail: dict = {}

    purchase_order = _purchase_order(po_number, vendor_name, quantity, unit_price, description)
    goods_receipt = _goods_receipt(po_number, quantity, created)
    invoice = _invoice(invoice_number, vendor_name, po_number, created,
                       quantity, unit_price, description, bank)
    priors: list[dict] = []

    if defect == "price_variance":
        percent = _variance_percent(rng, PRICE_TOLERANCE_PERCENT)
        detail = {"percent": percent}
        billed_price = round(unit_price * (1 + percent / 100), 2)
        invoice = _invoice(invoice_number, vendor_name, po_number, created,
                           quantity, billed_price, description, bank)

    elif defect == "quantity_variance":
        percent = _variance_percent(rng, QUANTITY_TOLERANCE_PERCENT)
        detail = {"percent": percent}
        # The receipt is what SHOULD have been invoiced; the invoice bills
        # more. Perturbing the receipt downward rather than the invoice upward
        # keeps the invoice's own arithmetic self-consistent.
        received = round(quantity / (1 + percent / 100), 2)
        goods_receipt = _goods_receipt(po_number, received, created)
        # A quantity below the tolerance floor rounds away entirely on small
        # orders; recompute the achieved percentage from the actual numbers so
        # ground truth describes the documents rather than the intent.
        detail["percent"] = round((quantity - received) / received * 100, 2)

    elif defect == "missing_goods_receipt":
        goods_receipt = None

    elif defect == "missing_purchase_order":
        purchase_order = None

    elif defect == "vendor_mismatch":
        other = rng.choice([v for v in VENDORS if v[0] != vendor_id])
        invoice = dict(invoice, vendor_name=other[1])
        detail = {"ordered_from": vendor_name, "billed_by": other[1]}

    elif defect == "tax_total_mismatch":
        percent = _variance_percent(rng, PRICE_TOLERANCE_PERCENT)
        detail = {"percent": percent}
        # The total is inflated above the subtotal and tax that justify it —
        # the oldest invoice manipulation there is, and checkable from one page.
        honest_total = invoice["total_amount"]
        invoice = dict(invoice, total_amount=round(honest_total * (1 + percent / 100), 2))

    elif defect == "duplicate_invoice":
        # The same invoice number from the same vendor, already on file.
        earlier = created - timedelta(days=rng.randint(3, 40))
        priors = [_prior_record(f"EVAL-{serial:05d}-P1",
                                _invoice(invoice_number, vendor_name, po_number, earlier,
                                         quantity, unit_price, description, bank),
                                earlier)]
        detail = {"first_seen": earlier.date().isoformat()}

    elif defect == "recurring_billing":
        # A retainer: the same vendor and the same amount, monthly, under a
        # different number each time. Everything the duplicate rule looks at
        # matches; the cadence is what says it is not a duplicate.
        priors = []
        for step in range(1, rng.randint(3, 6)):
            # A few days of jitter, because real invoices are not raised by a
            # metronome and a check that only tolerates exact periods would
            # be useless on real data.
            earlier = created - timedelta(days=step * 30 + rng.randint(-3, 3))
            priors.append(_prior_record(
                f"EVAL-{serial:05d}-R{step}",
                _invoice(f"INV-2026-{serial:05d}-{step}", vendor_name,
                         f"PO-2026-{serial:05d}-{step}", earlier,
                         quantity, unit_price, description, bank),
                earlier))
        detail = {"occurrences": len(priors) + 1, "cadence": "monthly"}

    elif defect == "po_over_billed":
        # Two earlier invoices against the SAME order, each individually
        # unremarkable, together taking the running total past the order
        # value. Nothing in this case's own documents is wrong.
        share = rng.uniform(0.45, 0.6)
        for step in (1, 2):
            earlier = created - timedelta(days=step * rng.randint(20, 45))
            part_qty = round(quantity * share, 2)
            priors.append(_prior_record(
                f"EVAL-{serial:05d}-B{step}",
                _invoice(f"INV-2026-{serial:05d}-B{step}", vendor_name, po_number, earlier,
                         part_qty, unit_price, description, bank),
                earlier))
        detail = {"instalments": len(priors) + 1}

    elif defect == "payment_details_changed":
        earlier = created - timedelta(days=rng.randint(25, 120))
        priors = [_prior_record(f"EVAL-{serial:05d}-P1",
                                _invoice(f"INV-2026-{serial:05d}-X", vendor_name,
                                         f"PO-2026-{serial:05d}-X", earlier,
                                         quantity, unit_price, description, bank),
                                earlier)]
        # This invoice names a different account for the same vendor.
        changed = dict(bank, bank_account_number=f"{(int(bank['bank_account_number']) + 7) % 10**10:010d}")
        invoice = _invoice(invoice_number, vendor_name, po_number, created,
                           quantity, unit_price, description, changed)
        detail = {"previous_account": bank["bank_account_number"],
                  "current_account": changed["bank_account_number"]}

    elif defect == "price_drift":
        # A rate creeping up ~3% a month against its own order every month.
        # Each invoice clears its own three-way match; four months later the
        # rate is materially above where it started.
        step_percent = rng.uniform(2.5, 4.0)
        count = rng.randint(4, 6)
        for step in range(count - 1, 0, -1):
            earlier = created - timedelta(days=step * 30 + rng.randint(-2, 2))
            stepped = round(unit_price * (1 + step_percent / 100) ** (count - 1 - step), 2)
            priors.append(_prior_record(
                f"EVAL-{serial:05d}-D{step}",
                _invoice(f"INV-2026-{serial:05d}-D{step}", vendor_name,
                         f"PO-2026-{serial:05d}-D{step}", earlier,
                         quantity, stepped, description, bank),
                earlier))
        latest = round(unit_price * (1 + step_percent / 100) ** (count - 1), 2)
        invoice = _invoice(invoice_number, vendor_name, po_number, created,
                           quantity, latest, description, bank)
        # The order is raised at the drifted rate too, so this invoice's own
        # match is clean and only the trend across orders can see it.
        purchase_order = _purchase_order(po_number, vendor_name, quantity, latest, description)
        goods_receipt = _goods_receipt(po_number, quantity, created)
        detail = {"per_month_percent": round(step_percent, 2), "invoices": count}

    # A document condition, applied AFTER the defect and without changing what
    # the correct answer is. `vendor_mismatch` is excluded because its defect
    # IS a vendor-name difference, and layering a spelling variant on top
    # would make the fixture's own label ambiguous.
    noise = "none"
    if rng.random() < NOISE_SHARE and defect != "vendor_mismatch":
        noise = _weighted(rng, NOISE_MIX)
        parts = _apply_noise(rng, {
            "invoice": invoice,
            "purchase_order": purchase_order,
            "goods_receipt": goods_receipt,
        }, noise)
        invoice, purchase_order, goods_receipt = (
            parts["invoice"], parts["purchase_order"], parts["goods_receipt"])

    expected_type, because = expected_outcome(defect, detail)
    return Fixture(
        noise=noise,
        case_id=case_id,
        vendor_name=vendor_name,
        vendor_id=vendor_id,
        business_unit=business_unit,
        created_at=created,
        invoice=invoice,
        purchase_order=purchase_order,
        goods_receipt=goods_receipt,
        prior_invoices=priors,
        defect=defect,
        defect_detail=detail,
        expected_type=expected_type,
        expected_because=because,
    )


def build_portfolio(count: int = 320, months: int = 12, seed: int = SEED) -> list[Fixture]:
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    return [build_fixture(rng, index, now, months) for index in range(count)]
