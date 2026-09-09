"""
test_exception_type_coverage.py — every finding the backend can produce must
have a severity in the queue.

The exception queue paints each finding with a tone from TYPE_TONE in
proofaegis-frontend/src/components/exceptions/ExceptionTable.js. A type that
is missing from that table does not error — it falls through to the neutral
grey default, which is the same grey a cleared invoice wears.

That is a silent UNDER-REPORT, and it is the failure mode that matters here:
the reviewer is scanning a queue for what needs attention, and a real finding
rendered as "nothing to see" is worse than one rendered too loudly. It already
happened once — `vendor_price_drift`, which schemas.py itself describes as the
price equivalent of PO_OVER_BILLED, shipped rendering as undifferentiated
grey.

This test crosses the language boundary on purpose. The enum is the source of
truth for what can be produced, the JS table is the source of truth for how it
is shown, and nothing else checks that the second keeps up with the first.
Adding a type to the enum without a tone should fail a build, not quietly
change what an analyst sees.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")

from schemas import ExceptionType  # noqa: E402

TABLE = (
    Path(__file__).resolve().parents[2]
    / "proofaegis-frontend" / "src" / "components" / "exceptions" / "ExceptionTable.js"
)

# Tones the theme actually defines (styles.css / theme-tokens.css `.badge-*`).
VALID_TONES = {"critical", "exception", "warning", "verified", "neutral", "accent"}

# `no_exception` is rendered by its own branch in the component ("Clean"), not
# through TYPE_TONE, so it is legitimately absent from the table.
RENDERED_ELSEWHERE = {"no_exception"}


def _type_tone() -> dict[str, str]:
    """Parse the TYPE_TONE object literal out of the component."""
    source = TABLE.read_text(encoding="utf-8")
    block = re.search(r"const TYPE_TONE = \{(.*?)\n\};", source, re.S)
    assert block, f"could not find the TYPE_TONE literal in {TABLE}"
    body = block.group(1)
    # Strip comments so a type name mentioned in prose is not read as an entry.
    body = re.sub(r"//[^\n]*", "", body)
    return dict(re.findall(r"([a-z_]+)\s*:\s*\"([a-z]+)\"", body))


def test_the_table_is_parseable():
    """If this fails the rest of the file is vacuous, so assert it separately."""
    assert TABLE.is_file(), f"{TABLE} not found — did the component move?"
    assert _type_tone(), "parsed TYPE_TONE is empty"


def test_every_exception_type_has_a_tone():
    tones = _type_tone()
    expected = {t.value for t in ExceptionType} - RENDERED_ELSEWHERE
    missing = sorted(expected - set(tones))
    assert not missing, (
        f"These ExceptionType values have no entry in TYPE_TONE: {missing}. "
        "They will render in the queue as neutral grey — the same grey a "
        "cleared invoice wears — so a real finding would read as nothing to "
        f"see. Add each to TYPE_TONE in {TABLE.name}."
    )


def test_no_tone_for_a_type_that_cannot_be_produced():
    """The reverse: a stale entry means the table describes a finding that no
    longer exists, which is dead code that reads as current."""
    tones = _type_tone()
    known = {t.value for t in ExceptionType}
    unknown = sorted(set(tones) - known)
    assert not unknown, (
        f"TYPE_TONE has entries for types the backend cannot produce: {unknown}. "
        "Either the enum member was renamed and the table was not updated, or "
        "the entry is left over from a type that was removed."
    )


@pytest.mark.parametrize("name,tone", sorted(_type_tone().items()))
def test_tone_is_one_the_theme_defines(name, tone):
    assert tone in VALID_TONES, (
        f"TYPE_TONE['{name}'] is '{tone}', which is not a badge tone the theme "
        f"defines. Valid: {sorted(VALID_TONES)}. An unknown tone renders as an "
        "unstyled badge."
    )


def test_critical_is_reserved():
    """`critical` is the loudest tone in the product. It is worth asserting
    that it stays reserved for the two findings that earn it, because the way
    this degrades is gradual — one more type at a time until the loudest tone
    means nothing."""
    tones = _type_tone()
    critical = {k for k, v in tones.items() if v == "critical"}
    assert critical == {"duplicate_invoice", "payment_details_changed"}, (
        f"`critical` is now used for {sorted(critical)}. It is reserved for "
        "findings where money may already have moved or that are a known "
        "fraud vector. Widening it is a deliberate product decision — update "
        "this test with the reasoning if that is what you intend."
    )
