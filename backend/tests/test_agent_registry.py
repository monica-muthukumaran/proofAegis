"""
test_agent_registry.py — keeping the agent disclosure honest.

`/api/settings/mode` publishes which agents call a model and which model each
one calls, and the UI prints that in a badge. That makes it a DISCLOSURE
SURFACE: the product's whole claim is that a reviewer can check what produced
a figure, and a badge naming the wrong model is worse than no badge, because
it is a specific, checkable, confident falsehood.

The registry in routes/settings.py is a hand-written table, chosen over
reflection so that a human can read it. The cost of that choice is that it can
drift out of step with the code it describes — an agent gets rewired to the
other model and the table keeps announcing the old one, silently and forever.

These tests are what makes that cost affordable. They read the agent modules
and assert the table still matches, so the drift fails a build instead of
misinforming an auditor.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, ".")

from config import config  # noqa: E402
from routes.settings import AGENT_REGISTRY, _agent_status  # noqa: E402

SERVICES = Path(__file__).resolve().parent.parent / "services"


def _module_for(key: str) -> Path:
    return SERVICES / f"{key}_agent.py"


@pytest.mark.parametrize("key,label,attr,stage", AGENT_REGISTRY)
def test_every_registered_agent_names_a_module_that_exists(key, label, attr, stage):
    """The table must not describe an agent that has been deleted or renamed."""
    assert _module_for(key).is_file(), (
        f"AGENT_REGISTRY lists '{key}', but services/{key}_agent.py does not exist. "
        "Either the agent was renamed and the registry was not updated, or the "
        "registry gained an entry for something that is not an agent."
    )


@pytest.mark.parametrize("key,label,attr,stage", AGENT_REGISTRY)
def test_every_registered_agent_names_a_real_config_attribute(key, label, attr, stage):
    """A model name the UI prints must actually be configured somewhere."""
    assert hasattr(config, attr), (
        f"AGENT_REGISTRY says '{key}' uses config.{attr}, which does not exist. "
        "The badge would print null for this agent."
    )
    assert getattr(config, attr), f"config.{attr} is empty; the badge would print nothing."


@pytest.mark.parametrize("key,label,attr,stage", AGENT_REGISTRY)
def test_registry_model_matches_the_model_the_agent_actually_passes(key, label, attr, stage):
    """The heart of this file.

    Reads the agent's source and asserts it passes the config attribute the
    registry claims. This is what catches the drift the registry's own comment
    warns about — an agent moved from GEMINI_MODEL to GEMINI_REASONING_MODEL
    while the table kept advertising the old one.
    """
    source = _module_for(key).read_text(encoding="utf-8")
    used = set(re.findall(r"config\.(GEMINI_[A-Z_]*MODEL)", source))

    assert used, (
        f"services/{key}_agent.py passes no config.GEMINI_*MODEL at all, but "
        f"AGENT_REGISTRY lists it as calling config.{attr}. Either it stopped "
        "calling a model (drop it from the registry) or it now sources the "
        "model some other way (the registry can no longer describe it)."
    )
    assert attr in used, (
        f"AGENT_REGISTRY says '{key}' uses config.{attr}, but "
        f"services/{key}_agent.py actually uses {sorted(used)}. The agent badge "
        "would name the wrong model."
    )


def test_no_model_calling_agent_is_missing_from_the_registry():
    """The reverse direction: an agent that calls a model must be disclosed.

    An agent silently added and never registered is the failure that matters
    most — the badge would under-report what the product is sending to a
    model, which is precisely the thing a reviewer is using it to check.
    """
    registered = {key for key, _, _, _ in AGENT_REGISTRY}
    calls_a_model = {
        path.stem[: -len("_agent")]
        for path in SERVICES.glob("*_agent.py")
        if re.search(r"config\.GEMINI_[A-Z_]*MODEL", path.read_text(encoding="utf-8"))
    }
    missing = calls_a_model - registered
    assert not missing, (
        f"These agents pass a model but are absent from AGENT_REGISTRY: {sorted(missing)}. "
        "The agent badge would under-report what this deployment sends to a model."
    )


def test_stage_is_one_the_ui_knows_how_to_group():
    """The UI groups rows by stage; an unknown stage falls out of the order."""
    known = {"extract", "reason", "investigate", "resolve"}
    for key, _, _, stage in AGENT_REGISTRY:
        assert stage in known, (
            f"'{key}' has stage '{stage}', which AgentBadge.js does not know how to "
            f"order. Add it to STAGE_ORDER/STAGE_LABEL there, or use one of {sorted(known)}."
        )


@pytest.mark.parametrize("live", [True, False])
def test_every_row_reports_the_single_shared_live_verdict(live):
    """`live` is passed in, not recomputed per row.

    A per-agent liveness that could disagree with the banner's own
    `gemini_active` would let the UI say "Agent off" beside a row marked live.
    """
    rows = _agent_status(live)
    assert rows, "the registry produced no rows"
    assert all(row["live"] is live for row in rows)


def test_status_rows_carry_everything_the_badge_renders():
    """A missing key renders as a blank cell rather than an error, so it has to
    be asserted rather than noticed."""
    for row in _agent_status(True):
        for field in ("key", "label", "model", "stage", "live"):
            assert field in row, f"agent row is missing '{field}': {row}"
        assert row["model"], f"agent '{row['key']}' has no model name to print"
