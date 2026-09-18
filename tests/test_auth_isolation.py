from __future__ import annotations

from cc_enrutador.providers.headers import (
    headers_for_anthropic,
    headers_for_non_anthropic,
)


def test_non_anthropic_headers_strip_claude_credentials() -> None:
    headers = {
        "Authorization": "Bearer fake-claude-oauth",
        "x-api-key": "fake-anthropic-key",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "tools-2025",
        "x-request-id": "request-1",
    }

    filtered = headers_for_non_anthropic(headers)

    assert "authorization" not in filtered
    assert "x-api-key" not in filtered
    assert "anthropic-version" not in filtered
    assert "anthropic-beta" not in filtered
    assert filtered["x-request-id"] == "request-1"


def test_anthropic_headers_preserve_subscription_and_protocol_headers() -> None:
    headers = {
        "Authorization": "Bearer fake-claude-oauth",
        "x-api-key": "fake-anthropic-key",
        "anthropic-version": "2023-06-01",
        "anthropic-beta": "tools-2025",
        "content-type": "application/json",
        "host": "router.local",
    }

    filtered = headers_for_anthropic(headers)

    assert filtered["authorization"] == "Bearer fake-claude-oauth"
    assert filtered["x-api-key"] == "fake-anthropic-key"
    assert filtered["anthropic-version"] == "2023-06-01"
    assert filtered["anthropic-beta"] == "tools-2025"
    assert "host" not in filtered
