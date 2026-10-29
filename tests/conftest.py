import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(ROOT))


def fixture(name: str) -> str:
    """A reply recorded from mcp.optimistfi.com on 2026-10-28, as the server sent it."""
    return (FIXTURES / f"{name}.sse").read_text()


def sse(message: dict) -> str:
    return f"event: message\ndata: {json.dumps(message)}\n\n"


def tool_reply(structured=None, texts=(), is_error=False) -> str:
    result: dict = {"content": [{"type": "text", "text": t} for t in texts], "isError": is_error}
    if structured is not None:
        result["structuredContent"] = structured
    return sse({"jsonrpc": "2.0", "id": 1, "result": result})
