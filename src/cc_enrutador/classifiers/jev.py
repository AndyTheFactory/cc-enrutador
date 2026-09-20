from __future__ import annotations

import math
import os
import time
from collections.abc import Mapping
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from cc_enrutador.config import ClassifierConfig
from cc_enrutador.models import ComplexityTier


class JevSchemaError(ValueError):
    """Response did not contain a valid three-tier Choice decision."""


class JevProviderError(RuntimeError):
    """OpenRouter Decisions call failed; message contains no upstream body."""


class JevChoiceDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    choice: ComplexityTier
    probabilities: dict[ComplexityTier, float]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    model: str | None = None
    latency_ms: float = Field(ge=0, allow_inf_nan=False)
    usage: dict[str, int | float] | None = None

    @model_validator(mode="after")
    def validate_probabilities(self) -> JevChoiceDecision:
        if set(self.probabilities) != set(ComplexityTier):
            raise ValueError("Choice probabilities must contain exactly three tiers")
        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in self.probabilities.values()):
            raise ValueError("Choice probabilities must be finite values in [0,1]")
        return self


def parse_choice(
    response: Mapping[str, Any], config: ClassifierConfig, latency_ms: float = 0
) -> JevChoiceDecision:
    jev = config.jev
    if jev is None:
        raise JevSchemaError("JEV config missing")
    answers = response.get("answers")
    if not isinstance(answers, Mapping):
        raise JevSchemaError("Choice answers missing")
    answer = answers.get(jev.question_id)
    if not isinstance(answer, Mapping) or answer.get("type") != "choice":
        raise JevSchemaError("Expected task_tier Choice answer")
    try:
        decision = JevChoiceDecision.model_validate(
            {
                "choice": answer.get("choice"),
                "probabilities": answer.get("probabilities"),
                "confidence": answer.get("confidence"),
                "model": response.get("model"),
                "latency_ms": latency_ms,
                "usage": response.get("usage"),
            }
        )
    except (ValidationError, ValueError, TypeError):
        raise JevSchemaError("Invalid Choice answer fields") from None
    if abs(sum(decision.probabilities.values()) - 1) > jev.policy.probability_sum_tolerance:
        raise JevSchemaError("Choice probabilities do not sum to one")
    return decision


def select_tier(
    decision: JevChoiceDecision, config: ClassifierConfig
) -> tuple[ComplexityTier, str]:
    if config.jev is None:
        raise ValueError("JEV config missing")
    policy = config.jev.policy
    complex_probability = decision.probabilities[ComplexityTier.COMPLEX]
    if complex_probability >= policy.complex_min_probability:
        return ComplexityTier.COMPLEX, "jev:complex-probability"
    if (
        decision.choice is ComplexityTier.SIMPLE
        and decision.probabilities[ComplexityTier.SIMPLE] >= policy.simple_min_probability
        and complex_probability < policy.simple_max_complex_probability
    ):
        return ComplexityTier.SIMPLE, "jev:confident-simple"
    return ComplexityTier.MEDIUM, "jev:conservative-medium"


class JevAdapter:
    def __init__(self, config: ClassifierConfig, client: httpx.AsyncClient | None = None) -> None:
        if config.model.provider != "openrouter_decisions" or config.jev is None:
            raise ValueError("JEV provider configuration required")
        self.config = config
        self.client = client

    async def decide(
        self,
        task: str,
        system: str = "",
        is_agentic: bool = False,
        is_mid_loop: bool = False,
    ) -> JevChoiceDecision:
        api_key = os.getenv(self.config.model.api_key_env or "")
        if not api_key:
            raise JevProviderError("OpenRouter classifier API key is missing")
        jev = self.config.jev
        assert jev is not None
        endpoint = self.config.model.api_base or "https://openrouter.ai/api/alpha/decisions"
        payload = {
            "model": self.config.model.model,
            "state": {
                "task": task,
                "system_context": system,
                "is_agentic": is_agentic,
                "is_mid_loop": is_mid_loop,
            },
            "questions": {
                jev.question_id: {
                    "type": "choice",
                    "instructions": jev.instructions,
                    "criteria": jev.criteria.model_dump(),
                }
            },
        }
        started = time.perf_counter()
        try:
            if self.client is None:
                async with httpx.AsyncClient(timeout=self.config.timeout_ms / 1000) as client:
                    response = await client.post(
                        endpoint,
                        json=payload,
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
            else:
                response = await self.client.post(
                    endpoint,
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}"},
                    timeout=self.config.timeout_ms / 1000,
                )
            response.raise_for_status()
            return parse_choice(
                response.json(), self.config, (time.perf_counter() - started) * 1000
            )
        except httpx.TimeoutException:
            raise JevProviderError("OpenRouter Decisions request timed out") from None
        except httpx.HTTPStatusError as exc:
            code = exc.response.status_code
            category = (
                "authentication"
                if code in (401, 403)
                else "rate-limit"
                if code in (429, 529)
                else "upstream"
            )
            raise JevProviderError(f"OpenRouter Decisions {category} error ({code})") from None
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            if isinstance(exc, JevSchemaError):
                raise
            raise JevProviderError("OpenRouter Decisions transport or JSON error") from None
