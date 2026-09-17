from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigLoadError(ValueError):
    """Raised when configuration cannot be loaded or validated."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerConfig(StrictModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8787, ge=1, le=65535)


class ProviderModelConfig(StrictModel):
    provider: str
    model: str
    api_base: str | None = None
    api_key_env: str | None = None

    @field_validator("provider", "model")
    @classmethod
    def non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value


class ClassifierOutputConfig(StrictModel):
    simple: str = "1"
    medium: str = "2"
    complex: str = "3"


_DEFAULT_PROMPT = """Classify the task complexity.

Return ONLY one digit:
1 = simple, short, mechanical, self-contained
2 = normal coding/reasoning task
3 = architecture, broad, ambiguous, or long-horizon task

Task:
{task}
"""


class ClassifierConfig(StrictModel):
    mode: Literal["heuristic", "ai", "hybrid"] = "hybrid"
    model: ProviderModelConfig
    prompt: str = _DEFAULT_PROMPT
    output: ClassifierOutputConfig = Field(default_factory=ClassifierOutputConfig)
    timeout_ms: int = Field(default=1500, gt=0)
    max_output_tokens: int = Field(default=4, gt=0)
    temperature: float = Field(default=0.0, ge=0.0)
    cache_size: int = Field(default=500, ge=0)


class ModelRoutesConfig(StrictModel):
    simple: ProviderModelConfig
    medium: ProviderModelConfig
    complex: ProviderModelConfig


class ProviderFailureEscalationConfig(StrictModel):
    simple_to_medium: bool = True
    medium_to_complex: bool = True


class SemanticEscalationConfig(StrictModel):
    enabled: bool = False
    max_attempts_per_level: int = Field(default=1, ge=1)


class EscalationConfig(StrictModel):
    enabled: bool = True
    provider_failure: ProviderFailureEscalationConfig = Field(
        default_factory=ProviderFailureEscalationConfig
    )
    semantic: SemanticEscalationConfig = Field(default_factory=SemanticEscalationConfig)
    never_demote_within_task: bool = True
    chain: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "simple": ["medium", "complex"],
            "medium": ["complex"],
            "complex": [],
        }
    )


class TimeoutsConfig(StrictModel):
    classifier_ms: int = Field(default=1500, gt=0)
    connect_ms: int = Field(default=5000, gt=0)
    request_ms: dict[str, int] = Field(
        default_factory=lambda: {
            "simple": 120_000,
            "medium": 300_000,
            "complex": 600_000,
        }
    )
    stream_idle_ms: dict[str, int] = Field(
        default_factory=lambda: {
            "simple": 60_000,
            "medium": 120_000,
            "complex": 120_000,
        }
    )


class TelemetryConfig(StrictModel):
    enabled: bool = True
    persist_prompts: bool = False
    preserve_claude_default: bool = True


class DoctorConfig(StrictModel):
    live_probes: bool = False
    probe_timeout_ms: int = Field(default=10_000, gt=0)
    check_streaming: bool = True
    check_tool_calls: bool = True


class LoggingConfig(StrictModel):
    level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"


class AppConfig(StrictModel):
    server: ServerConfig = Field(default_factory=ServerConfig)
    classifier: ClassifierConfig
    models: ModelRoutesConfig
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    doctor: DoctorConfig = Field(default_factory=DoctorConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)


def _expand_env(value: object) -> object:
    if isinstance(value, dict):
        return {key: _expand_env(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_expand_env(item) for item in value]
    if not isinstance(value, str):
        return value

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name not in os.environ:
            raise ConfigLoadError(f"environment variable {name!r} is required but not set")
        return os.environ[name]

    return _ENV_PATTERN.sub(replace, value)


def resolve_config_path(path: str | Path | None = None) -> Path:
    if path is not None:
        return Path(path)

    env_path = os.getenv("CC_ENRUTADOR_CONFIG")
    if env_path:
        return Path(env_path)

    for candidate in (Path("config.yaml"), Path("config.yml"), Path("config.example.yaml")):
        if candidate.exists():
            return candidate

    raise ConfigLoadError(
        "no configuration file found; pass --config, set CC_ENRUTADOR_CONFIG, "
        "or create config.yaml"
    )


def load_config(path: str | Path | None = None) -> AppConfig:
    config_path = resolve_config_path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigLoadError(f"configuration file not found: {config_path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigLoadError(f"invalid YAML in {config_path}: {exc}") from exc

    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ConfigLoadError("configuration root must be a YAML mapping")

    expanded = _expand_env(raw)
    try:
        return AppConfig.model_validate(expanded)
    except ValidationError as exc:
        raise ConfigLoadError(f"invalid configuration:\n{exc}") from exc
