from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from cc_enrutador.config import ProviderModelConfig
from cc_enrutador.providers.anthropic_passthrough import AnthropicPassthroughProvider


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_anthropic_passthrough_preserves_subscription_headers() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["anthropic-version"] = request.headers.get("anthropic-version")
        captured["anthropic-beta"] = request.headers.get("anthropic-beta")
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
            },
        )
    )
    run(client.aclose())

    assert response["content"][0]["text"] == "ok"
    assert captured["authorization"] == "Bearer fake-claude-oauth"
    assert captured["anthropic-version"] == "2023-06-01"
    assert captured["anthropic-beta"] == "tools-test"
    assert captured["body"]["future_field"] == {"preserved": True}


def test_anthropic_passthrough_streams_raw_sse() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=b"event: message_stop\ndata: {\"type\":\"message_stop\"}\n\n",
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
        ):
            parts.append(part)
        return b"".join(parts)

    payload = run(collect())
    run(client.aclose())

    assert b"event: message_stop" in payload
