from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict

from cc_enrutador.classifier import ClassifierService
from cc_enrutador.config import AppConfig
from cc_enrutador.execution import ProviderRegistry
from cc_enrutador.models import ClassificationResult
from cc_enrutador.providers.base import ProviderError
from cc_enrutador.routing import route_request
from cc_enrutador.streaming import forward_stream


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
) -> FastAPI:
    app = FastAPI(title="cc-enrutador")
    classification_service = classifier or ClassifierService(config)
    provider_registry = providers or ProviderRegistry(config)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/debug/classify", response_model=ClassificationResult)
    async def debug_classify(request: ClassifyRequest) -> ClassificationResult:
        if not config.debug.classification_endpoint:
            raise HTTPException(status_code=404, detail="classification debug endpoint disabled")
        return await classification_service.classify(request.model_dump(exclude_none=True))

    @app.post("/v1/messages")
    async def messages(request_body: ClassifyRequest, request: Request) -> Any:
        body = request_body.model_dump(exclude_none=True)
        classification = await classification_service.classify(body)
        route = route_request(classification, config)
        provider = provider_registry.get(route)
        headers = dict(request.headers)

        if body.get("stream") is True:
            upstream_stream = provider.stream(body, headers)

            return StreamingResponse(
                forward_stream(upstream_stream, request.is_disconnected),
                media_type="text/event-stream",
                headers={"cache-control": "no-cache"},
            )

        try:
            payload = await provider.complete(body, headers)
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return JSONResponse(payload)

    return app
