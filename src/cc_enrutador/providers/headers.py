from __future__ import annotations

from collections.abc import Mapping

_BLOCKED_HOP_HEADERS = {
    "connection",
    "content-length",
    "host",
    "transfer-encoding",
}


def normalized_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {key.lower(): value for key, value in headers.items()}


def headers_for_non_anthropic(headers: Mapping[str, str]) -> dict[str, str]:
    normalized = normalized_headers(headers)
    return {
        key: value
        for key, value in normalized.items()
        if key not in _BLOCKED_HOP_HEADERS
        and key not in {"authorization", "x-api-key"}
        and not key.startswith("anthropic-")
    }


def headers_for_anthropic(headers: Mapping[str, str]) -> dict[str, str]:
    normalized = normalized_headers(headers)
    allowed = {
        "authorization",
        "x-api-key",
        "anthropic-version",
        "anthropic-beta",
        "content-type",
        "accept",
        "user-agent",
    }
    result = {
        key: value
        for key, value in normalized.items()
        if key in allowed and key not in _BLOCKED_HOP_HEADERS
    }
    result.setdefault("content-type", "application/json")
    return result
