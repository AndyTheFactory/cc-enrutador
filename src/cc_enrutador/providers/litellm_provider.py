from __future__ import annotations

import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, cast

from cc_enrutador.config import ProviderModelConfig
from cc_enrutador.providers.base import ProviderError
from cc_enrutador.providers.headers import headers_for_non_anthropic
from cc_enrutador.providers.normalization import (
    anthropic_request_to_litellm,
    litellm_chunk_to_anthropic_sse,
    litellm_response_to_anthropic,
)

CompletionCallable = Callable[..., Awaitable[Any]]


class LiteLLMProvider:
    def __init__(
        self,
        config: ProviderModelConfig,
        completion: CompletionCallable | None = None,
    ) -> None:
        self.config = config
        self._completion = completion

    async def _call(self, *, stream: bool, body: Mapping[str, Any]) -> Any:
        if self._completion is None:
            import litellm

            completion = litellm.acompletion
        else:
            completion = self._completion

        kwargs = anthropic_request_to_litellm(body)
        kwargs["model"] = self.config.model
        kwargs["stream"] = stream

        if self.config.api_base:
            kwargs["api_base"] = self.config.api_base
        if self.config.api_key_env:
            api_key = os.getenv(self.config.api_key_env)
            if api_key:
                kwargs["api_key"] = api_key

        try:
            return await completion(**kwargs)
        except Exception as exc:
            raise ProviderError(f"LiteLLM execution failed: {exc}") from exc

    async def complete(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> dict[str, Any]:
        # Explicitly normalize/filter headers even though LiteLLM is invoked as a Python API.
        headers_for_non_anthropic(headers)
        response = await self._call(stream=False, body=body)
        return litellm_response_to_anthropic(response, self.config.model)

    async def stream(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> AsyncIterator[bytes]:
        headers_for_non_anthropic(headers)
        stream = await self._call(stream=True, body=body)
        yielded_start = False
        try:
            async for chunk in cast(Any, stream):
                for event in litellm_chunk_to_anthropic_sse(
                    chunk,
                    model=self.config.model,
                    include_start=not yielded_start,
                ):
                    yielded_start = True
                    yield event
        except Exception as exc:
            raise ProviderError(f"LiteLLM streaming failed: {exc}") from exc
