from __future__ import annotations

import httpx

from cc_enrutador.config import AppConfig
from cc_enrutador.models import RouteDecision
from cc_enrutador.providers.anthropic_passthrough import AnthropicPassthroughProvider
from cc_enrutador.providers.base import ExecutionProvider
from cc_enrutador.providers.litellm_provider import CompletionCallable, LiteLLMProvider
from cc_enrutador.routing import provider_for_tier
from cc_enrutador.timeouts import TimeoutPolicy


class ProviderRegistry:
    def __init__(
        self,
        config: AppConfig,
        *,
        litellm_completion: CompletionCallable | None = None,
        anthropic_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self.litellm_completion = litellm_completion
        self.anthropic_client = anthropic_client
        self.timeouts = TimeoutPolicy(config.timeouts)

    def anthropic(self) -> AnthropicPassthroughProvider:
        return AnthropicPassthroughProvider(
            self.config.models.complex,
            client=self.anthropic_client,
            connect_timeout_seconds=self.timeouts.connect_seconds,
        )

    def get(self, route: RouteDecision) -> ExecutionProvider:
        target = provider_for_tier(route.tier, self.config)
        if target.provider == "litellm":
            return LiteLLMProvider(
                target,
                completion=self.litellm_completion,
                timeout_seconds=self.timeouts.request_seconds(route.tier),
            )
        if target.provider == "anthropic_subscription":
            return AnthropicPassthroughProvider(
                target,
                client=self.anthropic_client,
                connect_timeout_seconds=self.timeouts.connect_seconds,
            )
        raise ValueError(f"unsupported execution provider: {target.provider}")
