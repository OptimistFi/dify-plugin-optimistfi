from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from optimistfi import render
from optimistfi.respond import respond, text

WINDOWS = {"1d", "7d", "30d", "90d"}


class PerpHistoryTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        market = text(tool_parameters.get("market"))
        if not market:
            yield self.create_text_message("A market is needed, such as BTC, ETH, NVDA or gold.")
            return
        window = text(tool_parameters.get("window"))
        arguments = {"entity": market, "window": window if window in WINDOWS else "7d"}
        yield from respond(
            self, tool_parameters, "get_perps_history", arguments, render.perp_history, "Perpetual futures history"
        )
