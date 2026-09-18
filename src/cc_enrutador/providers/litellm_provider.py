from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, cast

from cc_enrutador.config import ProviderModelConfig
from cc_enrutador.providers.base import ProviderError, ProviderRequestError
from cc_enrutador.providers.litellm_runtime import load_litellm
from cc_enrutador.providers.normalization import (
    LiteLLMStreamNormalizer,
    anthropic_request_to_litellm,
    litellm_response_to_anthropic,
)

CompletionCallable = Callable[..., Awaitable[Any]]

# litellm exception names that mean "the request itself was rejected", not "the
# transport/backend is unavailable" — these must not trigger provider-failure
# escalation to a different tier (see functional.md §8).
_NON_ESCALATING_LITELLM_EXCEPTIONS = frozenset(
    {
        "BadRequestError",
        "InvalidRequestError",
        "AuthenticationError",
        "PermissionDeniedError",
        "NotFoundError",
        "UnprocessableEntityError",
        "ContentPolicyViolationError",
        "ContextWindowExceededError",
    }
)


def _wrap_completion_error(exc: Exception) -> ProviderError:
    if type(exc).__name__ in _NON_ESCALATING_LITELLM_EXCEPTIONS:
        return ProviderRequestError(f"LiteLLM rejected the request: {exc}")
    return ProviderError(f"LiteLLM execution failed: {exc}")


class LiteLLMProvider:
    def __init__(
        self,
        config: ProviderModelConfig,
        completion: CompletionCallable | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.config = config
        self._completion = completion
        self.timeout_seconds = timeout_seconds

    async def _call(self, *, stream: bool, body: Mapping[str, Any]) -> Any:
        if self._completion is None:
            litellm = load_litellm()
            completion = litellm.acompletion
        else:
            completion = self._completion

        kwargs = anthropic_request_to_litellm(body)
        kwargs["model"] = self.config.model
        kwargs["stream"] = stream
        if self.timeout_seconds is not None:
            kwargs["timeout"] = self.timeout_seconds

        if self.config.api_base:
            kwargs["api_base"] = self.config.api_base
        if self.config.api_key_env:
            api_key = os.getenv(self.config.api_key_env)
            if api_key:
                kwargs["api_key"] = api_key

        try:
            return await completion(**kwargs)
        except Exception as exc:
            raise _wrap_completion_error(exc) from exc

    async def complete(
        self,
        body: Mapping[str, Any],
        _headers: Mapping[str, str],
    ) -> dict[str, Any]:
        # Inbound headers (including any Claude OAuth) are never forwarded to LiteLLM;
        # credentials come only from self.config.api_key_env in _call().
        response = await self._call(stream=False, body=body)
        try:
            return litellm_response_to_anthropic(response, self.config.model)
        except ValueError as exc:
            raise ProviderRequestError(f"LiteLLM returned a malformed response: {exc}") from exc

    async def stream(
        self,
        body: Mapping[str, Any],
        _headers: Mapping[str, str],
    ) -> AsyncIterator[bytes]:
        stream = await self._call(stream=True, body=body)
        normalizer = LiteLLMStreamNormalizer(self.config.model)
        try:
            async for chunk in cast(Any, stream):
                for event in normalizer.feed(chunk):
                    yield event
        except Exception as exc:
            raise ProviderError(f"LiteLLM streaming failed: {exc}") from exc
