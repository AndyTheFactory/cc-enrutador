from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

from cc_enrutador.config import AppConfig
from cc_enrutador.execution import ProviderRegistry
from cc_enrutador.models import ComplexityTier, RouteDecision
from cc_enrutador.providers.base import ProviderError, ProviderRequestError
from cc_enrutador.routing import provider_for_tier
from cc_enrutador.state import TaskStateStore
from cc_enrutador.timeouts import TimeoutPolicy


@dataclass
class ExecutionResult:
    payload: dict[str, Any]
    final_route: RouteDecision
    attempted_tiers: list[ComplexityTier]
    model_latency_ms: float


def route_for_tier(tier: ComplexityTier, config: AppConfig) -> RouteDecision:
    target = provider_for_tier(tier, config)
    return RouteDecision(
        tier=tier,
        provider=target.provider,
        model=target.model,
        fallback_chain=[ComplexityTier(item) for item in config.escalation.chain[tier.value]],
    )


def escalation_tiers(initial: ComplexityTier, config: AppConfig) -> list[ComplexityTier]:
    tiers = [initial]
    if not config.escalation.enabled:
        return tiers

    current = initial
    for raw_target in config.escalation.chain[initial.value]:
        target = ComplexityTier(raw_target)
        if (
            current is ComplexityTier.SIMPLE
            and target is ComplexityTier.MEDIUM
            and not config.escalation.provider_failure.simple_to_medium
        ):
            break
        if (
            current is ComplexityTier.MEDIUM
            and target is ComplexityTier.COMPLEX
            and not config.escalation.provider_failure.medium_to_complex
        ):
            break
        tiers.append(target)
        current = target
    return tiers


class ExecutionService:
    def __init__(
        self,
        config: AppConfig,
        providers: ProviderRegistry,
        task_state: TaskStateStore,
        timeouts: TimeoutPolicy | None = None,
    ) -> None:
        self.config = config
        self.providers = providers
        self.task_state = task_state
        self.timeouts = timeouts or TimeoutPolicy(config.timeouts)

    async def complete(
        self,
        initial_tier: ComplexityTier,
        task_id: str,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
        attempted_tiers: list[ComplexityTier] | None = None,
    ) -> ExecutionResult:
        attempted = attempted_tiers if attempted_tiers is not None else []
        last_error: BaseException | None = None
        started = time.perf_counter()

        for tier in escalation_tiers(initial_tier, self.config):
            attempted.append(tier)
            route = route_for_tier(tier, self.config)
            provider = self.providers.get(route)
            try:
                payload = await asyncio.wait_for(
                    provider.complete(body, headers),
                    timeout=self.timeouts.request_seconds(tier),
                )
            except ProviderRequestError:
                raise
            except (ProviderError, TimeoutError) as exc:
                last_error = exc
                continue
            self.task_state.promote(task_id, tier)
            return ExecutionResult(
                payload=payload,
                final_route=route,
                attempted_tiers=attempted,
                model_latency_ms=(time.perf_counter() - started) * 1000,
            )

        if isinstance(last_error, ProviderError):
            raise last_error
        if last_error is not None:
            raise ProviderError(f"provider execution timed out: {last_error}") from last_error
        raise ProviderError("provider execution failed without an upstream attempt")

    async def stream(
        self,
        initial_tier: ComplexityTier,
        task_id: str,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
        attempted_tiers: list[ComplexityTier] | None = None,
        model_latency_ms: list[float] | None = None,
    ) -> AsyncIterator[bytes]:
        """model_latency_ms, if given, is appended to with each upstream chunk's wait
        time only — it excludes time spent on the consumer side (e.g. writing to a
        slow client), so it stays comparable to complete()'s model_latency_ms."""
        last_error: BaseException | None = None
        attempts = attempted_tiers if attempted_tiers is not None else []
        latency_sink = model_latency_ms if model_latency_ms is not None else []

        for tier in escalation_tiers(initial_tier, self.config):
            attempts.append(tier)
            route = route_for_tier(tier, self.config)
            provider = self.providers.get(route)
            upstream = provider.stream(body, headers)
            yielded = False
            try:
                while True:
                    chunk_started = time.perf_counter()
                    try:
                        chunk = await asyncio.wait_for(
                            anext(upstream),
                            timeout=self.timeouts.stream_idle_seconds(tier),
                        )
                    except StopAsyncIteration:
                        self.task_state.promote(task_id, tier)
                        return
                    latency_sink.append((time.perf_counter() - chunk_started) * 1000)
                    yielded = True
                    self.task_state.promote(task_id, tier)
                    yield chunk
            except (ProviderError, TimeoutError) as exc:
                last_error = exc
                close = getattr(upstream, "aclose", None)
                if close is not None:
                    await close()
                if yielded or isinstance(exc, ProviderRequestError):
                    raise ProviderError(
                        f"stream failed after response started on {tier.value}: {exc}"
                    ) from exc
                continue

        if isinstance(last_error, ProviderError):
            raise last_error
        if last_error is not None:
            raise ProviderError(f"stream provider timed out: {last_error}") from last_error
        raise ProviderError("stream provider failed without an upstream attempt")
