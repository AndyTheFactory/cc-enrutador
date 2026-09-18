from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from cc_enrutador.config import AppConfig


def base() -> dict[str, Any]:
    return {
        "classifier": {
            "mode": "heuristic",
            "model": {"provider": "litellm", "model": "classifier"},
        },
        "models": {
            "simple": {"provider": "litellm", "model": "simple"},
            "medium": {"provider": "litellm", "model": "medium"},
            "complex": {
                "provider": "anthropic_subscription",
                "model": "passthrough",
                "api_base": "https://api.anthropic.com",
            },
        },
    }


@pytest.mark.parametrize(
    ("section", "value", "message"),
    [
        ("telemetry", {"persist_prompts": True}, "persist_prompts=true"),
        ("telemetry", {"preserve_claude_default": False}, "literal_error"),
        ("debug", {"capture_bodies": True}, "capture_bodies=true"),
    ],
)
def test_v1_rejects_unsupported_sensitive_capture_settings(
    section: str,
    value: dict[str, Any],
    message: str,
) -> None:
    data = base()
    data[section] = value

    with pytest.raises(ValidationError) as exc:
        AppConfig.model_validate(data)

    assert message in str(exc.value)
