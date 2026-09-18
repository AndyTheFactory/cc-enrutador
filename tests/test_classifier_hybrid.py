from __future__ import annotations

import asyncio
from typing import Any

from cc_enrutador.classifier import ClassifierService
from cc_enrutador.config import AppConfig, ClassifierConfig
from cc_enrutador.models import ComplexityTier


def app_config(mode: str = "hybrid", cache_size: int = 10) -> AppConfig:
    return AppConfig.model_validate(
        {
            "classifier": {
                "mode": mode,
                "model": {"provider": "litellm", "model": "test/classifier"},
                "cache_size": cache_size,
                "timeout_ms": 100,
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


def request(task: str) -> dict[str, Any]:
    return {"messages": [{"role": "user", "content": task}]}


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_hybrid_skips_ai_when_simple_gate_fires() -> None:
    calls = 0

    async def fake(prompt: str, config: ClassifierConfig) -> str:
        nonlocal calls
        calls += 1
        return "3"

    service = ClassifierService(app_config(), ai_completion=fake)
    result = run(service.classify(request("Rename foo to bar.")))

    assert result.tier == ComplexityTier.SIMPLE
    assert result.method == "heuristic"
    assert calls == 0


def test_hybrid_calls_ai_on_default_medium() -> None:
    calls = 0

    async def fake(prompt: str, config: ClassifierConfig) -> str:
        nonlocal calls
        calls += 1
        return "3"

    service = ClassifierService(app_config(), ai_completion=fake)
    result = run(service.classify(request("Fix the parser bug.")))

    assert result.tier == ComplexityTier.COMPLEX
    assert result.method == "hybrid"
    assert calls == 1


def test_ai_mode_calls_ai_even_for_explicit_gate() -> None:
    async def fake(prompt: str, config: ClassifierConfig) -> str:
        return "2"

    service = ClassifierService(app_config("ai"), ai_completion=fake)
    result = run(service.classify(request("Rename foo to bar.")))

    assert result.tier == ComplexityTier.MEDIUM
    assert result.method == "ai"


def test_timeout_falls_back_to_heuristic() -> None:
    async def slow(prompt: str, config: ClassifierConfig) -> str:
        await asyncio.sleep(1)
        return "1"

    service = ClassifierService(app_config(), ai_completion=slow)
    result = run(service.classify(request("Fix the parser bug.")))

    assert result.tier == ComplexityTier.MEDIUM
    assert result.method == "heuristic"
    assert result.reason.startswith("ai-fallback:")


def test_malformed_ai_output_falls_back() -> None:
    async def fake(prompt: str, config: ClassifierConfig) -> str:
        return "definitely-medium"

    service = ClassifierService(app_config(), ai_completion=fake)
    result = run(service.classify(request("Fix the parser bug.")))

    assert result.tier == ComplexityTier.MEDIUM
    assert result.method == "heuristic"


def test_ai_result_is_cached() -> None:
    calls = 0

    async def fake(prompt: str, config: ClassifierConfig) -> str:
        nonlocal calls
        calls += 1
        return "2"

    service = ClassifierService(app_config(), ai_completion=fake)
    first = run(service.classify(request("Fix parser behavior.")))
    second = run(service.classify(request("Fix parser behavior.")))

    assert first.cached is False
    assert second.cached is True
    assert calls == 1


def test_cache_key_uses_full_task_not_only_prefix() -> None:
    calls = 0

    async def fake(prompt: str, config: ClassifierConfig) -> str:
        nonlocal calls
        calls += 1
        return "2"

    service = ClassifierService(app_config(), ai_completion=fake)
    prefix = "Explain the behavior. " + ("x" * 900)
    run(service.classify(request(prefix + " first ending")))
    run(service.classify(request(prefix + " second ending")))

    assert calls == 2


def test_cache_can_be_disabled() -> None:
    calls = 0

    async def fake(prompt: str, config: ClassifierConfig) -> str:
        nonlocal calls
        calls += 1
        return "2"

    service = ClassifierService(app_config(cache_size=0), ai_completion=fake)
    run(service.classify(request("Fix parser behavior.")))
    run(service.classify(request("Fix parser behavior.")))

    assert calls == 2
