"""Each Dify tool end to end, with the OptimistFi endpoint mocked by a recorded reply."""

import importlib
from unittest.mock import patch

import pytest
import yaml
from dify_plugin.entities.tool import ToolInvokeMessage

from optimistfi.client import Reply, parse

from conftest import ROOT

TOOLS = {
    "insider_trades": (
        "InsiderTradesTool",
        {"company": "NVDA", "limit": 10},
        "insider_nvda",
        "get_insider_trades",
        {"entity": "NVDA", "start": None, "end": None, "limit": 10},
    ),
    "congress_trades": (
        "CongressTradesTool",
        {"ticker": "NVDA"},
        "congress_nvda",
        "get_congress_trades",
        {"ticker": "NVDA", "member": None, "limit": 25},
    ),
    "company_filings": (
        "CompanyFilingsTool",
        {"company": "AAPL", "kind": "red_flags"},
        "filings_flags_aapl",
        "get_filings",
        {"entity": "AAPL", "kind": "red_flags", "start": None, "end": None, "limit": 12},
    ),
    "company_calendar": (
        "CompanyCalendarTool",
        {"company": "AAPL"},
        "calendar_aapl",
        "get_calendar",
        {"entity": "AAPL", "limit": 12},
    ),
}


def run(name: str, parameters: dict, reply: Reply):
    module = importlib.import_module(f"tools.{name}")
    tool = getattr(module, TOOLS[name][0]).from_credentials({})
    with patch("optimistfi.respond.client.call", return_value=reply) as call:
        messages = list(tool.invoke(parameters))
    return messages, call


def declared_outputs(name: str) -> set[str]:
    spec = yaml.safe_load((ROOT / "tools" / f"{name}.yaml").read_text())
    return set(spec["output_schema"]["properties"])


@pytest.mark.parametrize("name", TOOLS)
def test_tool_calls_the_mcp_tool_and_returns_summary_data_and_variables(name):
    from conftest import fixture

    _, parameters, recorded, mcp_tool, arguments = TOOLS[name]
    messages, call = run(name, parameters, parse(fixture(recorded)))

    assert call.call_args.args == (mcp_tool, arguments)
    kinds = [m.type for m in messages]
    assert kinds[0] == ToolInvokeMessage.MessageType.TEXT
    assert kinds[1] == ToolInvokeMessage.MessageType.JSON
    assert "records" in messages[1].message.json_object
    variables = {m.message.variable_name for m in messages if m.type == ToolInvokeMessage.MessageType.VARIABLE}
    assert variables, "a tool returns workflow variables"
    assert variables <= declared_outputs(name), variables - declared_outputs(name)


@pytest.mark.parametrize("name", TOOLS)
def test_summary_only_leaves_out_the_full_data(name):
    from conftest import fixture

    _, parameters, recorded, _, _ = TOOLS[name]
    messages, _ = run(name, parameters | {"detail": "summary"}, parse(fixture(recorded)))

    assert ToolInvokeMessage.MessageType.JSON not in [m.type for m in messages]


def test_a_failed_call_returns_the_reason_and_an_error_variable():
    messages, _ = run("insider_trades", {"company": "AAPL"}, Reply(error="OptimistFi answered with HTTP 503."))

    assert messages[0].message.text == "OptimistFi answered with HTTP 503."
    assert messages[1].message.variable_name == "error"


@pytest.mark.parametrize("name", ["insider_trades", "company_filings", "company_calendar", "congress_trades"])
def test_a_missing_required_input_is_explained_without_a_call(name):
    messages, call = run(name, {}, Reply())

    call.assert_not_called()
    assert "needed" in messages[0].message.text
