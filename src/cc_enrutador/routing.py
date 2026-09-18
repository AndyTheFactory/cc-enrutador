from __future__ import annotations

from cc_enrutador.config import AppConfig, ProviderModelConfig
from cc_enrutador.models import ComplexityTier


def provider_for_tier(tier: ComplexityTier, config: AppConfig) -> ProviderModelConfig:
    if tier is ComplexityTier.SIMPLE:
        return config.models.simple
    if tier is ComplexityTier.MEDIUM:
        return config.models.medium
    return config.models.complex
