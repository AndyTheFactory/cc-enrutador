from __future__ import annotations

from cc_enrutador.config import AppConfig
from cc_enrutador.models import ClassificationResult, ComplexityTier
from cc_enrutador.routing import route_request


def config() -> AppConfig:
    return AppConfig.model_validate(
        {
            "classifier": {
                "mode": "heuristic",
                "model": {"provider": "litellm", "model": "classifier"},
            },
            "models": {
                "simple": {"provider": "litellm", "model": "local/simple"},
                "medium": {"provider": "litellm", "model": "remote/medium"},
                "complex": {
                    "provider": "anthropic_subscription",
                    "model": "passthrough",
                    "api_base": "https://api.anthropic.com",
                },
            },
        }
    )


def result(tier: ComplexityTier) -> ClassificationResult:
    return ClassificationResult(
        tier=tier,
        method="heuristic",
        reason="test",
        confidence=1.0,
        latency_ms=0.0,
    )


def test_routes_each_tier_to_configured_target() -> None:
    cfg = config()

    simple = route_request(result(ComplexityTier.SIMPLE), cfg)
    medium = route_request(result(ComplexityTier.MEDIUM), cfg)
    complex_route = route_request(result(ComplexityTier.COMPLEX), cfg)

    assert (simple.provider, simple.model) == ("litellm", "local/simple")
    assert (medium.provider, medium.model) == ("litellm", "remote/medium")
    assert (complex_route.provider, complex_route.model) == (
        "anthropic_subscription",
        "passthrough",
    )
    assert simple.fallback_chain == [ComplexityTier.MEDIUM, ComplexityTier.COMPLEX]
    assert medium.fallback_chain == [ComplexityTier.COMPLEX]
    assert complex_route.fallback_chain == []
