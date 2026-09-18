from __future__ import annotations

from cc_enrutador.config import AppConfig, ProviderModelConfig
from cc_enrutador.models import ClassificationResult, ComplexityTier, RouteDecision


def route_request(classification: ClassificationResult, config: AppConfig) -> RouteDecision:
    tier = classification.tier
    target = provider_for_tier(tier, config)
    fallback_chain = [
        ComplexityTier(item) for item in config.escalation.chain[tier.value]
    ]
    return RouteDecision(
        tier=tier,
        provider=target.provider,
        model=target.model,
        fallback_chain=fallback_chain,
    )


def provider_for_tier(tier: ComplexityTier, config: AppConfig) -> ProviderModelConfig:
    if tier is ComplexityTier.SIMPLE:
        return config.models.simple
    if tier is ComplexityTier.MEDIUM:
        return config.models.medium
    return config.models.complex
