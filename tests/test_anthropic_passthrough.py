from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from cc_enrutador.config import ProviderModelConfig
from cc_enrutador.providers.anthropic_passthrough import AnthropicPassthroughProvider
from cc_enrutador.providers.base import ProviderError, ProviderResponseError


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_anthropic_passthrough_preserves_subscription_headers() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["anthropic-version"] = request.headers.get("anthropic-version")
        captured["anthropic-beta"] = request.headers.get("anthropic-beta")
        captured["accept-encoding"] = request.headers.get("accept-encoding")
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "msg_1",
                "type": "message",
                "role": "assistant",
                "model": "claude-test",
                "content": [{"type": "text", "text": "ok"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 1, "output_tokens": 1},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config = ProviderModelConfig(
        provider="anthropic_subscription",
        model="passthrough",
        api_base="https://api.anthropic.test",
    )
    provider = AnthropicPassthroughProvider(config, client=client)

    response = run(
        provider.complete(
            {
                "model": "claude-test",
                "max_tokens": 10,
                "messages": [{"role": "user", "content": "hello"}],
                "future_field": {"preserved": True},
            },
            {
                "authorization": "Bearer fake-claude-oauth",
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "tools-test",
                "accept-encoding": "gzip, deflate, br, zstd",
            },
        )
    )
    run(client.aclose())

    assert response["content"][0]["text"] == "ok"
    assert captured["authorization"] == "Bearer fake-claude-oauth"
    assert captured["anthropic-version"] == "2023-06-01"
    assert captured["anthropic-beta"] == "tools-test"
    assert captured["accept-encoding"] == "identity"
    assert captured["body"]["future_field"] == {"preserved": True}


def test_anthropic_passthrough_reports_response_encoding_on_invalid_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/json", "content-encoding": "br"},
            content=b"\x8b\xe4\x00",
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AnthropicPassthroughProvider(
        ProviderModelConfig(
            provider="anthropic_subscription",
            model="passthrough",
            api_base="https://api.anthropic.test",
        ),
        client=client,
    )

    with pytest.raises(ProviderError) as caught:
        run(provider.complete({"messages": []}, {}))
    run(client.aclose())

    message = str(caught.value)
    assert "undecodable JSON" in message
    assert "status=200" in message
    assert "content_encoding='br'" in message
    assert "body_bytes=3" in message


def test_anthropic_passthrough_streams_raw_sse() -> None:
    captured_url = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_url
        captured_url = str(request.url)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b'event: message_stop\ndata: {"type":"message_stop"}\n\n',
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AnthropicPassthroughProvider(
        ProviderModelConfig(
            provider="anthropic_subscription",
            model="passthrough",
            api_base="https://api.anthropic.test",
        ),
        client=client,
    )

    async def collect() -> bytes:
        parts = []
        async for part in provider.stream(
            {"stream": True, "messages": [{"role": "user", "content": "hello"}]},
            {"authorization": "Bearer fake-claude-oauth"},
            "beta=true",
        ):
            parts.append(part)
        return b"".join(parts)

    payload = run(collect())
    run(client.aclose())

    assert b"event: message_stop" in payload
    assert captured_url == "https://api.anthropic.test/v1/messages?beta=true"


def test_anthropic_passthrough_reports_upstream_error_details() -> None:
    captured_url = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_url
        captured_url = str(request.url)
        return httpx.Response(
            400,
            headers={
                "request-id": "req_upstream_123",
                "retry-after": "7",
                "x-should-retry": "false",
            },
            json={
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "Unsupported beta capability",
                },
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = AnthropicPassthroughProvider(
        ProviderModelConfig(
            provider="anthropic_subscription",
            model="passthrough",
            api_base="https://api.anthropic.test",
        ),
        client=client,
    )

    with pytest.raises(ProviderResponseError) as caught:
        run(provider.complete({"messages": []}, {}, "beta=true&feature=test"))
    run(client.aclose())

    assert captured_url == "https://api.anthropic.test/v1/messages?beta=true&feature=test"
    message = str(caught.value)
    assert "status=400" in message
    assert "invalid_request_error" in message
    assert "req_upstream_123" in message
    assert "Unsupported beta capability" in message
    assert caught.value.status_code == 400
    assert caught.value.headers["retry-after"] == "7"
    assert caught.value.headers["x-should-retry"] == "false"
    assert caught.value.headers["request-id"] == "req_upstream_123"
    assert caught.value.content == (
        b'{"type":"error","error":{"type":"invalid_request_error",'
        b'"message":"Unsupported beta capability"}}'
    )
