from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import cc_enrutador.providers.litellm_provider as provider_module
from cc_enrutador.config import ProviderModelConfig
from cc_enrutador.providers.litellm_provider import LiteLLMProvider


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_litellm_provider_uses_configured_credentials(
    monkeypatch: Any,
) -> None:
    captured: dict[str, Any] = {}

    async def completion(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "id": "response_1",
            "choices": [
                {
                    "message": {"content": "ok", "tool_calls": None},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }

    monkeypatch.setenv("TEST_PROVIDER_KEY", "configured-provider-key")
    config = ProviderModelConfig(
        provider="litellm",
        model="openai/test-model",
        api_base="https://provider.invalid/v1",
        api_key_env="TEST_PROVIDER_KEY",
    )
    provider = LiteLLMProvider(config, completion=completion)

    response = run(
        provider.complete(
            {"messages": [{"role": "user", "content": "hello"}]},
            {"authorization": "Bearer fake-claude-oauth"},
        )
    )

    assert response["content"] == [{"type": "text", "text": "ok"}]
    assert captured["api_key"] == "configured-provider-key"
    assert captured["model"] == "openai/test-model"
    assert "fake-claude-oauth" not in repr(captured)


def test_litellm_provider_streams_incrementally() -> None:
    async def completion(**kwargs: Any) -> Any:
        async def chunks() -> Any:
            yield {
                "id": "stream_1",
                "choices": [{"delta": {"content": "a"}, "finish_reason": None}],
            }
            yield {
                "id": "stream_1",
                "choices": [{"delta": {"content": "b"}, "finish_reason": "stop"}],
            }

        return chunks()

    config = ProviderModelConfig(provider="litellm", model="test/model")
    provider = LiteLLMProvider(config, completion=completion)

    async def collect() -> bytes:
        parts = []
        async for part in provider.stream(
            {"messages": [{"role": "user", "content": "hello"}]},
            {},
        ):
            parts.append(part)
        return b"".join(parts)

    payload = run(collect()).decode()
    assert '"text":"a"' in payload
    assert '"text":"b"' in payload


def test_litellm_provider_applies_openrouter_context_limits(monkeypatch: Any) -> None:
    captured: dict[str, Any] = {}

    async def completion(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "id": "response_1",
            "choices": [
                {
                    "message": {"content": "ok", "tool_calls": None},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 2, "completion_tokens": 1},
        }

    fake_litellm = SimpleNamespace(
        acompletion=completion,
        get_max_tokens=lambda _model: 16_384,
    )
    monkeypatch.setattr(provider_module, "load_litellm", lambda: fake_litellm)
    provider = LiteLLMProvider(
        ProviderModelConfig(
            provider="litellm",
            model="openrouter/google/gemma-4-31b-it",
            context_compression=True,
        )
    )

    run(
        provider.complete(
            {
                "messages": [{"role": "user", "content": "hello"}],
                "max_tokens": 64_000,
            },
            {},
        )
    )

    assert captured["max_tokens"] == 16_384
    assert captured["plugins"] == [{"id": "context-compression"}]
