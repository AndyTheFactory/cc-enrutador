from __future__ import annotations

import asyncio
from typing import Any

from cc_enrutador.streaming import forward_stream


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_forward_stream_stops_and_closes_on_disconnect() -> None:
    closed = False
    checks = 0

    async def upstream() -> Any:
        nonlocal closed
        try:
            yield b"first"
            yield b"second"
        finally:
            closed = True

    async def disconnected() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 2

    async def collect() -> list[bytes]:
        result = []
        async for part in forward_stream(upstream(), disconnected):
            result.append(part)
        return result

    parts = run(collect())

    assert parts == [b"first"]
    assert closed is True
