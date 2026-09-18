from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest

from cc_enrutador.config import AppConfig
from cc_enrutador.models import ComplexityTier, RouteDecision
from cc_enrutador.operations import ExecutionService, escalation_tiers
from cc_enrutador.providers.base import ProviderError
from cc_enrutador.state import TaskStateStore


def config(*, enabled: bool = True) -> AppConfig:
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
            "escalation": {"enabled": enabled},
        }
    )


class FakeProvider:
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
        return {"type": "message", "model": self.name, "content": []}

    async def stream(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> AsyncIterator[bytes]:
        if self.fail:
            raise ProviderError(f"{self.name} failed")
        yield self.name.encode()


class FakeRegistry:
    def __init__(self, failures: set[ComplexityTier]) -> None:
        self.failures = failures
        self.attempted: list[ComplexityTier] = []

    def get(self, route: RouteDecision) -> FakeProvider:
        self.attempted.append(route.tier)
        return FakeProvider(route.model, fail=route.tier in self.failures)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_default_escalation_chain() -> None:
    cfg = config()
    assert escalation_tiers(ComplexityTier.SIMPLE, cfg) == [
        ComplexityTier.SIMPLE,
        ComplexityTier.MEDIUM,
        ComplexityTier.COMPLEX,
    ]
    assert escalation_tiers(ComplexityTier.MEDIUM, cfg) == [
        ComplexityTier.MEDIUM,
        ComplexityTier.COMPLEX,
    ]


def test_provider_failure_escalates_and_promotes_task_floor() -> None:
    cfg = config()
    registry = FakeRegistry({ComplexityTier.SIMPLE})
    state = TaskStateStore()
    service = ExecutionService(cfg, registry, state)
    attempts: list[ComplexityTier] = []

    result = run(
        service.complete(
            ComplexityTier.SIMPLE,
            "task",
            {"messages": [{"role": "user", "content": "hello"}]},
            {},
            attempted_tiers=attempts,
        )
    )

    assert result.final_route.tier == ComplexityTier.MEDIUM
    assert attempts == [ComplexityTier.SIMPLE, ComplexityTier.MEDIUM]
    assert state.get("task") is not None
    assert state.get("task").minimum_tier == ComplexityTier.MEDIUM


def test_disabled_escalation_stops_after_first_failure() -> None:
    cfg = config(enabled=False)
    registry = FakeRegistry({ComplexityTier.SIMPLE})
    service = ExecutionService(cfg, registry, TaskStateStore())

    with pytest.raises(ProviderError, match="simple failed"):
        run(
            service.complete(
                ComplexityTier.SIMPLE,
                "task",
                {"messages": [{"role": "user", "content": "hello"}]},
                {},
            )
        )

    assert registry.attempted == [ComplexityTier.SIMPLE]


def test_stream_escalates_before_first_chunk() -> None:
    cfg = config()
    registry = FakeRegistry({ComplexityTier.SIMPLE})
    state = TaskStateStore()
    service = ExecutionService(cfg, registry, state)
    attempts: list[ComplexityTier] = []

    async def collect() -> bytes:
        parts = []
        async for chunk in service.stream(
            ComplexityTier.SIMPLE,
            "task",
            {"messages": [{"role": "user", "content": "hello"}]},
            {},
            attempted_tiers=attempts,
        ):
            parts.append(chunk)
        return b"".join(parts)

    payload = run(collect())

    assert payload == b"medium"
    assert attempts == [ComplexityTier.SIMPLE, ComplexityTier.MEDIUM]


def test_stream_does_not_switch_provider_after_output_started() -> None:
    class PartialFailProvider(FakeProvider):
        async def stream(
            self,
            body: Mapping[str, Any],
            headers: Mapping[str, str],
        ) -> AsyncIterator[bytes]:
            yield b"partial"
            raise ProviderError("late failure")

    class PartialRegistry(FakeRegistry):
        def get(self, route: RouteDecision) -> FakeProvider:
            self.attempted.append(route.tier)
            if route.tier is ComplexityTier.SIMPLE:
                return PartialFailProvider(route.model)
            return FakeProvider(route.model)

    service = ExecutionService(config(), PartialRegistry(set()), TaskStateStore())

    async def collect() -> None:
        async for _ in service.stream(
            ComplexityTier.SIMPLE,
            "task",
            {"messages": [{"role": "user", "content": "hello"}]},
            {},
        ):
            pass

    with pytest.raises(ProviderError, match="after response started"):
        run(collect())
