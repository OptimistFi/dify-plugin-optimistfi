from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from optimistfi import render
from optimistfi.respond import integer, respond, text


class CongressTradesTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        ticker = text(tool_parameters.get("ticker"))
        member = text(tool_parameters.get("member"))
        if not ticker and not member:
            yield self.create_text_message("A ticker (such as NVDA) or a House member's name is needed.")
            return
        arguments = {"ticker": ticker, "member": member, "limit": integer(tool_parameters.get("limit"), 1, 100, 25)}
        yield from respond(
            self, tool_parameters, "get_congress_trades", arguments, render.congress_trades, "Congressional trades"
        )
