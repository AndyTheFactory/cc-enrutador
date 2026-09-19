from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from cc_enrutador.classifier import ClassifierService
from cc_enrutador.classifiers.jev import (
    JevAdapter,
    JevChoiceDecision,
    JevSchemaError,
    parse_choice,
    select_tier,
)
from cc_enrutador.config import AppConfig
from cc_enrutador.models import ComplexityTier


def config(*, mode: str = "hybrid", shadow: bool = False) -> AppConfig:
    return AppConfig.model_validate({
        "classifier": {
            "mode": mode,
            "model": {
                "provider": "openrouter_decisions",
                "model": "~typesafe/jev-latest",
                "api_base": "https://openrouter.ai/api/alpha/decisions",
                "api_key_env": "TEST_OPENROUTER_KEY",
            },
            "jev": {"shadow": {"enabled": shadow}},
        },
        "models": {
            "simple": {"provider": "litellm", "model": "local/model"},
            "medium": {"provider": "litellm", "model": "remote/model"},
            "complex": {
                "provider": "anthropic_subscription",
                "model": "passthrough",
                "api_base": "https://api.anthropic.com",
            },
        },
    })


def answer(choice: str = "medium", simple: float = 0.10,
           medium: float = 0.80, complex: float = 0.10) -> dict[str, Any]:
    return {
        "model": "typesafe/jev-1.13",
        "answers": {
            "task_tier": {
                "type": "choice",
                "choice": choice,
                "confidence": 0.92,
                "probabilities": {
                    "simple": simple,
                    "medium": medium,
                    "complex": complex,
                },
            },
        },
    }


def test_config_provider_is_classifier_only() -> None:
    cfg = config()
    assert cfg.classifier.model.provider == "openrouter_decisions"
    cfg_data = cfg.model_dump()
    cfg_data["models"]["simple"]["provider"] = "openrouter_decisions"
    with pytest.raises(ValidationError, match="classifier-only"):
        AppConfig.model_validate(cfg_data)


def test_litellm_classifier_remains_supported() -> None:
    cfg = config().model_dump()
    cfg["classifier"]["model"]["provider"] = "litellm"
    cfg["classifier"]["jev"] = None
    assert AppConfig.model_validate(cfg).classifier.model.provider == "litellm"


@pytest.mark.parametrize("bad", [
    answer("invalid"), answer("medium", 0.5, 0.5, 0.5),
    answer("medium", -0.1, 1.0, 0.1),
])
def test_invalid_choice_fails_closed(bad: dict[str, Any]) -> None:
    with pytest.raises(JevSchemaError):
        parse_choice(bad, config().classifier)


def test_policy_conservative_simple_and_complex_priority() -> None:
    cfg = config().classifier
    confident = parse_choice(answer("simple", 0.90, 0.06, 0.04), cfg)
    ambiguous = parse_choice(answer("simple", 0.52, 0.43, 0.05), cfg)
    complex_case = parse_choice(answer("medium", 0.04, 0.44, 0.52), cfg)
    assert select_tier(confident, cfg)[0] is ComplexityTier.SIMPLE
    assert select_tier(ambiguous, cfg)[0] is ComplexityTier.MEDIUM
    assert select_tier(complex_case, cfg)[0] is ComplexityTier.COMPLEX


def test_adapter_sends_one_choice_and_only_openrouter_key(monkeypatch: Any) -> None:
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "test-openrouter-secret")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=answer())

    async def scenario() -> JevChoiceDecision:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            adapter = JevAdapter(config().classifier, client=client)
            return await adapter.decide("Fix the parser.", "Rules", False, False)

    result = asyncio.run(scenario())
    assert result.choice is ComplexityTier.MEDIUM
    assert len(seen) == 1
    request = seen[0]
    assert request.headers["authorization"] == "Bearer test-openrouter-secret"
    assert b"task_tier" in request.content
    assert request.content.count(b'"type":"choice"') == 1
    assert b"fake-claude-oauth" not in request.content


def test_provider_driven_routing_cache_and_shadow(monkeypatch: Any) -> None:
    monkeypatch.setenv("TEST_OPENROUTER_KEY", "test-openrouter-secret")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=answer("complex", 0.01, 0.09, 0.90))

    async def scenario(shadow: bool) -> tuple[Any, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            cfg = config(shadow=shadow)
            service = ClassifierService(cfg, jev_adapter=JevAdapter(cfg.classifier, client))
            request = {"messages": [{"role": "user", "content": "Fix the parser bug."}]}
            return await service.classify(request), await service.classify(request)

    first, second = asyncio.run(scenario(False))
    assert first.tier is ComplexityTier.COMPLEX
    assert second.cached is True
    assert calls == 1

    shadow_first, shadow_second = asyncio.run(scenario(True))
    assert shadow_first.tier is ComplexityTier.MEDIUM
    assert shadow_first.decision is not None
    assert shadow_first.decision["disagreement"] is True
    assert shadow_second.tier is ComplexityTier.MEDIUM
    assert calls == 2
