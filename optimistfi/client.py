"""One call to OptimistFi's public MCP endpoint.

The endpoint speaks MCP's streamable HTTP transport: a JSON-RPC `tools/call`
goes in and the reply comes back as server-sent events. No key is needed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

ENDPOINT = "https://mcp.optimistfi.com/mcp"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "User-Agent": "optimistfi-dify-plugin/0.0.1",
}
TIMEOUT_SECONDS = 100.0


@dataclass
class Reply:
    """What a call returned: the records, or an error a reader can act on."""

    records: list[Any] = field(default_factory=list)
    error: str | None = None


def payload(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool, "arguments": {k: v for k, v in arguments.items() if v not in (None, "")}},
    }


def parse(body: str) -> Reply:
    messages = [line[5:].strip() for line in body.splitlines() if line.startswith("data:")] or [body]
    reply: dict[str, Any] = {}
    for message in messages:
        if not message:
            continue
        decoded = json.loads(message)
        if isinstance(decoded, dict) and decoded.get("id") == 1:
            reply = decoded
    if "error" in reply:
        detail = (reply["error"] or {}).get("message") or "no detail"
        return Reply(error=f"OptimistFi could not run the request: {detail}")
    result = reply.get("result")
    if not isinstance(result, dict):
        return Reply(error="OptimistFi sent no result for this request.")
    parts = [part.get("text", "") for part in result.get("content", []) if part.get("type") == "text"]
    if result.get("isError"):
        return Reply(error=" ".join(parts) or "OptimistFi could not run the request.")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        records = structured.get("result", structured)
        return Reply(records=records if isinstance(records, list) else [records])
    # Without structured content, each text part carries one JSON record.
    records: list[Any] = []
    for part in parts:
        try:
            decoded = json.loads(part)
        except ValueError:
            decoded = {"text": part}
        records.extend(decoded if isinstance(decoded, list) else [decoded])
    return Reply(records=records)


def call(tool: str, arguments: dict[str, Any], timeout: float = TIMEOUT_SECONDS) -> Reply:
    try:
        response = httpx.post(ENDPOINT, headers=HEADERS, json=payload(tool, arguments), timeout=timeout)
        response.raise_for_status()
        return parse(response.text)
    except httpx.TimeoutException:
        return Reply(
            error=(
                f"OptimistFi did not answer within {timeout:.0f} seconds. This view is computed on request; "
                "a later call is usually answered from the finished build."
            )
        )
    except httpx.HTTPStatusError as error:
        return Reply(error=f"OptimistFi answered with HTTP {error.response.status_code}.")
    except httpx.RequestError as error:
        return Reply(error=f"OptimistFi could not be reached: {type(error).__name__}.")
    except ValueError:
        return Reply(error="OptimistFi sent a reply that is not JSON.")
