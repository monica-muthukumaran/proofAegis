"""
test_seed_context.py — the other half of the seeded data's job.

Per-user workspaces took the seeded corpus out of everybody's queue. This
module is what it does instead: calibrate the reasoning agent's severity
scale, for every workspace including an empty one.

Two things are on trial, and they pull in opposite directions.

  * It must actually reach the model. A calibration set nobody sends is a
    comment, and the whole argument for keeping the seeded data was that it
    still earns its place for a user whose own queue is empty.
  * It must carry nothing identifying across the workspace boundary. This is
    the ONE path in the application that is deliberately unscoped, so it is
    the one path where a leak would not be caught by any tenancy test.

The financial guardrail is asserted here too, from the other side: whatever
the calibration does to the model's severity judgement, it must not be able
to move a number.
"""
from __future__ import annotations

import re
import sys

sys.path.insert(0, ".")

from schemas import ExceptionType  # noqa: E402
from services import seed_context  # noqa: E402

# Every value an exemplar is allowed to hold, as a closed vocabulary.
#
# A substring sweep for "vendor" or "amount" was the obvious check and it is
# the wrong one: `vendor_mismatch` and `payment_details_changed` are exception
# TYPE names, so the sweep fails on correct output while still passing on a
# vendor called "Acme". Closed vocabularies invert that — a real vendor name,
# an invoice number, or a rupee figure cannot be a member of any of these
# sets, so anything identifying fails by construction rather than by
# resembling a word somebody blacklisted.
_MAGNITUDE = re.compile(r"^(0|~1e\d+)$")
_SCORE_BANDS = {"95-100", "80-94", "60-79", "below-60", "unknown"}
_RISK_LEVELS = {"low", "medium", "high", "critical"}


def _flatten(value, out=None):
    """Every scalar in a nested structure, as strings — so an assertion about
    what a payload contains cannot be dodged by nesting."""
    out = [] if out is None else out
    if isinstance(value, dict):
        for key, item in value.items():
            out.append(str(key))
            _flatten(item, out)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _flatten(item, out)
    else:
        out.append(str(value))
    return out


# ---------------------------------------------------------------------------
# What crosses the boundary
# ---------------------------------------------------------------------------
class TestNothingIdentifyingLeaves:
    def test_an_exemplar_has_exactly_the_whitelisted_fields(self):
        for exemplar in seed_context.severity_exemplars():
            assert set(exemplar) == set(seed_context.EXEMPLAR_FIELDS)

    def test_every_value_comes_from_a_closed_vocabulary(self):
        """The real containment assertion.

        A vendor name, an invoice number and a rupee figure are all excluded
        not because they were listed as forbidden, but because there is
        nowhere in an exemplar for a free-form string to sit: exception types
        come from the schema enum, risk and band from fixed sets, and impact
        matches a magnitude pattern. Widen the exemplar and this fails.
        """
        valid_types = {t.value for t in ExceptionType}
        for exemplar in seed_context.severity_exemplars():
            assert exemplar["exception_type"] in valid_types
            assert exemplar["risk_level"] in _RISK_LEVELS
            assert exemplar["match_score_band"] in _SCORE_BANDS
            assert _MAGNITUDE.match(exemplar["impact_magnitude"]), exemplar

    def test_a_vendor_name_in_the_source_does_not_survive_into_an_exemplar(self):
        """Stated directly, against a case that carries every identifying
        field the seed format has."""
        exemplar = seed_context._exemplar({
            "exception_type": "price_variance",
            "risk_level": "high",
            "financial_impact": 265000,
            "match_score": 72,
            "vendor_name": "Chennai Industrial Supplies Pvt. Ltd.",
            "invoice_id": "INV-2026-1187",
            "exception_id": "EXC-2026-0001",
        })
        flat = " ".join(_flatten(exemplar))
        assert "Chennai" not in flat
        assert "INV-2026-1187" not in flat
        assert "EXC-2026-0001" not in flat
        assert "265000" not in flat

    def test_the_note_is_fixed_prose_and_carries_no_corpus_data(self):
        """The note has to use the words "vendor" and "invoice" — that is how
        it tells the model these examples are about neither. So assert instead
        that it is a constant rather than something built from the corpus."""
        note = seed_context.calibration_block()["note"]
        for exemplar in seed_context.severity_exemplars():
            assert exemplar["impact_magnitude"] not in note
            assert exemplar["match_score_band"] not in note

    def test_impact_is_an_order_of_magnitude_and_never_a_figure(self):
        for exemplar in seed_context.severity_exemplars():
            magnitude = exemplar["impact_magnitude"]
            assert magnitude == "0" or magnitude.startswith("~1e"), magnitude

    def test_magnitude_keeps_the_scale_and_discards_the_number(self):
        assert seed_context._magnitude(4302.58) == "~1e3"
        assert seed_context._magnitude(4999.99) == "~1e3"
        assert seed_context._magnitude(265000) == "~1e5"
        # A rounded amount must not be reconstructible: everything in a decade
        # collapses to the same string.
        assert seed_context._magnitude(1000) == seed_context._magnitude(9999)

    def test_magnitude_survives_the_values_a_real_corpus_contains(self):
        for value in (None, 0, 0.4, -8200, "not a number"):
            assert isinstance(seed_context._magnitude(value), str)

    def test_the_exemplar_is_built_from_a_whitelist_not_a_filter(self):
        """A case carrying extra fields must produce the same four keys. This
        is the difference between a construction and a blacklist, and it is
        the reason a new seed field cannot quietly widen the payload."""
        exemplar = seed_context._exemplar({
            "exception_type": "price_variance",
            "risk_level": "high",
            "financial_impact": 1234.5,
            "match_score": 71,
            "vendor_name": "Chennai Industrial Supplies Pvt. Ltd.",
            "invoice_id": "INV-2026-1187",
            "some_field_added_next_year": "secret",
        })
        assert set(exemplar) == set(seed_context.EXEMPLAR_FIELDS)


# ---------------------------------------------------------------------------
# What the sample is
# ---------------------------------------------------------------------------
class TestTheSampleIsUsable:
    def test_there_is_a_calibration_set_at_all(self):
        assert seed_context.corpus_stats()["available"] is True
        assert seed_context.severity_exemplars()

    def test_clean_invoices_are_excluded(self):
        """243 of the 320 seeded cases are clean. Sampling them would teach
        the model that almost everything is low risk — true of the corpus,
        false of the queue, because a clean invoice never reaches the
        reasoning agent at all."""
        types = {e["exception_type"] for e in seed_context.severity_exemplars()}
        assert "no_exception" not in types

    def test_the_sample_spans_several_exception_types(self):
        types = {e["exception_type"] for e in seed_context.severity_exemplars()}
        assert len(types) >= 3

    def test_the_sample_spans_more_than_one_risk_level(self):
        """An anchor that only ever shows 'low' is an anchor that teaches the
        model to answer 'low'."""
        levels = {e["risk_level"] for e in seed_context.severity_exemplars()}
        assert len(levels) >= 2

    def test_it_is_capped(self):
        assert len(seed_context.severity_exemplars()) <= seed_context.MAX_EXEMPLARS

    def test_it_is_deterministic(self):
        """A prompt that changes between two runs makes every difference in
        the output impossible to attribute."""
        seed_context.severity_exemplars.cache_clear()
        first = seed_context.severity_exemplars()
        seed_context.severity_exemplars.cache_clear()
        assert seed_context.severity_exemplars() == first

    def test_score_bands_cover_the_whole_range(self):
        assert seed_context._score_band(100) == "95-100"
        assert seed_context._score_band(94) == "80-94"
        assert seed_context._score_band(60) == "60-79"
        assert seed_context._score_band(0) == "below-60"
        assert seed_context._score_band(None) == "unknown"


# ---------------------------------------------------------------------------
# It reaches the model, and it reaches every workspace
# ---------------------------------------------------------------------------
class TestItReachesThePrompt:
    def test_the_agent_sends_the_calibration_with_the_case(self):
        """Asserted against the payload the agent actually builds. A
        calibration set that is assembled and then never sent is a comment
        with extra steps, and nothing else in the suite would notice."""
        from services.exception_agent import build_prompt_payload

        payload = build_prompt_payload(_match_result(), [], "")
        assert payload["severity_calibration"]["examples"]
        assert payload["severity_calibration"]["examples"] == [
            dict(e) for e in seed_context.severity_exemplars()]

    def test_the_case_own_facts_are_still_the_bulk_of_the_prompt(self):
        """Calibration is an addition, not a replacement. The deterministic
        match result, the documents and the rejection notice are what the
        model is actually judging."""
        from services.exception_agent import build_prompt_payload

        payload = build_prompt_payload(
            _match_result(), [{"document_id": "DOC-1", "document_type": "vendor_invoice"}],
            "Damaged on arrival")
        assert payload["matching_results"]["financial_impact"] == 25000.0
        assert payload["document_references"][0]["document_id"] == "DOC-1"
        assert payload["rejection_notice_text"] == "Damaged on arrival"

    def test_the_prompt_omits_the_section_entirely_when_there_is_no_corpus(self, monkeypatch):
        from services.exception_agent import build_prompt_payload

        monkeypatch.setattr(seed_context, "_corpus", lambda: ())
        seed_context.severity_exemplars.cache_clear()
        try:
            assert "severity_calibration" not in build_prompt_payload(_match_result(), [], "")
        finally:
            seed_context.severity_exemplars.cache_clear()

    def test_the_calibration_does_not_depend_on_a_workspace(self):
        """The point of keeping the seeded data. seed_context takes no
        workspace argument anywhere — a user whose own queue is empty still
        gets a severity scale consistent with every case this product has
        classified."""
        import inspect

        for name in ("severity_exemplars", "calibration_block", "corpus_stats"):
            signature = inspect.signature(getattr(seed_context, name))
            assert not signature.parameters, f"{name} takes arguments"

    def test_the_block_tells_the_model_not_to_treat_it_as_evidence(self):
        note = seed_context.calibration_block()["note"].lower()
        assert "not" in note
        assert "evidence" in note or "cite" in note

    def test_the_agent_instruction_forbids_it_moving_a_number(self):
        """Calibration is for judgement and language. The money is still the
        deterministic matcher's alone, and the instruction has to say so —
        the guardrail in _enforce_guardrails is the enforcement, this is the
        instruction that stops the model trying."""
        from services.exception_agent import INSTRUCTION

        lowered = INSTRUCTION.lower()
        assert "severity_calibration" in lowered
        assert "not evidence" in lowered
        assert "change a single number" in lowered

    def test_no_corpus_means_no_section_rather_than_an_empty_one(self, monkeypatch):
        """None, not []. "Here are zero examples" reads to a model as an
        instruction to be cautious, and would quietly shift every severity it
        returns."""
        monkeypatch.setattr(seed_context, "_corpus", lambda: ())
        seed_context.severity_exemplars.cache_clear()
        try:
            assert seed_context.calibration_block() is None
        finally:
            seed_context.severity_exemplars.cache_clear()


def _match_result():
    """A minimal but VALID MatchResult — built through the schema rather than
    hand-written as a dict, so a schema change breaks this loudly instead of
    letting the prompt assertions run against a shape the agent never sees."""
    from schemas import Comparison, ExceptionType, MatchResult

    return MatchResult(
        exception_type=ExceptionType.PRICE_VARIANCE,
        comparisons=[Comparison(
            field="unit_price", expected_value=2400, actual_value=2650,
            absolute_variance=250, percentage_variance=10.42,
            tolerance_percent=5, classification="outside_tolerance",
            evaluable=True)],
        match_score=72,
        financial_impact=25000.0,
        financial_impact_basis="Unit price above PO.",
        risk_level="high",
        recommended_owner="Procurement",
    )
