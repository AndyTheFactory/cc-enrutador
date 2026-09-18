from __future__ import annotations

from cc_enrutador.config import AppConfig
from cc_enrutador.models import ComplexityTier
from cc_enrutador.operations import escalation_tiers, route_for_tier


def config(escalation: dict | None = None) -> AppConfig:
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
            **({"escalation": escalation} if escalation else {}),
        }
    )


def test_routes_each_tier_to_configured_target() -> None:
    cfg = config()

    simple = route_for_tier(ComplexityTier.SIMPLE, cfg)
    medium = route_for_tier(ComplexityTier.MEDIUM, cfg)
    complex_route = route_for_tier(ComplexityTier.COMPLEX, cfg)

    assert (simple.provider, simple.model) == ("litellm", "local/simple")
    assert (medium.provider, medium.model) == ("litellm", "remote/medium")
    assert (complex_route.provider, complex_route.model) == (
        "anthropic_subscription",
        "passthrough",
    )
    assert simple.fallback_chain == [ComplexityTier.MEDIUM, ComplexityTier.COMPLEX]
    assert medium.fallback_chain == [ComplexityTier.COMPLEX]
    assert complex_route.fallback_chain == []


def test_escalation_disabled_never_leaves_initial_tier() -> None:
    cfg = config({"enabled": False})

    assert escalation_tiers(ComplexityTier.SIMPLE, cfg) == [ComplexityTier.SIMPLE]
    assert escalation_tiers(ComplexityTier.MEDIUM, cfg) == [ComplexityTier.MEDIUM]


def test_provider_failure_flags_gate_individual_hops() -> None:
    cfg = config({"provider_failure": {"simple_to_medium": False, "medium_to_complex": True}})

    assert escalation_tiers(ComplexityTier.SIMPLE, cfg) == [ComplexityTier.SIMPLE]
    assert escalation_tiers(ComplexityTier.MEDIUM, cfg) == [
        ComplexityTier.MEDIUM,
        ComplexityTier.COMPLEX,
    ]
