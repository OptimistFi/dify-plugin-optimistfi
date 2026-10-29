from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from optimistfi import render
from optimistfi.respond import respond, text


class PerpMarketTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        market = text(tool_parameters.get("market"))
        if not market:
            yield self.create_text_message("A market is needed, such as BTC, ETH, NVDA or gold.")
            return
        yield from respond(
            self, tool_parameters, "get_perps", {"entity": market}, render.perp_market, "Perpetual futures market"
        )
