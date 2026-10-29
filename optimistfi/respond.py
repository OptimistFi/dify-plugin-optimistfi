"""The messages each tool sends back to Dify.

A plain function, not a Tool base class: Dify loads each tool module by its one
Tool subclass, so a shared subclass imported into every module would collide.
"""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from typing import Any

from dify_plugin import Tool
from dify_plugin.entities.tool import ToolInvokeMessage

from optimistfi import client, render


def text(value: Any) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None


def integer(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return default
    return max(low, min(number, high))


def amount(value: Any) -> float | int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return int(number) if number.is_integer() else number


def respond(
    tool: Tool,
    parameters: Mapping[str, Any],
    mcp_tool: str,
    arguments: dict[str, Any],
    renderer: Callable[..., render.Summary],
    title: str,
    **render_kwargs: Any,
) -> Generator[ToolInvokeMessage, None, None]:
    reply = client.call(mcp_tool, arguments)
    if reply.error:
        yield tool.create_text_message(reply.error)
        yield tool.create_variable_message("error", reply.error)
        return
    summary = render.safely(renderer, reply.records, title, **render_kwargs)
    yield tool.create_text_message(summary.text)
    if parameters.get("detail", "full") != "summary":
        yield tool.create_json_message({"records": reply.records})
    for name, value in summary.variables.items():
        if value is not None:
            yield tool.create_variable_message(name, value)
