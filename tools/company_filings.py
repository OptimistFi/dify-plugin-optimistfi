from collections.abc import Generator
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from optimistfi import render
from optimistfi.respond import integer, respond, text

KINDS = {"events", "press_releases", "event_text", "red_flags"}


class CompanyFilingsTool(Tool):
    def _invoke(self, tool_parameters: dict[str, Any]) -> Generator[ToolInvokeMessage, None, None]:
        company = text(tool_parameters.get("company"))
        if not company:
            yield self.create_text_message("A company is needed: a ticker such as AAPL, a name or an SEC CIK.")
            return
        kind = text(tool_parameters.get("kind"))
        kind = kind if kind in KINDS else "events"
        arguments = {
            "entity": company,
            "kind": kind,
            "start": text(tool_parameters.get("start_date")),
            "end": text(tool_parameters.get("end_date")),
            "limit": integer(tool_parameters.get("limit"), 1, 50, 12),
        }
        yield from respond(
            self, tool_parameters, "get_filings", arguments, render.company_filings, "SEC filings", kind=kind
        )
