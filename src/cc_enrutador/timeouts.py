from __future__ import annotations

from cc_enrutador.config import TimeoutsConfig
from cc_enrutador.models import ComplexityTier


class TimeoutPolicy:
    def __init__(self, config: TimeoutsConfig) -> None:
        self.config = config

    @property
    def classifier_seconds(self) -> float:
        return self.config.classifier_ms / 1000

    @property
    def connect_seconds(self) -> float:
        return self.config.connect_ms / 1000

    def request_seconds(self, tier: ComplexityTier) -> float:
        return self.config.request_ms[tier.value] / 1000

    def stream_idle_seconds(self, tier: ComplexityTier) -> float:
        return self.config.stream_idle_ms[tier.value] / 1000
