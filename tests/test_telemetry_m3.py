from __future__ import annotations

from cc_enrutador.config import TelemetryConfig
from cc_enrutador.models import ComplexityTier
from cc_enrutador.telemetry import RouterTelemetryEvent, TelemetryRecorder


def event() -> RouterTelemetryEvent:
    return RouterTelemetryEvent(
        request_id="request-1",
        task_id="task-1",
        classifier_mode="hybrid",
        classifier_method="heuristic",
        tier=ComplexityTier.MEDIUM,
        reason="default:medium",
        confidence=0.5,
        classifier_latency_ms=1.2,
        target="medium-model",
        fallback_path=[ComplexityTier.COMPLEX],
        total_latency_ms=42.0,
        status="success",
    )


def test_router_telemetry_can_be_disabled_independently() -> None:
    captured: list[RouterTelemetryEvent] = []
    recorder = TelemetryRecorder(TelemetryConfig(enabled=False), captured.append)

    recorder.emit(event())

    assert captured == []


def test_router_telemetry_emits_only_structured_metadata() -> None:
    captured: list[RouterTelemetryEvent] = []
    recorder = TelemetryRecorder(TelemetryConfig(enabled=True), captured.append)

    recorder.emit(event())

    assert len(captured) == 1
    serialized = captured[0].model_dump_json()
    assert "request-1" in serialized
    assert "medium-model" in serialized
    assert "authorization" not in serialized.lower()
    assert "prompt" not in serialized.lower()
