from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx
from fastapi.testclient import TestClient

from cc_enrutador.app import create_app
from cc_enrutador.config import AppConfig, TelemetryConfig
from cc_enrutador.models import ClassificationResult, ComplexityTier, RouteDecision
from cc_enrutador.providers.base import ProviderError, ProviderResponseError
from cc_enrutador.telemetry import RouterTelemetryEvent, TelemetryRecorder


def config(*, telemetry_enabled: bool = True) -> AppConfig:
    return AppConfig.model_validate(
        {
            "classifier": {
                "mode": "heuristic",
                "model": {"provider": "litellm", "model": "classifier"},
            },
            "models": {
                "simple": {"provider": "litellm", "model": "simple"},
                "medium": {"provider": "litellm", "model": "medium"},
                "complex": {
                    "provider": "anthropic_subscription",
                    "model": "complex",
                    "api_base": "https://api.anthropic.test",
                },
            },
            "telemetry": {"enabled": telemetry_enabled},
        }
    )


class SequenceClassifier:
    def __init__(self, tiers: list[ComplexityTier]) -> None:
        self.tiers = tiers
        self.calls = 0

    async def classify(self, request: Mapping[str, Any]) -> ClassificationResult:
        tier = self.tiers[min(self.calls, len(self.tiers) - 1)]
        self.calls += 1
        return ClassificationResult(
            tier=tier,
            method="heuristic",
            reason="test",
            confidence=1.0,
            latency_ms=0.1,
        )


class Provider:
    def __init__(self, name: str, *, fail: bool = False) -> None:
        self.name = name
        self.fail = fail

    async def complete(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
        query: str = "",
    ) -> dict[str, Any]:
        if self.fail:
            raise ProviderError(f"{self.name} failed")
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
        if self.fail:
            raise ProviderError(f"{self.name} failed")
        yield b'event: message_stop\ndata: {"type":"message_stop"}\n\n'


class AuxiliaryProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes, str]] = []

    async def raw_request(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        content: bytes,
        query: str = "",
    ) -> tuple[int, dict[str, str], bytes]:
        self.calls.append((method, path, content, query))
        return 200, {"content-type": "application/json"}, b'{"accepted":true}'


class Registry:
    def __init__(self, *, fail_simple: bool = False) -> None:
        self.providers = {
            ComplexityTier.SIMPLE: Provider("simple", fail=fail_simple),
            ComplexityTier.MEDIUM: Provider("medium"),
            ComplexityTier.COMPLEX: Provider("complex"),
        }
        self.routes: list[ComplexityTier] = []
        self.auxiliary = AuxiliaryProvider()

    def get(self, route: RouteDecision) -> Provider:
        self.routes.append(route.tier)
        return self.providers[route.tier]

    def anthropic(self) -> AuxiliaryProvider:
        return self.auxiliary


def test_tool_loop_keeps_complex_floor_until_fresh_instruction() -> None:
    cfg = config()
    classifier = SequenceClassifier(
        [ComplexityTier.COMPLEX, ComplexityTier.SIMPLE, ComplexityTier.SIMPLE]
    )
    registry = Registry()
    client = TestClient(create_app(cfg, classifier, registry))

    first = client.post(
        "/v1/messages",
        json={"messages": [{"role": "user", "content": "Design the architecture."}]},
    )
    continued = client.post(
        "/v1/messages",
        json={
            "messages": [
                {"role": "user", "content": "Design the architecture."},
                {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "id": "toolu_1", "name": "read", "input": {}}],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": "result",
                        }
                    ],
                },
            ]
        },
    )
    fresh = client.post(
        "/v1/messages",
        json={
            "messages": [
                {"role": "user", "content": "Design the architecture."},
                {"role": "assistant", "content": "Done."},
                {"role": "user", "content": "Rename foo to bar."},
            ]
        },
    )

    assert first.status_code == 200
    assert continued.status_code == 200
    assert fresh.status_code == 200
    assert registry.routes == [
        ComplexityTier.COMPLEX,
        ComplexityTier.COMPLEX,
        ComplexityTier.SIMPLE,
    ]


def test_provider_fallback_is_recorded_in_telemetry() -> None:
    cfg = config()
    registry = Registry(fail_simple=True)
    events: list[RouterTelemetryEvent] = []
    telemetry = TelemetryRecorder(TelemetryConfig(enabled=True), events.append)
    client = TestClient(
        create_app(
            cfg,
            SequenceClassifier([ComplexityTier.SIMPLE]),
            registry,
            telemetry=telemetry,
        )
    )

    response = client.post(
        "/v1/messages",
        headers={"x-request-id": "request-123"},
        json={"messages": [{"role": "user", "content": "Rename foo to bar."}]},
    )

    assert response.status_code == 200
    assert response.json()["model"] == "medium"
    assert registry.routes == [ComplexityTier.SIMPLE, ComplexityTier.MEDIUM]
    assert len(events) == 1
    assert events[0].request_id == "request-123"
    assert events[0].tier == ComplexityTier.MEDIUM
    assert events[0].fallback_path == [ComplexityTier.MEDIUM]
    assert events[0].model_latency_ms is not None
    assert events[0].model_latency_ms >= 0


def test_failed_model_request_logs_actionable_context(caplog: Any) -> None:
    registry = Registry()
    registry.providers[ComplexityTier.COMPLEX].fail = True
    app = create_app(config(), SequenceClassifier([ComplexityTier.COMPLEX]), registry)

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/v1/messages?beta=true",
                headers={"x-request-id": "request-456", "authorization": "Bearer secret"},
                json={"messages": [{"role": "user", "content": "Design the architecture."}]},
            )

    with caplog.at_level(logging.ERROR, logger="cc_enrutador.app"):
        response = asyncio.run(send_request())

    assert response.status_code == 502
    log = caplog.messages[-1]
    assert "model request failed" in log
    assert "request_id=request-456" in log
    assert "tier=complex" in log
    assert "target=complex" in log
    assert "attempted_tiers=['complex']" in log
    assert "error_type=ProviderError" in log
    assert "complex failed" in log
    assert "secret" not in log


def test_anthropic_error_response_is_relayed_unchanged() -> None:
    class RejectedProvider(Provider):
        async def complete(
            self,
            body: Mapping[str, Any],
            headers: Mapping[str, str],
            query: str = "",
        ) -> dict[str, Any]:
            assert query == "beta=true"
            raise ProviderResponseError(
                "upstream rejected request",
                status_code=429,
                headers={
                    "content-type": "application/json",
                    "retry-after": "11",
                    "x-should-retry": "true",
                    "request-id": "req_123",
                },
                content=b'{"type":"error","request_id":"req_123"}',
                retryable=True,
            )

    registry = Registry()
    registry.providers[ComplexityTier.COMPLEX] = RejectedProvider("complex")
    app = create_app(config(), SequenceClassifier([ComplexityTier.COMPLEX]), registry)

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/v1/messages?beta=true",
                json={"messages": [{"role": "user", "content": "hello"}]},
            )

    response = asyncio.run(send_request())

    assert response.status_code == 429
    assert response.content == b'{"type":"error","request_id":"req_123"}'
    assert response.headers["retry-after"] == "11"
    assert response.headers["x-should-retry"] == "true"
    assert response.headers["request-id"] == "req_123"


def test_streaming_anthropic_error_is_relayed_before_response_starts() -> None:
    class RejectedStreamProvider(Provider):
        async def stream(
            self,
            body: Mapping[str, Any],
            headers: Mapping[str, str],
            query: str = "",
        ) -> AsyncIterator[bytes]:
            assert query == "beta=true"
            raise ProviderResponseError(
                "upstream unavailable",
                status_code=529,
                headers={
                    "content-type": "application/json",
                    "retry-after": "3",
                    "x-should-retry": "true",
                    "request-id": "req_stream_123",
                },
                content=b'{"type":"error","error":{"type":"overloaded_error"}}',
                retryable=True,
            )
            yield b""  # pragma: no cover

    registry = Registry()
    registry.providers[ComplexityTier.COMPLEX] = RejectedStreamProvider("complex")
    app = create_app(config(), SequenceClassifier([ComplexityTier.COMPLEX]), registry)

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/v1/messages?beta=true",
                json={
                    "stream": True,
                    "messages": [{"role": "user", "content": "hello"}],
                },
            )

    response = asyncio.run(send_request())

    assert response.status_code == 529
    assert response.content == b'{"type":"error","error":{"type":"overloaded_error"}}'
    assert response.headers["retry-after"] == "3"
    assert response.headers["x-should-retry"] == "true"
    assert response.headers["request-id"] == "req_stream_123"


def test_auxiliary_traffic_bypasses_classifier_and_router_telemetry() -> None:
    cfg = config(telemetry_enabled=False)

    class ExplodingClassifier:
        async def classify(self, request: Mapping[str, Any]) -> ClassificationResult:
            raise AssertionError("auxiliary traffic must not be classified")

    registry = Registry()
    events: list[RouterTelemetryEvent] = []
    telemetry = TelemetryRecorder(TelemetryConfig(enabled=False), events.append)
    client = TestClient(create_app(cfg, ExplodingClassifier(), registry, telemetry=telemetry))

    response = client.post(
        "/api/event?source=claude",
        headers={"authorization": "Bearer fake-oauth"},
        content=b'{"event":"test"}',
    )

    assert response.status_code == 200
    assert response.json() == {"accepted": True}
    assert registry.auxiliary.calls == [("POST", "api/event", b'{"event":"test"}', "source=claude")]
    assert events == []


def test_hello_supports_get_and_head_without_upstream_call() -> None:
    registry = Registry()
    app = create_app(config(), providers=registry)

    async def request_hello() -> tuple[httpx.Response, httpx.Response]:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.get("/api/hello"), await client.head("/api/hello")

    get_response, head_response = asyncio.run(request_hello())

    assert get_response.status_code == 200
    assert get_response.json() == {"status": "ok"}
    assert head_response.status_code == 200
    assert head_response.content == b""
    assert registry.auxiliary.calls == []


def test_harm_monitor_request_bypasses_classifier_with_raw_anthropic_passthrough() -> None:
    class ExplodingClassifier:
        async def classify(self, request: Mapping[str, Any]) -> ClassificationResult:
            raise AssertionError("harm monitor request must not be classified")

    registry = Registry()
    app = create_app(config(), classifier=ExplodingClassifier(), providers=registry)
    payload = {
        "system": "You are a security monitor for autonomous AI coding agents.",
        "messages": [
            {
                "role": "user",
                "content": (
                    '<transcript>\n{"user":"delete generated files"}\n</transcript>\n'
                    "Grade HARM ONLY. Respond with <severity>N</severity> ONLY."
                ),
            }
        ],
    }

    async def send_request() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            return await client.post(
                "/v1/messages?beta=true",
                headers={"authorization": "Bearer fake-oauth"},
                json=payload,
            )

    response = asyncio.run(send_request())

    assert response.status_code == 200
    assert response.json() == {"accepted": True}
    assert registry.routes == []
    assert len(registry.auxiliary.calls) == 1
    method, path, content, query = registry.auxiliary.calls[0]
    assert method == "POST"
    assert path == "/v1/messages"
    assert b"security monitor for autonomous AI coding agents" in content
    assert query == "beta=true"
