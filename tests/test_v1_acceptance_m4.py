from __future__ import annotations

import asyncio
import socket
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from cc_enrutador.app import create_app
from cc_enrutador.classifier import ClassifierService
from cc_enrutador.config import AppConfig, load_config
from cc_enrutador.doctor import CheckStatus, Doctor
from cc_enrutador.models import ComplexityTier, RouteDecision
from cc_enrutador.streaming import forward_stream


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def base_config(*, mode: str = "heuristic") -> AppConfig:
    return AppConfig.model_validate(
        {
            "server": {"host": "127.0.0.1", "port": free_port()},
            "classifier": {
                "mode": mode,
                "model": {"provider": "litellm", "model": "test/classifier"},
                "timeout_ms": 50,
            },
            "models": {
                "simple": {"provider": "litellm", "model": "test/simple"},
                "medium": {"provider": "litellm", "model": "test/medium"},
                "complex": {
                    "provider": "anthropic_subscription",
                    "model": "passthrough",
                    "api_base": "https://api.anthropic.test",
                },
            },
        }
    )


class FakeProvider:
    def __init__(self, name: str) -> None:
        self.name = name

    async def complete(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
        query: str = "",
    ) -> dict[str, Any]:
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
        yield b'event: message_stop\ndata: {"type":"message_stop"}\n\n'


class FakeRegistry:
    def __init__(self) -> None:
        self.routes: list[ComplexityTier] = []

    def get(self, route: RouteDecision) -> FakeProvider:
        self.routes.append(route.tier)
        return FakeProvider(route.model)

    def anthropic(self) -> Any:
        raise AssertionError("auxiliary passthrough not used by this test")


def test_reference_config_loads_with_documented_environment(
    monkeypatch: Any,
) -> None:
    monkeypatch.setenv("SIMPLE_MODEL", "ollama/qwen3-coder")
    monkeypatch.setenv("SIMPLE_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("MEDIUM_MODEL", "openai/gpt-oss-120b")
    monkeypatch.setenv("MEDIUM_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.delenv("SIMPLE_API_KEY", raising=False)
    monkeypatch.delenv("MEDIUM_API_KEY", raising=False)

    config = load_config(Path("config.example.yaml"))

    assert config.classifier.mode == "hybrid"
    assert config.models.simple.provider == "litellm"
    assert config.models.simple.api_key_env == "SIMPLE_API_KEY"
    assert config.models.medium.provider == "litellm"
    assert config.models.medium.api_key_env == "MEDIUM_API_KEY"
    assert config.models.complex.provider == "anthropic_subscription"


def test_missing_optional_provider_key_is_doctor_warning(
    monkeypatch: Any,
) -> None:
    monkeypatch.delenv("OPTIONAL_PROVIDER_KEY", raising=False)
    cfg = base_config()
    cfg.models.medium.api_key_env = "OPTIONAL_PROVIDER_KEY"

    report = asyncio.run(Doctor(cfg).run())
    check = next(item for item in report.checks if item.name == "secret:medium")

    assert check.status == CheckStatus.WARN
    assert check.required is False
    assert report.exit_code == 0


def test_all_three_reference_task_types_route_to_expected_tiers() -> None:
    cfg = base_config()
    registry = FakeRegistry()
    client = TestClient(create_app(cfg, providers=registry))

    cases = [
        ("Rename foo to bar.", ComplexityTier.SIMPLE),
        ("Fix the parser bug and add a regression test.", ComplexityTier.MEDIUM),
        (
            "Design the service architecture end-to-end and discuss trade-offs.",
            ComplexityTier.COMPLEX,
        ),
    ]

    for task, expected in cases:
        response = client.post(
            "/v1/messages",
            json={"messages": [{"role": "user", "content": task}], "max_tokens": 8},
        )
        assert response.status_code == 200
        assert registry.routes[-1] == expected


def test_ai_classifier_failure_still_executes_via_heuristic_fallback() -> None:
    cfg = base_config(mode="hybrid")

    async def failing_classifier(prompt: str, config: Any) -> str:
        raise RuntimeError("classifier unavailable")

    classifier = ClassifierService(cfg, ai_completion=failing_classifier)
    registry = FakeRegistry()
    client = TestClient(create_app(cfg, classifier=classifier, providers=registry))

    response = client.post(
        "/v1/messages",
        json={
            "messages": [
                {"role": "user", "content": "Fix the parser bug and add a regression test."}
            ],
            "max_tokens": 8,
        },
    )

    assert response.status_code == 200
    assert registry.routes == [ComplexityTier.MEDIUM]


def test_long_stream_disconnect_closes_upstream_without_buffering() -> None:
    closed = False
    checks = 0

    async def upstream() -> AsyncIterator[bytes]:
        nonlocal closed
        try:
            for index in range(1000):
                yield f"{index},".encode()
        finally:
            closed = True

    async def disconnected() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 101

    async def collect() -> list[bytes]:
        parts: list[bytes] = []
        async for part in forward_stream(upstream(), disconnected):
            parts.append(part)
        return parts

    parts = asyncio.run(collect())

    assert len(parts) == 100
    assert parts[0] == b"0,"
    assert parts[-1] == b"99,"
    assert closed is True
