from __future__ import annotations

import httpx

from cc_enrutador.config import AppConfig
from cc_enrutador.models import RouteDecision
from cc_enrutador.providers.anthropic_passthrough import AnthropicPassthroughProvider
from cc_enrutador.providers.base import ExecutionProvider
from cc_enrutador.providers.litellm_provider import CompletionCallable, LiteLLMProvider
from cc_enrutador.routing import provider_for_tier


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

    def get(self, route: RouteDecision) -> ExecutionProvider:
        target = provider_for_tier(route.tier, self.config)
        if target.provider == "litellm":
            return LiteLLMProvider(target, completion=self.litellm_completion)
        if target.provider == "anthropic_subscription":
            return AnthropicPassthroughProvider(target, client=self.anthropic_client)
        raise ValueError(f"unsupported execution provider: {target.provider}")
