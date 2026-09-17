from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from cc_enrutador.config import AppConfig


def base() -> dict[str, Any]:
    return {
        "classifier": {
            "mode": "hybrid",
            "model": {"provider": "litellm", "model": "test/classifier"},
        },
        "models": {
            "simple": {"provider": "litellm", "model": "test/simple"},
            "medium": {"provider": "litellm", "model": "test/medium"},
            "complex": {
                "provider": "anthropic_subscription",
                "model": "passthrough",
                "api_base": "https://api.anthropic.com",
            },
        },
    }


def test_unknown_prompt_placeholder_is_rejected() -> None:
    data = base()
    data["classifier"]["prompt"] = "Task: {task}\nUnknown: {banana}"

    with pytest.raises(ValidationError, match="unsupported classification prompt"):
        AppConfig.model_validate(data)


def test_prompt_requires_task_placeholder() -> None:
    data = base()
    data["classifier"]["prompt"] = "Return only 1, 2, or 3."

    with pytest.raises(ValidationError, match="must contain"):
        AppConfig.model_validate(data)


def test_duplicate_classifier_labels_are_rejected() -> None:
    data = base()
    data["classifier"]["output"] = {"simple": "1", "medium": "1", "complex": "3"}

    with pytest.raises(ValidationError, match="must be unique"):
        AppConfig.model_validate(data)


def test_escalation_cycle_is_rejected() -> None:
    data = base()
    data["escalation"] = {"chain": {"simple": ["medium"], "medium": ["simple"], "complex": []}}

    with pytest.raises(ValidationError, match="cycle"):
        AppConfig.model_validate(data)


def test_non_positive_tier_timeout_is_rejected() -> None:
    data = base()
    data["timeouts"] = {"request_ms": {"simple": 0, "medium": 1, "complex": 1}}

    with pytest.raises(ValidationError, match="must be positive"):
        AppConfig.model_validate(data)
