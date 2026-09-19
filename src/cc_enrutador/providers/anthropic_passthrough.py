from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from cc_enrutador.config import ProviderModelConfig
from cc_enrutador.providers.base import ProviderError, ProviderResponseError
from cc_enrutador.providers.headers import headers_for_anthropic

# 5xx and 429 are transport/availability failures worth escalating to a different
# backend; other 4xx mean the request itself was rejected and escalating would just
# waste usage on a request that will fail identically upstream.
_NON_ESCALATING_STATUS = range(400, 500)
_RETRYABLE_STATUS_EXCEPTIONS = {429}
_MAX_ERROR_MESSAGE_CHARS = 1000
_HOP_BY_HOP_RESPONSE_HEADERS = {"content-length", "transfer-encoding", "connection"}


def _response_headers(response: httpx.Response) -> dict[str, str]:
    return {
        key: value
        for key, value in response.headers.items()
        if key.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS
    }


def _response_error_summary(response: httpx.Response) -> str:
    error_type = "unknown"
    message = response.reason_phrase
    request_id = response.headers.get("request-id") or response.headers.get("x-request-id")
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        request_id = payload.get("request_id") or request_id
        error = payload.get("error")
        if isinstance(error, dict):
            error_type = str(error.get("type", error_type))
            message = str(error.get("message", message))
    message = message[:_MAX_ERROR_MESSAGE_CHARS]
    return (
        f"status={response.status_code} error_type={error_type!r} "
        f"request_id={request_id!r} message={message!r}"
    )


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        summary = _response_error_summary(exc.response)
        retryable = status not in _NON_ESCALATING_STATUS or status in _RETRYABLE_STATUS_EXCEPTIONS
        raise ProviderResponseError(
            f"Anthropic upstream response: {summary}",
            status_code=status,
            headers=_response_headers(exc.response),
            content=exc.response.content,
            retryable=retryable,
        ) from exc


class AnthropicPassthroughProvider:
    def __init__(
        self,
        config: ProviderModelConfig,
        client: httpx.AsyncClient | None = None,
        connect_timeout_seconds: float | None = None,
    ) -> None:
        self.config = config
        self._client = client
        self.connect_timeout_seconds = connect_timeout_seconds

    @property
    def messages_url(self) -> str:
        assert self.config.api_base is not None
        return self.config.api_base.rstrip("/") + "/v1/messages"

    async def complete(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
        query: str = "",
    ) -> dict[str, Any]:
        request_body = dict(body)
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(None, connect=self.connect_timeout_seconds)
        )
        owns_client = self._client is None
        try:
            url = f"{self.messages_url}?{query}" if query else self.messages_url
            response = await client.post(
                url,
                headers=headers_for_anthropic(headers),
                json=request_body,
            )
            _raise_for_status(response)
            try:
                payload = response.json()
            except ValueError as exc:
                raise ProviderError(
                    "Anthropic returned undecodable JSON: "
                    f"status={response.status_code} "
                    f"content_type={response.headers.get('content-type')!r} "
                    f"content_encoding={response.headers.get('content-encoding')!r} "
                    f"body_bytes={len(response.content)} error={exc}"
                ) from exc
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

        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(None, connect=self.connect_timeout_seconds)
        )
        owns_client = self._client is None
        try:
            response = await client.request(
                method,
                url,
                headers=headers_for_anthropic(headers),
                content=content,
            )
            return response.status_code, _response_headers(response), response.content
        except httpx.HTTPError as exc:
            raise ProviderError(f"Anthropic auxiliary passthrough failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()

    async def stream(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
        query: str = "",
    ) -> AsyncIterator[bytes]:
        request_body = dict(body)
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(None, connect=self.connect_timeout_seconds)
        )
        owns_client = self._client is None
        try:
            url = f"{self.messages_url}?{query}" if query else self.messages_url
            async with client.stream(
                "POST",
                url,
                headers=headers_for_anthropic(headers),
                json=request_body,
            ) as response:
                if response.is_error:
                    await response.aread()
                _raise_for_status(response)
                async for chunk in response.aiter_bytes():
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            raise ProviderError(f"Anthropic streaming passthrough failed: {exc}") from exc
        finally:
            if owns_client:
                await client.aclose()
