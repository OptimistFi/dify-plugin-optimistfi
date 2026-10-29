import json
from unittest.mock import MagicMock, patch

import httpx

from optimistfi import client

from conftest import sse, tool_reply


def test_payload_drops_unset_arguments():
    sent = client.payload("get_insider_trades", {"start": None, "end": "", "entity": "AAPL"})

    assert sent == {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "get_insider_trades", "arguments": {"entity": "AAPL"}},
    }


def test_structured_content_result_list_is_the_records():
    reply = client.parse(tool_reply({"result": [{"type": "insider_trade"}, {"type": "insider_trade"}]}))

    assert reply.error is None
    assert reply.records == [{"type": "insider_trade"}, {"type": "insider_trade"}]


def test_each_text_part_is_one_record():
    reply = client.parse(tool_reply(texts=['{"type": "red_flag", "n": 1}', '{"type": "red_flag", "n": 2}']))

    assert [r["n"] for r in reply.records] == [1, 2]


def test_a_text_part_that_is_not_json_is_kept_as_text():
    assert client.parse(tool_reply(texts=["plain words"])).records == [{"text": "plain words"}]


def test_the_reply_is_found_among_other_stream_messages():
    notice = sse({"jsonrpc": "2.0", "method": "notifications/progress", "params": {"progress": 1}})
    reply = client.parse(notice + tool_reply({"result": [{"ok": True}]}) + notice)

    assert reply.records == [{"ok": True}]


def test_tool_error_reads_as_the_server_wrote_it():
    reply = client.parse(tool_reply(texts=["kind: Input should be 'events'"], is_error=True))

    assert reply.error == "kind: Input should be 'events'"
    assert reply.records == []


def test_json_rpc_error_is_reported():
    body = sse({"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "Invalid params"}})

    assert client.parse(body).error == "OptimistFi could not run the request: Invalid params"


@patch("optimistfi.client.httpx.post")
def test_call_sends_the_mcp_headers(post):
    response = MagicMock(text=tool_reply({"result": []}))
    response.raise_for_status.return_value = None
    post.return_value = response

    client.call("get_insider_trades", {"entity": "AAPL"})

    kwargs = post.call_args.kwargs
    assert post.call_args.args == (client.ENDPOINT,)
    assert kwargs["headers"]["Accept"] == "application/json, text/event-stream"
    assert kwargs["json"]["params"] == {"name": "get_insider_trades", "arguments": {"entity": "AAPL"}}
    assert kwargs["timeout"] == client.TIMEOUT_SECONDS


@patch("optimistfi.client.httpx.post", side_effect=httpx.ReadTimeout("slow"))
def test_timeout_explains_itself(_post):
    error = client.call("get_filings", {"entity": "AAPL", "kind": "red_flags"}).error

    assert "did not answer within 100 seconds" in error


@patch("optimistfi.client.httpx.post")
def test_http_status_is_reported(post):
    request = httpx.Request("POST", client.ENDPOINT)
    response = httpx.Response(503, request=request, text="unavailable")
    post.return_value = response

    assert client.call("get_insider_trades", {"entity": "AAPL"}).error == "OptimistFi answered with HTTP 503."


@patch("optimistfi.client.httpx.post", side_effect=httpx.ConnectError("refused"))
def test_network_error_is_reported(_post):
    assert (
        client.call("get_insider_trades", {"entity": "AAPL"}).error == "OptimistFi could not be reached: ConnectError."
    )


def test_unreadable_body_is_an_error_not_a_crash():
    with patch("optimistfi.client.httpx.post") as post:
        response = MagicMock(text="data: {not json\n\n")
        response.raise_for_status.return_value = None
        post.return_value = response

        assert (
            client.call("get_insider_trades", {"entity": "AAPL"}).error == "OptimistFi sent a reply that is not JSON."
        )


def test_recorded_reply_parses():
    from conftest import fixture

    reply = client.parse(fixture("insider_nvda"))

    assert reply.error is None
    assert reply.records[0]["entity"]["ticker"] == "NVDA"
    assert json.dumps(reply.records)  # the records are plain JSON, ready for a json message
