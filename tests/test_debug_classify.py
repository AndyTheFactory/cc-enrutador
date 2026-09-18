from __future__ import annotations

from fastapi.testclient import TestClient

from cc_enrutador.app import create_app
from cc_enrutador.classifier import ClassifierService
from cc_enrutador.config import AppConfig


def config(*, enabled: bool = True) -> AppConfig:
    return AppConfig.model_validate(
        {
            "classifier": {
                "mode": "heuristic",
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
            "debug": {"classification_endpoint": enabled},
        }
    )


def test_debug_classify_returns_result_without_execution_provider() -> None:
    cfg = config()
    app = create_app(cfg, ClassifierService(cfg))
    client = TestClient(app)

    response = client.post(
        "/debug/classify",
        json={"messages": [{"role": "user", "content": "Rename foo to bar."}]},
    )

    assert response.status_code == 200
    assert response.json()["tier"] == "simple"
    assert response.json()["method"] == "heuristic"


def test_debug_classify_can_be_disabled() -> None:
    cfg = config(enabled=False)
    app = create_app(cfg, ClassifierService(cfg))
    client = TestClient(app)

    response = client.post(
        "/debug/classify",
        json={"messages": [{"role": "user", "content": "Rename foo to bar."}]},
    )

    assert response.status_code == 404
