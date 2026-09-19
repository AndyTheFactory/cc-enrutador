from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

from fastapi.testclient import TestClient

from cc_enrutador.app import create_app
from cc_enrutador.config import AppConfig
from cc_enrutador.models import ClassificationResult, ComplexityTier, RouteDecision


def config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "classifier": {
                "mode": "heuristic",
                "model": {"provider": "litellm", "model": "classifier"},
            },
            "models": {
                "simple": {"provider": "litellm", "model": "simple-model"},
                "medium": {"provider": "litellm", "model": "medium-model"},
                "complex": {
                    "provider": "anthropic_subscription",
                    "model": "passthrough",
                    "api_base": "https://api.anthropic.test",
                },
            },
        }
    )


class StubClassifier:
    def __init__(self, tier: ComplexityTier) -> None:
        self.tier = tier

    async def classify(self, request: Mapping[str, Any]) -> ClassificationResult:
        return ClassificationResult(
            tier=self.tier,
            method="heuristic",
            reason="test",
            confidence=1.0,
            latency_ms=0.0,
        )


class FakeProvider:
    def __init__(self, name: str) -> None:
        self.name = name
        self.last_body: dict[str, Any] | None = None
        self.last_headers: dict[str, str] | None = None
        self.last_query = ""

    async def complete(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
        query: str = "",
    ) -> dict[str, Any]:
        self.last_body = dict(body)
        self.last_headers = dict(headers)
        self.last_query = query
        return {
            "id": f"msg_{self.name}",
            "type": "message",
            "role": "assistant",
            "model": self.name,
            "content": [{"type": "text", "text": self.name}],
            "stop_reason": "end_turn",
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }

    async def stream(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
        query: str = "",
    ) -> AsyncIterator[bytes]:
        self.last_body = dict(body)
        self.last_headers = dict(headers)
        self.last_query = query
        yield b'event: message_start\ndata: {"type":"message_start"}\n\n'
        yield b'event: message_stop\ndata: {"type":"message_stop"}\n\n'


class FakeRegistry:
    def __init__(self) -> None:
        self.providers = {
            ComplexityTier.SIMPLE: FakeProvider("simple-model"),
            ComplexityTier.MEDIUM: FakeProvider("medium-model"),
            ComplexityTier.COMPLEX: FakeProvider("claude-passthrough"),
        }
        self.routes: list[RouteDecision] = []

    def get(self, route: RouteDecision) -> FakeProvider:
        self.routes.append(route)
        return self.providers[route.tier]


def test_health_is_provider_free() -> None:
    cfg = config()
    registry = FakeRegistry()
    client = TestClient(create_app(cfg, StubClassifier(ComplexityTier.SIMPLE), registry))

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert registry.routes == []


def test_all_three_tiers_execute_through_messages_endpoint() -> None:
    cfg = config()

    for tier, expected in (
        (ComplexityTier.SIMPLE, "simple-model"),
        (ComplexityTier.MEDIUM, "medium-model"),
        (ComplexityTier.COMPLEX, "claude-passthrough"),
    ):
        registry = FakeRegistry()
        client = TestClient(create_app(cfg, StubClassifier(tier), registry))

        response = client.post(
            "/v1/messages",
            json={
                "model": "incoming-model-is-not-authoritative",
                "max_tokens": 32,
                "messages": [{"role": "user", "content": "hello"}],
            },
        )

        assert response.status_code == 200
        assert response.json()["content"][0]["text"] == expected
        assert registry.routes[-1].tier == tier


def test_unknown_fields_are_preserved_for_provider_forwarding() -> None:
    cfg = config()
    registry = FakeRegistry()
    client = TestClient(create_app(cfg, StubClassifier(ComplexityTier.COMPLEX), registry))

    response = client.post(
        "/v1/messages",
        json={
            "model": "claude-test",
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "hello"}],
            "metadata": {"user_id": "fixture-user"},
            "future_anthropic_field": {"enabled": True},
        },
    )

    assert response.status_code == 200
    provider = registry.providers[ComplexityTier.COMPLEX]
    assert provider.last_body is not None
    assert provider.last_body["future_anthropic_field"] == {"enabled": True}
    assert provider.last_body["metadata"] == {"user_id": "fixture-user"}


def test_streaming_messages_endpoint_returns_sse() -> None:
    cfg = config()
    registry = FakeRegistry()
    client = TestClient(create_app(cfg, StubClassifier(ComplexityTier.MEDIUM), registry))

    with client.stream(
        "POST",
        "/v1/messages",
        json={
            "model": "ignored",
            "stream": True,
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "hello"}],
        },
    ) as response:
        payload = b"".join(response.iter_bytes())

    assert response.status_code == 200
    assert b"event: message_start" in payload
    assert b"event: message_stop" in payload


def test_request_headers_reach_provider_for_route_specific_filtering() -> None:
    cfg = config()
    registry = FakeRegistry()
    client = TestClient(create_app(cfg, StubClassifier(ComplexityTier.COMPLEX), registry))

    response = client.post(
        "/v1/messages",
        headers={
            "authorization": "Bearer fake-claude-oauth",
            "anthropic-version": "2023-06-01",
        },
        json={
            "model": "claude-test",
            "max_tokens": 32,
            "messages": [{"role": "user", "content": "hello"}],
        },
    )

    assert response.status_code == 200
    provider = registry.providers[ComplexityTier.COMPLEX]
    assert provider.last_headers is not None
    assert provider.last_headers["authorization"] == "Bearer fake-claude-oauth"
