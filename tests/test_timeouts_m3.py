from __future__ import annotations

from cc_enrutador.config import TimeoutsConfig
from cc_enrutador.models import ComplexityTier
from cc_enrutador.timeouts import TimeoutPolicy


def test_timeout_policy_exposes_effective_seconds() -> None:
    policy = TimeoutPolicy(
        TimeoutsConfig(
            classifier_ms=1500,
            connect_ms=5000,
            request_ms={"simple": 1000, "medium": 2000, "complex": 3000},
            stream_idle_ms={"simple": 4000, "medium": 5000, "complex": 6000},
        )
    )

    assert policy.classifier_seconds == 1.5
    assert policy.connect_seconds == 5
    assert policy.request_seconds(ComplexityTier.MEDIUM) == 2
    assert policy.stream_idle_seconds(ComplexityTier.COMPLEX) == 6
