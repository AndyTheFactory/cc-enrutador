from __future__ import annotations

from cc_enrutador.providers.headers import (
    headers_for_anthropic,
    headers_for_non_anthropic,
)


def test_non_anthropic_boundary_strips_all_claude_auth_and_protocol_headers() -> None:
    inbound = {
        "Authorization": "Bearer fake-claude-oauth",
        "X-Api-Key": "fake-anthropic-api-key",
        "Anthropic-Version": "2023-06-01",
        "Anthropic-Beta": "dangerous-capability",
        "Cookie": "session=fake",
        "X-Request-ID": "request-1",
    }

    outbound = headers_for_non_anthropic(inbound)
    serialized = repr(outbound)

    assert "fake-claude-oauth" not in serialized
    assert "fake-anthropic-api-key" not in serialized
    assert "anthropic-version" not in outbound
    assert "anthropic-beta" not in outbound
    assert outbound["x-request-id"] == "request-1"


def test_anthropic_boundary_preserves_client_capability_headers_but_not_hop_headers() -> None:
    inbound = {
        "Authorization": "Bearer fake-claude-oauth",
        "Anthropic-Version": "2023-06-01",
        "Anthropic-Beta": "tools-test",
        "X-Custom-Claude-Header": "preserve-me",
        "Host": "router.local",
        "Connection": "keep-alive",
        "Content-Length": "123",
    }

    outbound = headers_for_anthropic(inbound)

    assert outbound["authorization"] == "Bearer fake-claude-oauth"
    assert outbound["anthropic-version"] == "2023-06-01"
    assert outbound["anthropic-beta"] == "tools-test"
    assert outbound["x-custom-claude-header"] == "preserve-me"
    assert "host" not in outbound
    assert "connection" not in outbound
    assert "content-length" not in outbound
