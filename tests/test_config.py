from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from cc_enrutador.config import ConfigLoadError, ProviderModelConfig, load_config


def _write_config(path: Path, medium_base: str = "http://localhost:8000/v1") -> None:
    path.write_text(
        f"""
classifier:
  mode: hybrid
  model:
    provider: litellm
    model: local/classifier

models:
  simple:
    provider: litellm
    model: local/simple
  medium:
    provider: litellm
    model: remote/medium
    api_base: {medium_base}
  complex:
    provider: anthropic_subscription
    model: passthrough
    api_base: https://api.anthropic.com
""",
        encoding="utf-8",
    )


def test_load_minimal_valid_config(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _write_config(path)

    config = load_config(path)

    assert config.server.port == 8787
    assert config.classifier.mode == "hybrid"
    assert config.models.simple.model == "local/simple"
    assert config.models.simple.context_compression is False
    assert config.telemetry.preserve_claude_default is True


def test_context_compression_requires_openrouter_model() -> None:
    with pytest.raises(ValidationError, match="requires an openrouter/ model"):
        ProviderModelConfig(
            provider="litellm",
            model="local/simple",
            context_compression=True,
        )


def test_environment_interpolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "config.yaml"
    _write_config(path, medium_base="${TEST_MEDIUM_BASE}")
    monkeypatch.setenv("TEST_MEDIUM_BASE", "http://example.test/v1")

    config = load_config(path)

    assert config.models.medium.api_base == "http://example.test/v1"


def test_missing_environment_variable_is_actionable(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    _write_config(path, medium_base="${MISSING_TEST_BASE}")

    with pytest.raises(ConfigLoadError, match="MISSING_TEST_BASE"):
        load_config(path)


def test_invalid_config_is_actionable(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("classifier: {}\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="invalid configuration"):
        load_config(path)


def test_non_mapping_yaml_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    with pytest.raises(ConfigLoadError, match="YAML mapping"):
        load_config(path)
