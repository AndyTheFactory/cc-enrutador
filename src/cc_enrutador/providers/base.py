from __future__ import annotations

from collections.abc import AsyncIterator, Mapping
from typing import Any, Protocol


class ProviderError(RuntimeError):
    """Raised when an upstream provider cannot satisfy a request."""


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
