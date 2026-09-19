from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict

from cc_enrutador.classifier import ClassifierService
from cc_enrutador.config import AppConfig
from cc_enrutador.execution import ProviderRegistry
from cc_enrutador.logging import get_logger
from cc_enrutador.models import ClassificationResult, ComplexityTier
from cc_enrutador.operations import ExecutionService, route_for_tier
from cc_enrutador.providers.base import ProviderError, ProviderResponseError
from cc_enrutador.state import TaskStateStore, task_identity
from cc_enrutador.streaming import forward_stream
from cc_enrutador.task_extraction import is_harm_monitor_request
from cc_enrutador.telemetry import RouterTelemetryEvent, TelemetryRecorder

_LOGGER = get_logger(__name__)


class ClassifyRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    messages: list[dict[str, Any]]
    system: str | list[dict[str, Any]] | None = None
    tools: list[dict[str, Any]] | None = None
    stream: bool | None = None
    model: str | None = None


def create_app(
    config: AppConfig,
    classifier: ClassifierService | None = None,
    providers: ProviderRegistry | None = None,
    task_state: TaskStateStore | None = None,
    telemetry: TelemetryRecorder | None = None,
) -> FastAPI:
    app = FastAPI(title="cc-enrutador")
    classification_service = classifier or ClassifierService(config)
    provider_registry = providers or ProviderRegistry(config)
    state_store = task_state or TaskStateStore()
    telemetry_recorder = telemetry or TelemetryRecorder(config.telemetry)
    execution = ExecutionService(config, provider_registry, state_store)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.api_route("/api/hello", methods=["GET", "HEAD"])
    async def hello() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/debug/classify", response_model=ClassificationResult)
    async def debug_classify(request: ClassifyRequest) -> ClassificationResult:
        if not config.debug.classification_endpoint:
            raise HTTPException(status_code=404, detail="classification debug endpoint disabled")
        return await classification_service.classify(request.model_dump(exclude_none=True))

    @app.post("/v1/messages")
    async def messages(request_body: ClassifyRequest, request: Request) -> Any:
        started = time.perf_counter()
        body = request_body.model_dump(exclude_none=True)
        headers = dict(request.headers)
        request_id = headers.get("x-request-id") or uuid.uuid4().hex

        if is_harm_monitor_request(body):
            try:
                status, response_headers, content = await provider_registry.anthropic().raw_request(
                    request.method,
                    request.url.path,
                    headers,
                    await request.body(),
                    request.url.query,
                )
            except ProviderError as exc:
                _LOGGER.error(
                    "Anthropic passthrough failed request_id=%s method=%s path=%s "
                    "duration_ms=%.1f error_type=%s error=%s",
                    request_id,
                    request.method,
                    request.url.path,
                    (time.perf_counter() - started) * 1000,
                    type(exc).__name__,
                    exc,
                )
                raise HTTPException(status_code=502, detail=str(exc)) from exc
            return Response(
                content=content,
                status_code=status,
                headers=response_headers,
            )

        task_id = task_identity(body, headers)

        classification = await classification_service.classify(body)
        proposed_tier = classification.tier
        effective_tier = state_store.apply_floor(
            task_id,
            proposed_tier,
            never_demote=config.escalation.never_demote_within_task,
        )
        if effective_tier is not proposed_tier:
            classification = classification.model_copy(
                update={
                    "tier": effective_tier,
                    "reason": f"{classification.reason}|state-floor:{effective_tier.value}",
                }
            )

        initial_route = route_for_tier(effective_tier, config)
        attempts: list[ComplexityTier] = []

        if body.get("stream") is True:
            model_latencies: list[float] = []
            upstream_stream = execution.stream(
                effective_tier,
                task_id,
                body,
                headers,
                query=request.url.query,
                attempted_tiers=attempts,
                model_latency_ms=model_latencies,
            )

            try:
                first_chunk = await anext(upstream_stream)
            except StopAsyncIteration:
                first_chunk = None
            except ProviderError as exc:
                failed_tier = attempts[-1] if attempts else effective_tier
                failed_route = route_for_tier(failed_tier, config)
                _LOGGER.error(
                    "streaming model request failed request_id=%s task_id=%s tier=%s "
                    "target=%s attempted_tiers=%s duration_ms=%.1f error_type=%s error=%s",
                    request_id,
                    task_id,
                    failed_tier.value,
                    failed_route.model,
                    [tier.value for tier in attempts],
                    (time.perf_counter() - started) * 1000,
                    type(exc).__name__,
                    exc,
                )
                telemetry_recorder.emit(
                    RouterTelemetryEvent(
                        request_id=request_id,
                        task_id=task_id,
                        classifier_mode=config.classifier.mode,
                        classifier_method=classification.method,
                        tier=failed_tier,
                        reason=classification.reason,
                        confidence=classification.confidence,
                        classifier_latency_ms=classification.latency_ms,
                        model_latency_ms=sum(model_latencies),
                        target=failed_route.model,
                        fallback_path=attempts[1:],
                        total_latency_ms=(time.perf_counter() - started) * 1000,
                        status="failure",
                    )
                )
                if isinstance(exc, ProviderResponseError):
                    return Response(
                        content=exc.content,
                        status_code=exc.status_code,
                        headers=exc.headers,
                    )
                raise HTTPException(status_code=502, detail=str(exc)) from exc

            async def observed_stream() -> AsyncIterator[bytes]:
                status: Literal["success", "failure"] = "success"
                try:
                    if first_chunk is not None:
                        yield first_chunk
                    async for chunk in forward_stream(upstream_stream, request.is_disconnected):
                        yield chunk
                except Exception as exc:
                    status = "failure"
                    final_tier = attempts[-1] if attempts else effective_tier
                    final_route = route_for_tier(final_tier, config)
                    _LOGGER.error(
                        "streaming model request failed request_id=%s task_id=%s tier=%s "
                        "target=%s attempted_tiers=%s duration_ms=%.1f error_type=%s error=%s",
                        request_id,
                        task_id,
                        final_tier.value,
                        final_route.model,
                        [tier.value for tier in attempts],
                        (time.perf_counter() - started) * 1000,
                        type(exc).__name__,
                        exc,
                    )
                    raise
                finally:
                    final_tier = attempts[-1] if attempts else effective_tier
                    final_route = route_for_tier(final_tier, config)
                    telemetry_recorder.emit(
                        RouterTelemetryEvent(
                            request_id=request_id,
                            task_id=task_id,
                            classifier_mode=config.classifier.mode,
                            classifier_method=classification.method,
                            tier=final_tier,
                            reason=classification.reason,
                            confidence=classification.confidence,
                            classifier_latency_ms=classification.latency_ms,
                            model_latency_ms=sum(model_latencies),
                            target=final_route.model,
                            fallback_path=attempts[1:],
                            total_latency_ms=(time.perf_counter() - started) * 1000,
                            status=status,
                        )
                    )

            return StreamingResponse(
                observed_stream(),
                media_type="text/event-stream",
                headers={"cache-control": "no-cache"},
            )

        execution_started = time.perf_counter()
        try:
            result = await execution.complete(
                effective_tier,
                task_id,
                body,
                headers,
                query=request.url.query,
                attempted_tiers=attempts,
            )
        except ProviderError as exc:
            failed_tier = attempts[-1] if attempts else effective_tier
            failed_route = route_for_tier(failed_tier, config)
            _LOGGER.error(
                "model request failed request_id=%s task_id=%s tier=%s target=%s "
                "attempted_tiers=%s duration_ms=%.1f error_type=%s error=%s",
                request_id,
                task_id,
                failed_tier.value,
                failed_route.model,
                [tier.value for tier in attempts],
                (time.perf_counter() - started) * 1000,
                type(exc).__name__,
                exc,
            )
            telemetry_recorder.emit(
                RouterTelemetryEvent(
                    request_id=request_id,
                    task_id=task_id,
                    classifier_mode=config.classifier.mode,
                    classifier_method=classification.method,
                    tier=attempts[-1] if attempts else effective_tier,
                    reason=classification.reason,
                    confidence=classification.confidence,
                    classifier_latency_ms=classification.latency_ms,
                    model_latency_ms=(time.perf_counter() - execution_started) * 1000,
                    target=initial_route.model,
                    fallback_path=attempts[1:],
                    total_latency_ms=(time.perf_counter() - started) * 1000,
                    status="failure",
                )
            )
            if isinstance(exc, ProviderResponseError):
                return Response(
                    content=exc.content,
                    status_code=exc.status_code,
                    headers=exc.headers,
                )
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        telemetry_recorder.emit(
            RouterTelemetryEvent(
                request_id=request_id,
                task_id=task_id,
                classifier_mode=config.classifier.mode,
                classifier_method=classification.method,
                tier=result.final_route.tier,
                reason=classification.reason,
                confidence=classification.confidence,
                classifier_latency_ms=classification.latency_ms,
                model_latency_ms=result.model_latency_ms,
                target=result.final_route.model,
                fallback_path=result.attempted_tiers[1:],
                total_latency_ms=(time.perf_counter() - started) * 1000,
                status="success",
            )
        )
        return JSONResponse(result.payload)

    @app.api_route(
        "/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def auxiliary_passthrough(path: str, request: Request) -> Response:
        """Forward non-model Claude Code traffic directly to Anthropic without classification."""
        started = time.perf_counter()
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        try:
            status, response_headers, content = await provider_registry.anthropic().raw_request(
                request.method,
                path,
                dict(request.headers),
                await request.body(),
                request.url.query,
            )
        except ProviderError as exc:
            _LOGGER.error(
                "Anthropic auxiliary passthrough failed request_id=%s method=%s path=/%s "
                "duration_ms=%.1f error_type=%s error=%s",
                request_id,
                request.method,
                path,
                (time.perf_counter() - started) * 1000,
                type(exc).__name__,
                exc,
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return Response(
            content=content,
            status_code=status,
            headers=response_headers,
        )

    return app
