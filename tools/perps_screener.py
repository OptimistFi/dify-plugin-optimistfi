from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from optimistfi import render
from optimistfi.respond import integer, respond, text

# Which filters each view takes, as the server answered on 2026-10-28. A filter a view does not take
# fails the whole call, so it is left out here and the answer says so.
VENUE_VIEWS = {"open_interest", "whales", "new_listings", "exchanges"}
NO_MARKET_VIEWS = {"trending", "funding", "liquidations"}
NEEDS_MARKET_VIEWS = {"options", "basis"}


class PerpsScreenerTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        view = text(tool_parameters.get("view"))
        view = view if view in render.VIEW_TITLES else "trending"
        market = text(tool_parameters.get("market"))
        venue = text(tool_parameters.get("venue"))
        if view in NEEDS_MARKET_VIEWS and not market:
            yield self.create_text_message(f"The {view} view reads one market at a time, such as BTC or ETH.")
            return
        left_out = []
        if market and view in NO_MARKET_VIEWS:
            left_out.append("market")
            market = None
        if venue and view not in VENUE_VIEWS:
            left_out.append("venue")
            venue = None
        arguments = {
            "view": view,
            "market": market,
            "venue": venue,
            "asset_class": text(tool_parameters.get("asset_class")),
            "window": text(tool_parameters.get("window")),
            "limit": integer(tool_parameters.get("limit"), 1, 25, 10),
        }
        yield from respond(
            self,
            tool_parameters,
            "get_perps_market",
            arguments,
            render.perps_screener,
            "Perps screener",
            view=view,
            left_out=left_out,
        )
