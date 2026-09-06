"""
test_mcp_manifest.py — the MCP tool manifest must not drift from the code.

backend/mcp/tools.yaml necessarily restates constants that live in Python:
which statuses count as open, which exception types are cross-case, the SLA
threshold, the match score that means "a full three-way match". SQL in a YAML
file cannot import them.

Restated constants drift. That is not a hypothesis about this codebase — the
eval harness already caught the vendor-identity rule implemented twice, in
two modules, differently, and a duplicate invoice went unreported because of
it. The same failure here would be worse, because it would be silent: an
agent would confidently report a cross-case total that omits a whole category
of finding, and every screen in the product would still show the right one.

So every constant this file duplicates is asserted against its source.

None of these tests need a Toolbox server, a BigQuery project, or an API key.
They read the YAML as text and compare it to what Python says.
"""
from __future__ import annotations

import os
import re

import pytest

yaml = pytest.importorskip("yaml", reason="pyyaml parses the tool manifest")

from schemas import CROSS_CASE_TYPE_VALUES  # noqa: E402
from services import analytics_gateway, portfolio_agent  # noqa: E402
from services.analytics_service import (  # noqa: E402
    AGE_BUCKETS,
    CLEAN_MATCH_SCORE,
    CLEAN_TYPE,
    OPEN_STATUSES,
    SLA_BREACH_DAYS,
)

MANIFEST_PATH = portfolio_agent.MANIFEST_PATH


@pytest.fixture(scope="module")
def raw() -> str:
    with open(MANIFEST_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def manifest(raw: str) -> dict:
    # `${VAR}` and `${VAR:default}` are Toolbox's own substitution syntax and
    # are not valid YAML values unquoted in every position; neutralise them
    # before parsing so this test reads structure rather than environment.
    return yaml.safe_load(re.sub(r"\$\{[^}]+\}", "ENV", raw))


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------
def test_manifest_exists_and_parses(manifest):
    assert manifest["sources"], "no sources declared"
    assert manifest["tools"], "no tools declared"
    assert manifest["toolsets"], "no toolsets declared"


def test_every_analytic_is_exposed_as_a_tool(manifest):
    """A sixth analytic must not be added to the product and silently not
    exist here — the agent would answer questions about five-sixths of the
    portfolio with no indication anything was missing."""
    assert set(manifest["tools"]) == set(analytics_gateway.ANALYTIC_NAMES)


def test_the_agents_toolset_contains_exactly_those_tools(manifest):
    toolset = manifest["toolsets"][portfolio_agent.TOOLSET]
    assert set(toolset) == set(analytics_gateway.ANALYTIC_NAMES)


def test_every_tool_is_a_parameterised_statement_not_a_sql_accepting_tool(manifest):
    """THE safety property of this file.

    An agent with a tool that takes SQL can compose an aggregation, and a
    figure a model composed is a figure a model can get wrong. Every tool
    here must be a pre-written statement whose parameters are scalars.
    """
    for name, tool in manifest["tools"].items():
        assert tool["kind"] == "bigquery-sql", f"{name}: unexpected tool kind"
        assert "statement" in tool, f"{name}: no statement — is this a raw SQL tool?"
        for param in tool.get("parameters", []):
            assert param["type"] in ("integer", "string", "float", "boolean"), \
                f"{name}.{param['name']}: only scalar parameters"
            assert param["name"] not in ("sql", "query", "statement"), \
                f"{name}: takes {param['name']} — an agent must not supply SQL"


def test_every_tool_has_a_description_an_agent_can_route_on(manifest):
    """A tool the model cannot tell apart from another is a tool it will call
    at random. These descriptions are the routing logic."""
    for name, tool in manifest["tools"].items():
        description = (tool.get("description") or "").strip()
        assert len(description) > 80, f"{name}: description too thin to route on"
        for param in tool.get("parameters", []):
            assert (param.get("description") or "").strip(), \
                f"{name}.{param['name']}: undocumented parameter"


def test_every_tool_bounds_its_window(manifest):
    """Same cost control as the executor. A tool with no date predicate is a
    full-table scan an agent can trigger by asking a vague question."""
    for name, tool in manifest["tools"].items():
        statement = tool["statement"]
        assert "TIMESTAMP_SUB" in statement, f"{name}: no bounded window"
        params = {p["name"] for p in tool.get("parameters", [])}
        assert params & {"days", "months"}, f"{name}: window is not a parameter"


def test_vendor_risk_caps_its_row_count(manifest):
    """The one tool that returns a list rather than a single row."""
    statement = manifest["tools"]["vendor_risk"]["statement"]
    assert "LIMIT @limit" in statement


# ---------------------------------------------------------------------------
# Constants — every value the YAML restates, checked against its source
# ---------------------------------------------------------------------------
def test_open_statuses_match_the_python_definition(raw):
    """`OPEN_STATUSES` decides what "at risk" means. If the YAML lists four of
    the five, every value-at-risk figure the agent reports is understated and
    nothing anywhere says so."""
    for tool in ("portfolio_summary", "vendor_risk", "ageing"):
        assert tool in raw
    for status in OPEN_STATUSES:
        assert f"'{status}'" in raw, f"{status} missing from tools.yaml"

    # And nothing extra: a status listed here but not in OPEN_STATUSES would
    # inflate the same figure.
    quoted = set(re.findall(r"'(awaiting_\w+|exception_detected|assigned)'", raw))
    assert quoted == set(OPEN_STATUSES)


def test_cross_case_types_match_schemas(raw):
    """The headline claim of the product. A cross-case type missing here means
    the agent reports a smaller 'what a per-invoice system would have paid'
    figure than the analytics screen does, from the same table."""
    statement = re.search(r"exception_type IN \(([^)]+)\)", raw, re.S)
    assert statement, "cross_case_value no longer lists its types"
    listed = set(re.findall(r"'(\w+)'", statement.group(1)))
    assert listed == set(CROSS_CASE_TYPE_VALUES)


def test_clean_type_matches(raw):
    assert f"'{CLEAN_TYPE}'" in raw


def test_sla_threshold_matches(raw):
    assert f"age_days > {SLA_BREACH_DAYS}" in raw, \
        f"SLA is {SLA_BREACH_DAYS} days in Python; tools.yaml disagrees"


def test_clean_match_score_matches(raw):
    assert f"match_score >= {CLEAN_MATCH_SCORE}" in raw, \
        f"a full match is {CLEAN_MATCH_SCORE} in Python; tools.yaml disagrees"


def test_ageing_buckets_match(raw):
    """The bucket labels the UI renders. A mismatch produces a chart with a
    bucket nothing falls into and a bucket that does not exist."""
    for label, _, _ in AGE_BUCKETS:
        assert f"'{label}'" in raw, f"ageing bucket {label!r} missing"


# ---------------------------------------------------------------------------
# The agent's own boundaries
# ---------------------------------------------------------------------------
def test_agent_reports_not_configured_rather_than_answering(monkeypatch):
    """No toolbox URL means no answer — not an answer composed from memory."""
    monkeypatch.setattr(portfolio_agent.config, "MCP_TOOLBOX_URL", "")
    result = portfolio_agent.ask("Which vendors should I audit?")
    assert result["available"] is False
    assert result["reason"] == "not_configured"
    assert "answer" not in result


def test_agent_returns_no_answer_when_the_toolbox_is_unreachable(monkeypatch):
    """The degraded-mode rule. An agent that answers a portfolio question with
    its tools down produces confident prose with no data behind it."""
    monkeypatch.setattr(portfolio_agent.config, "MCP_TOOLBOX_URL", "http://127.0.0.1:1")
    monkeypatch.setattr(portfolio_agent.config, "GEMINI_API_KEY", "test-key")

    def boom():
        raise portfolio_agent.ToolboxUnavailable("connection refused")

    monkeypatch.setattr(portfolio_agent, "_load_tools", boom)
    result = portfolio_agent.ask("Which vendors should I audit?")
    assert result["available"] is False
    assert result["reason"] == "toolbox_unreachable"
    assert "answer" not in result


def test_agent_asks_for_a_named_toolset_not_every_tool():
    """A server that later gains a write tool must not silently hand it to a
    read-only agent."""
    assert portfolio_agent.TOOLSET == "proofaegis-analytics"


def test_instruction_forbids_stating_an_unsourced_number():
    instruction = portfolio_agent.INSTRUCTION.lower()
    assert "never state a number" in instruction
    assert "tool" in instruction
