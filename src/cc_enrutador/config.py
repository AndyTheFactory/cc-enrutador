from __future__ import annotations

import os
import re
import string
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TIERS = {"simple", "medium", "complex"}
_ALLOWED_PROMPT_FIELDS = {
    "task",
    "system",
    "is_agentic",
    "is_mid_loop",
    "message_count",
    "tool_count",
}


class ConfigLoadError(ValueError):
    """Raised when configuration cannot be loaded or validated."""


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ServerConfig(StrictModel):
    host: str = "127.0.0.1"
    port: int = Field(default=8787, ge=1, le=65535)


class ProviderModelConfig(StrictModel):
    provider: Literal["litellm", "anthropic_subscription"]
    model: str
    api_base: str | None = None
    api_key_env: str | None = None
    context_compression: bool = False

    @field_validator("model")
    @classmethod
    def non_empty_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be empty")
        return value

    @field_validator("api_key_env")
    @classmethod
    def valid_api_key_env(cls, value: str | None) -> str | None:
        if value is not None and not _ENV_NAME_PATTERN.fullmatch(value):
            raise ValueError("must be a valid environment-variable name")
        return value

    @model_validator(mode="after")
    def validate_provider_shape(self) -> ProviderModelConfig:
        if self.provider == "anthropic_subscription" and not self.api_base:
            raise ValueError("anthropic_subscription requires api_base")
        if self.context_compression and not self.model.startswith("openrouter/"):
            raise ValueError("context_compression requires an openrouter/ model")
        return self


class ClassifierOutputConfig(StrictModel):
    simple: str = "1"
    medium: str = "2"
    complex: str = "3"

    @model_validator(mode="after")
    def unique_labels(self) -> ClassifierOutputConfig:
        labels = [self.simple.strip(), self.medium.strip(), self.complex.strip()]
        if any(not label for label in labels):
            raise ValueError("classifier output labels must not be empty")
        if len(set(labels)) != 3:
            raise ValueError("classifier output labels must be unique")
        return self


class ClassifierExtractionConfig(StrictModel):
    task_head_chars: int = Field(default=700, ge=0)
    task_tail_chars: int = Field(default=300, ge=0)
    system_prefix_chars: int = Field(default=200, ge=0)


class ClassifierHeuristicConfig(StrictModel):
    simple_max_chars: int = Field(default=400, gt=0)
    system_max_chars: int = Field(default=400, ge=0)
    allow_simple_in_agentic: bool = False


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
    extraction: ClassifierExtractionConfig = Field(default_factory=ClassifierExtractionConfig)
    heuristic: ClassifierHeuristicConfig = Field(default_factory=ClassifierHeuristicConfig)

    @field_validator("model")
    @classmethod
    def classifier_uses_litellm(cls, value: ProviderModelConfig) -> ProviderModelConfig:
        if value.provider != "litellm":
            raise ValueError("classifier model provider must be litellm")
        return value

    @field_validator("prompt")
    @classmethod
    def validate_prompt(cls, value: str) -> str:
        fields: set[str] = set()
        try:
            for _, field_name, _, _ in string.Formatter().parse(value):
                if field_name:
                    fields.add(field_name)
        except ValueError as exc:
            raise ValueError(f"invalid classification prompt: {exc}") from exc

        unknown = fields - _ALLOWED_PROMPT_FIELDS
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(f"unsupported classification prompt placeholder(s): {names}")
        if "task" not in fields:
            raise ValueError("classification prompt must contain {task}")
        return value


class ModelRoutesConfig(StrictModel):
    simple: ProviderModelConfig
    medium: ProviderModelConfig
    complex: ProviderModelConfig

    @model_validator(mode="after")
    def complex_requires_anthropic_subscription(self) -> ModelRoutesConfig:
        if self.complex.provider != "anthropic_subscription":
            raise ValueError(
                "models.complex.provider must be anthropic_subscription: "
                "the complex route's Claude OAuth header is forwarded verbatim to it, "
                "and forwarding that header to a non-Anthropic provider is a credential leak"
            )
        return self


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

    @field_validator("chain")
    @classmethod
    def validate_chain(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        if set(value) != _TIERS:
            raise ValueError("escalation chain must define simple, medium, and complex")

        for source, targets in value.items():
            unknown = set(targets) - _TIERS
            if unknown:
                raise ValueError(
                    f"escalation chain for {source} has invalid target(s): "
                    + ", ".join(sorted(unknown))
                )
            if source in targets:
                raise ValueError(f"escalation chain for {source} cannot target itself")

        def visit(node: str, active: set[str], done: set[str]) -> None:
            if node in active:
                raise ValueError("escalation chain contains a cycle")
            if node in done:
                return
            active.add(node)
            for target in value[node]:
                visit(target, active, done)
            active.remove(node)
            done.add(node)

        done: set[str] = set()
        for tier in _TIERS:
            visit(tier, set(), done)
        return value


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

    @field_validator("request_ms", "stream_idle_ms")
    @classmethod
    def validate_tier_timeouts(cls, value: dict[str, int]) -> dict[str, int]:
        if set(value) != _TIERS:
            raise ValueError("tier timeout mapping must define simple, medium, and complex")
        if any(timeout <= 0 for timeout in value.values()):
            raise ValueError("tier timeouts must be positive")
        return value


class TelemetryConfig(StrictModel):
    enabled: bool = True
    persist_prompts: bool = False
    preserve_claude_default: Literal[True] = True

    @field_validator("persist_prompts")
    @classmethod
    def reject_prompt_persistence_in_v1(cls, value: bool) -> bool:
        if value:
            raise ValueError("telemetry.persist_prompts=true is not supported in V1")
        return value


class DoctorConfig(StrictModel):
    live_probes: bool = False
    probe_timeout_ms: int = Field(default=10_000, gt=0)
    check_streaming: bool = True
    check_tool_calls: bool = True


class DebugConfig(StrictModel):
    classification_endpoint: bool = True
    capture_bodies: bool = False

    @field_validator("capture_bodies")
    @classmethod
    def reject_body_capture_in_v1(cls, value: bool) -> bool:
        if value:
            raise ValueError("debug.capture_bodies=true is not supported in V1")
        return value


class LoggingConfig(StrictModel):
    level: Literal["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"] = "INFO"


class AppConfig(StrictModel):
    @model_validator(mode="before")
    @classmethod
    def synchronize_classifier_timeout(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value

        data = dict(value)
        classifier_raw = data.get("classifier")
        timeouts_raw = data.get("timeouts")
        classifier = dict(classifier_raw) if isinstance(classifier_raw, dict) else {}
        timeouts = dict(timeouts_raw) if isinstance(timeouts_raw, dict) else {}

        has_classifier = "timeout_ms" in classifier
        has_global = "classifier_ms" in timeouts

        if has_classifier and has_global:
            if classifier["timeout_ms"] != timeouts["classifier_ms"]:
                raise ValueError(
                    "classifier.timeout_ms and timeouts.classifier_ms must match in V1"
                )
        elif has_classifier:
            timeouts["classifier_ms"] = classifier["timeout_ms"]
            data["timeouts"] = timeouts
        elif has_global and classifier:
            classifier["timeout_ms"] = timeouts["classifier_ms"]
            data["classifier"] = classifier

        return data

    server: ServerConfig = Field(default_factory=ServerConfig)
    classifier: ClassifierConfig
    models: ModelRoutesConfig
    escalation: EscalationConfig = Field(default_factory=EscalationConfig)
    timeouts: TimeoutsConfig = Field(default_factory=TimeoutsConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    doctor: DoctorConfig = Field(default_factory=DoctorConfig)
    debug: DebugConfig = Field(default_factory=DebugConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    @model_validator(mode="after")
    def classifier_timeout_matches_global_timeout(self) -> AppConfig:
        if self.classifier.timeout_ms != self.timeouts.classifier_ms:
            raise ValueError("classifier.timeout_ms and timeouts.classifier_ms must match in V1")
        return self


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
        "no configuration file found; pass --config, set CC_ENRUTADOR_CONFIG, or create config.yaml"
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
