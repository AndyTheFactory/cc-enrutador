from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class ComplexityTier(StrEnum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    COMPLEX = "complex"


class ClassificationResult(BaseModel):
    tier: ComplexityTier
    method: Literal["heuristic", "ai", "hybrid"]
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    latency_ms: float = Field(ge=0.0)
    cached: bool = False


class HeuristicDecision(BaseModel):
    tier: ComplexityTier
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    explicit_gate: bool



class RouteDecision(BaseModel):
    tier: ComplexityTier
    provider: str
    model: str
    fallback_chain: list[ComplexityTier] = Field(default_factory=list)
