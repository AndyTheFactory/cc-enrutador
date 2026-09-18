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
            "timeout_ms": 1500,
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


def test_classifier_timeout_fields_must_match() -> None:
    data = base()
    data["timeouts"] = {"classifier_ms": 2000}

    with pytest.raises(ValidationError, match="must match"):
        AppConfig.model_validate(data)


def test_classifier_timeout_fields_match_by_default() -> None:
    config = AppConfig.model_validate(base())

    assert config.classifier.timeout_ms == config.timeouts.classifier_ms == 1500
