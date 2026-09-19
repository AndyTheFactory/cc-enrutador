from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Raised on a transport/availability failure. Triggers provider-failure escalation."""


class ProviderRequestError(ProviderError):
    """Raised when the provider rejected the request itself (bad request, auth, content
    policy, etc). Not a transport failure, so it must not trigger escalation — retrying
    the same malformed/rejected request against a bigger model wastes upstream usage."""


class ProviderResponseError(ProviderError):
    """An upstream HTTP response that must be relayed to the client unchanged."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        headers: Mapping[str, str],
        content: bytes,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.headers = dict(headers)
        self.content = content
        self.retryable = retryable


class ExecutionProvider(Protocol):
    async def complete(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
        query: str = "",
    ) -> dict[str, Any]: ...

    def stream(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
        query: str = "",
    ) -> AsyncIterator[bytes]: ...
