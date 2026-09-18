from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from cc_enrutador.config import TelemetryConfig
from cc_enrutador.models import ComplexityTier

_LOGGER = logging.getLogger("cc_enrutador.telemetry")


class RouterTelemetryEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    request_id: str
    task_id: str
    classifier_mode: str
    classifier_method: str
    tier: ComplexityTier
    reason: str
    confidence: float
    classifier_latency_ms: float
    model_latency_ms: float | None = None
    target: str
    fallback_path: list[ComplexityTier] = Field(default_factory=list)
    total_latency_ms: float
    status: Literal["success", "failure"]


TelemetrySink = Callable[[RouterTelemetryEvent], None]


class TelemetryRecorder:
    def __init__(
        self,
        config: TelemetryConfig,
        sink: TelemetrySink | None = None,
    ) -> None:
        self.config = config
        self.sink = sink

    def emit(self, event: RouterTelemetryEvent) -> None:
        if not self.config.enabled:
            return
        if self.sink is not None:
            self.sink(event)
            return
        _LOGGER.info(json.dumps(event.model_dump(mode="json"), separators=(",", ":")))
