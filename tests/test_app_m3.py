from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

from fastapi.testclient import TestClient

from cc_enrutador.app import create_app
from cc_enrutador.config import AppConfig, TelemetryConfig
from cc_enrutador.models import ClassificationResult, ComplexityTier, RouteDecision
from cc_enrutador.providers.base import ProviderError
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
                    "content": [
                        {"type": "tool_use", "id": "toolu_1", "name": "read", "input": {}}
                    ],
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
    assert registry.auxiliary.calls == [
        ("POST", "api/event", b'{"event":"test"}', "source=claude")
    ]
    assert events == []
