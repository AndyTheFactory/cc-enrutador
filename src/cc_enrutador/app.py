from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict

from cc_enrutador.classifier import ClassifierService
from cc_enrutador.config import AppConfig
from cc_enrutador.models import ClassificationResult


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
) -> FastAPI:
    app = FastAPI(title="cc-enrutador")
    service = classifier or ClassifierService(config)

    @app.post("/debug/classify", response_model=ClassificationResult)
    async def debug_classify(request: ClassifyRequest) -> ClassificationResult:
        if not config.debug.classification_endpoint:
            raise HTTPException(status_code=404, detail="classification debug endpoint disabled")
        return await service.classify(request.model_dump(exclude_none=True))

    return app
