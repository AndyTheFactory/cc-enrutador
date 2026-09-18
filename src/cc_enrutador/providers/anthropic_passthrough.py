from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from cc_enrutador.config import ProviderModelConfig
from cc_enrutador.providers.base import ProviderError
from cc_enrutador.providers.headers import headers_for_anthropic


class AnthropicPassthroughProvider:
    def __init__(
        self,
        config: ProviderModelConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.config = config
        self._client = client

    @property
    def messages_url(self) -> str:
        assert self.config.api_base is not None
        return self.config.api_base.rstrip("/") + "/v1/messages"

    async def complete(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> dict[str, Any]:
        request_body = dict(body)
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            response = await client.post(
                self.messages_url,
                headers=headers_for_anthropic(headers),
                json=request_body,
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ProviderError("Anthropic returned a non-object JSON response")
            return payload
        except (httpx.HTTPError, ValueError) as exc:
            raise ProviderError(f"Anthropic passthrough failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def raw_request(
        self,
        method: str,
        path: str,
        headers: Mapping[str, str],
        content: bytes,
        query: str = "",
    ) -> tuple[int, dict[str, str], bytes]:
        assert self.config.api_base is not None
        url = self.config.api_base.rstrip("/") + "/" + path.lstrip("/")
        if query:
            url = f"{url}?{query}"

        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            response = await client.request(
                method,
                url,
                headers=headers_for_anthropic(headers),
                content=content,
            )
            response_headers = {
                key: value
                for key, value in response.headers.items()
                if key.lower() not in {"content-length", "transfer-encoding", "connection"}
            }
            return response.status_code, response_headers, response.content
        except httpx.HTTPError as exc:
            raise ProviderError(f"Anthropic auxiliary passthrough failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def stream(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> AsyncIterator[bytes]:
        request_body = dict(body)
        client = self._client or httpx.AsyncClient()
        owns_client = self._client is None
        try:
            async with client.stream(
                "POST",
                self.messages_url,
                headers=headers_for_anthropic(headers),
                json=request_body,
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise ProviderError(f"Anthropic streaming passthrough failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()
