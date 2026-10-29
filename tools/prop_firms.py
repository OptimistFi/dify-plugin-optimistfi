from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from optimistfi import render
from optimistfi.respond import amount, respond, text


class PropFirmsTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        on_chain = tool_parameters.get("on_chain")
        arguments = {
            "firm": text(tool_parameters.get("firm")),
            "account_usd": amount(tool_parameters.get("account_usd")),
            "max_price_usd": amount(tool_parameters.get("max_price_usd")),
            "rule": text(tool_parameters.get("rule")),
            "asset": text(tool_parameters.get("asset")),
            "country": text(tool_parameters.get("country")),
            "on_chain": True if on_chain is True else None,
        }
        yield from respond(
            self,
            tool_parameters,
            "get_prop_firms",
            arguments,
            render.prop_firms,
            "Prop firms",
            firm=arguments["firm"],
            account_usd=arguments["account_usd"],
        )
