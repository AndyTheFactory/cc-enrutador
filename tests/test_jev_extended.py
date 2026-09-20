from __future__ import annotations

import asyncio
import json
import socket
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cc_enrutador.app import create_app
from cc_enrutador.classifier import ClassifierService
from cc_enrutador.classifiers.jev import JevAdapter, JevProviderError, JevSchemaError, parse_choice
from cc_enrutador.config import AppConfig
from cc_enrutador.doctor import CheckStatus, Doctor
from cc_enrutador.models import ComplexityTier
from cc_enrutador.telemetry import RouterTelemetryEvent, TelemetryRecorder


def settings(*, mode: str = "ai", shadow: bool = False, cache_size: int = 2) -> AppConfig:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return AppConfig.model_validate(
        {
            "server": {"host": "127.0.0.1", "port": port},
            "classifier": {
                "mode": mode,
                "model": {
                    "provider": "openrouter_decisions",
                    "model": "~typesafe/jev-latest",
                    "api_key_env": "JEV_TEST_KEY",
                },
                "jev": {"shadow": {"enabled": shadow}},
                "cache_size": cache_size,
            },
            "models": {
                "simple": {"provider": "litellm", "model": "test/simple"},
                "medium": {"provider": "litellm", "model": "test/medium"},
                "complex": {
                    "provider": "anthropic_subscription",
                    "model": "passthrough",
                    "api_base": "https://api.anthropic.com",
                },
            },
        }
    )


def response(choice: str = "complex") -> dict[str, Any]:
    probabilities = (
        {"simple": 0.01, "medium": 0.09, "complex": 0.90}
        if choice == "complex"
        else {"simple": 0.90, "medium": 0.06, "complex": 0.04}
    )
    return {
        "model": "typesafe/jev-1.13",
        "answers": {
            "task_tier": {
                "type": "choice",
                "choice": choice,
                "probabilities": probabilities,
                "confidence": 0.9,
            }
        },
    }


def task(text: str) -> dict[str, Any]:
    return {"messages": [{"role": "user", "content": text}]}


def test_synthetic_fixtures_parse_and_reject_invalid() -> None:
    cfg = settings().classifier
    folder = Path("tests/fixtures/jev")
    good = json.loads((folder / "choice-success.json").read_text(encoding="utf-8"))
    bad = json.loads((folder / "choice-invalid.json").read_text(encoding="utf-8"))
    assert parse_choice(good, cfg).choice is ComplexityTier.MEDIUM
    with pytest.raises(JevSchemaError):
        parse_choice(bad, cfg)


@pytest.mark.parametrize("status", [401, 403, 429, 529, 500])
def test_provider_errors_are_categorized_without_upstream_body(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    monkeypatch.setenv("JEV_TEST_KEY", "secret-openrouter-key")

    def fail(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="secret response body")

    async def scenario() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
            adapter = JevAdapter(settings().classifier, client)
            with pytest.raises(JevProviderError) as error:
                await adapter.decide("diagnostic instruction")
            assert "secret" not in str(error.value)
            assert str(status) in str(error.value)

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["ai", "hybrid", "heuristic"])
def test_jev_mode_selection_and_shadow_gate(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("JEV_TEST_KEY", "synthetic-key")
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=response("complex"))

    async def scenario() -> tuple[Any, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            cfg = settings(mode=mode)
            service = ClassifierService(cfg, jev_adapter=JevAdapter(cfg.classifier, client))
            first = await service.classify(task("Rename foo to bar."))
            again = await service.classify(task("Rename foo to bar."))
            return first, again

    first, again = asyncio.run(scenario())
    assert first.tier is (ComplexityTier.SIMPLE if mode != "ai" else ComplexityTier.COMPLEX)
    assert calls == (1 if mode == "ai" else 0)
    assert again.tier is first.tier


def test_shadow_evaluates_explicit_gate_but_never_changes_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JEV_TEST_KEY", "synthetic-key")
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=response("complex"))

    async def scenario() -> tuple[Any, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            cfg = settings(mode="hybrid", shadow=True)
            classifier = ClassifierService(cfg, jev_adapter=JevAdapter(cfg.classifier, client))
            return (
                await classifier.classify(task("Rename foo to bar.")),
                await classifier.classify(task("Rename foo to bar.")),
            )

    first, again = asyncio.run(scenario())
    assert first.tier is ComplexityTier.SIMPLE
    assert first.decision is not None
    assert first.decision["disagreement"] is True
    assert again.cached is True
    assert calls == 1


def test_tool_result_only_does_not_call_jev(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JEV_TEST_KEY", "synthetic-key")

    def forbidden(_: httpx.Request) -> httpx.Response:
        raise AssertionError("tool result must not reach Decisions")

    async def scenario() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
            cfg = settings()
            classifier = ClassifierService(cfg, jev_adapter=JevAdapter(cfg.classifier, client))
            return await classifier.classify(
                {
                    "messages": [
                        {"role": "user", "content": "Fix the parser bug."},
                        {
                            "role": "assistant",
                            "content": [
                                {
                                    "type": "tool_use",
                                    "id": "toolu_1",
                                    "name": "read",
                                    "input": {},
                                }
                            ],
                        },
                        {
                            "role": "user",
                            "content": [
                                {
                                    "type": "tool_result",
                                    "tool_use_id": "toolu_1",
                                    "content": "secret source code",
                                }
                            ],
                        },
                    ]
                }
            )

    assert asyncio.run(scenario()).method == "heuristic"


def test_cache_eviction_and_disabled_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("JEV_TEST_KEY", "synthetic-key")
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=response())

    async def scenario(size: int) -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            cfg = settings(cache_size=size)
            service = ClassifierService(cfg, jev_adapter=JevAdapter(cfg.classifier, client))
            await service.classify(task("Fix the parser bug one."))
            await service.classify(task("Fix the parser bug two."))
            await service.classify(task("Fix the parser bug one."))

    asyncio.run(scenario(1))
    assert calls == 3
    asyncio.run(scenario(0))
    assert calls == 6


def test_missing_key_and_doctor_safe_live_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("JEV_TEST_KEY", raising=False)
    cfg = settings(mode="hybrid")
    doctor = Doctor(cfg)
    report = asyncio.run(doctor.run())
    secret = next(check for check in report.checks if check.name == "secret:classifier")
    assert secret.status is CheckStatus.FAIL
    assert report.exit_code == 1

    disabled = settings(mode="heuristic")
    report = asyncio.run(Doctor(disabled).run())
    secret = next(check for check in report.checks if check.name == "secret:classifier")
    assert secret.status is CheckStatus.WARN

    monkeypatch.setenv("JEV_TEST_KEY", "synthetic-key")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response())

    async def live() -> Any:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = JevAdapter(cfg.classifier, client)
            return await Doctor(cfg, jev_adapter=adapter)._live_classifier()

    result = asyncio.run(live())
    assert result.status is CheckStatus.PASS
    assert "synthetic-key" not in result.model_dump_json()


def test_config_rejects_unsafe_or_ambiguous_jev_options() -> None:
    data = settings().model_dump()
    data["classifier"]["jev"]["criteria"]["simple"] = " "
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)

    data = settings().model_dump()
    data["classifier"]["jev"]["policy"]["complex_min_probability"] = -0.1
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)

    data = settings().model_dump()
    data["classifier"]["model"]["api_base"] = "http://openrouter.ai/api/alpha/decisions"
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


def test_telemetry_metadata_is_optional_and_disabled_cleanly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("JEV_TEST_KEY", "synthetic-key")
    events: list[RouterTelemetryEvent] = []

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=response())

    class FakeProvider:
        async def complete(self, body: Any, headers: Any, query: str = "") -> dict[str, Any]:
            return {"type": "message", "model": "test", "content": []}

    class FakeRegistry:
        def get(self, route: Any) -> FakeProvider:
            return FakeProvider()

    async def classify_and_record(enabled: bool) -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            cfg = settings()
            cfg.telemetry.enabled = enabled
            classifier = ClassifierService(cfg, jev_adapter=JevAdapter(cfg.classifier, client))
            recorder = TelemetryRecorder(cfg.telemetry, events.append)
            app = create_app(
                cfg, classifier=classifier, providers=FakeRegistry(), telemetry=recorder
            )
            with TestClient(app) as http:
                response_http = http.post("/v1/messages", json=task("Fix parser behavior."))
                assert response_http.status_code == 200

    asyncio.run(classify_and_record(False))
    assert events == []
    asyncio.run(classify_and_record(True))
    assert len(events) == 1
    assert events[0].classifier_provider == "openrouter_decisions"
    assert events[0].jev is not None
    assert events[0].jev["policy_tier"] == "complex"
    assert "synthetic-key" not in events[0].model_dump_json()
