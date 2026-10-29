from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from optimistfi import render
from optimistfi.respond import integer, respond, text


class InsiderTradesTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        company = text(tool_parameters.get("company"))
        if not company:
            yield self.create_text_message("A company is needed: a ticker such as AAPL, a name or an SEC CIK.")
            return
        arguments = {
            "entity": company,
            "start": text(tool_parameters.get("start_date")),
            "end": text(tool_parameters.get("end_date")),
            "limit": integer(tool_parameters.get("limit"), 1, 100, 25),
        }
        yield from respond(
            self, tool_parameters, "get_insider_trades", arguments, render.insider_trades, "Insider trades"
        )
