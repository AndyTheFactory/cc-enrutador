from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable


async def forward_stream(
    upstream: AsyncIterator[bytes],
    is_disconnected: Callable[[], Awaitable[bool]],
) -> AsyncIterator[bytes]:
    try:
        async for chunk in upstream:
            if await is_disconnected():
                break
            yield chunk
    finally:
        close = getattr(upstream, "aclose", None)
        if close is not None:
            await close()
