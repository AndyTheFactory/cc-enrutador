from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Raised on a transport/availability failure. Triggers provider-failure escalation."""


class ProviderRequestError(ProviderError):
    """Raised when the provider rejected the request itself (bad request, auth, content
    policy, etc). Not a transport failure, so it must not trigger escalation — retrying
    the same malformed/rejected request against a bigger model wastes upstream usage."""


class ExecutionProvider(Protocol):
    async def complete(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> dict[str, Any]: ...

    def stream(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> AsyncIterator[bytes]: ...
