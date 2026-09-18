from __future__ import annotations

import asyncio
import importlib.util
import os
import socket
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from cc_enrutador.classifier import ClassifierService
from cc_enrutador.config import AppConfig, ProviderModelConfig
from cc_enrutador.execution import ProviderRegistry
from cc_enrutador.models import ComplexityTier
from cc_enrutador.operations import route_for_tier
from cc_enrutador.providers.base import ProviderError
from cc_enrutador.timeouts import TimeoutPolicy


class CheckStatus(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


class DoctorCheck(BaseModel):
    name: str
    status: CheckStatus
    message: str
    required: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class DoctorReport(BaseModel):
    checks: list[DoctorCheck]
    live: bool = False

    @property
    def exit_code(self) -> int:
        return (
            1
            if any(check.status is CheckStatus.FAIL and check.required for check in self.checks)
            else 0
        )


class Doctor:
    def __init__(
        self,
        config: AppConfig,
        providers: ProviderRegistry | None = None,
        classifier: ClassifierService | None = None,
    ) -> None:
        self.config = config
        self.providers = providers or ProviderRegistry(config)
        self.classifier = classifier or ClassifierService(config)
        self.timeouts = TimeoutPolicy(config.timeouts)

    async def run(self, *, live: bool = False) -> DoctorReport:
        checks = self._safe_checks()
        if live:
            checks.extend(await self._live_checks())
        return DoctorReport(checks=checks, live=live)

    def _safe_checks(self) -> list[DoctorCheck]:
        checks = [
            DoctorCheck(
                name="configuration",
                status=CheckStatus.PASS,
                message="configuration parsed and validated",
            ),
            self._classifier_check(),
            *self._route_checks(),
            self._escalation_check(),
            self._litellm_check(),
            self._bind_port_check(),
            self._telemetry_check(),
            self._timeout_check(),
        ]
        checks.extend(self._secret_checks())
        return checks

    def _classifier_check(self) -> DoctorCheck:
        return DoctorCheck(
            name="classifier",
            status=CheckStatus.PASS,
            message=f"classifier mode={self.config.classifier.mode}",
            metadata={
                "model": self.config.classifier.model.model,
                "timeout_ms": self.config.classifier.timeout_ms,
                "cache_size": self.config.classifier.cache_size,
            },
        )

    def _route_checks(self) -> list[DoctorCheck]:
        checks: list[DoctorCheck] = []
        for tier in ComplexityTier:
            model = self._model_for_tier(tier)
            endpoint_status, endpoint_message = self._endpoint_status(model)
            checks.append(
                DoctorCheck(
                    name=f"route:{tier.value}",
                    status=endpoint_status,
                    message=endpoint_message,
                    metadata={
                        "provider": model.provider,
                        "model": model.model,
                        "api_base": model.api_base,
                    },
                )
            )
        return checks

    @staticmethod
    def _endpoint_status(model: ProviderModelConfig) -> tuple[CheckStatus, str]:
        if model.api_base is None:
            return CheckStatus.PASS, "provider uses its configured/default endpoint"
        parsed = urlparse(model.api_base)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return CheckStatus.FAIL, "api_base must be an absolute http(s) URL"
        return CheckStatus.PASS, "endpoint syntax is valid"

    def _model_for_tier(self, tier: ComplexityTier) -> ProviderModelConfig:
        if tier is ComplexityTier.SIMPLE:
            return self.config.models.simple
        if tier is ComplexityTier.MEDIUM:
            return self.config.models.medium
        return self.config.models.complex

    def _secret_checks(self) -> list[DoctorCheck]:
        checks: list[DoctorCheck] = []
        configs = [
            ("classifier", self.config.classifier.model),
            ("simple", self.config.models.simple),
            ("medium", self.config.models.medium),
            ("complex", self.config.models.complex),
        ]
        for name, model in configs:
            if not model.api_key_env:
                continue
            present = bool(os.getenv(model.api_key_env))
            checks.append(
                DoctorCheck(
                    name=f"secret:{name}",
                    status=CheckStatus.PASS if present else CheckStatus.FAIL,
                    message=(
                        f"environment variable {model.api_key_env} is present"
                        if present
                        else f"environment variable {model.api_key_env} is missing or empty"
                    ),
                    metadata={"env": model.api_key_env},
                )
            )
        return checks

    def _escalation_check(self) -> DoctorCheck:
        return DoctorCheck(
            name="escalation",
            status=CheckStatus.PASS,
            message="escalation chain is valid",
            metadata={"chain": self.config.escalation.chain},
        )

    @staticmethod
    def _litellm_check() -> DoctorCheck:
        available = importlib.util.find_spec("litellm") is not None
        return DoctorCheck(
            name="litellm",
            status=CheckStatus.PASS if available else CheckStatus.FAIL,
            message="LiteLLM is importable" if available else "LiteLLM is not installed",
        )

    def _bind_port_check(self) -> DoctorCheck:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((self.config.server.host, self.config.server.port))
        except OSError as exc:
            return DoctorCheck(
                name="bind-port",
                status=CheckStatus.FAIL,
                message=f"cannot bind {self.config.server.host}:{self.config.server.port}: {exc}",
            )
        finally:
            sock.close()
        return DoctorCheck(
            name="bind-port",
            status=CheckStatus.PASS,
            message=f"{self.config.server.host}:{self.config.server.port} is available",
        )

    def _telemetry_check(self) -> DoctorCheck:
        return DoctorCheck(
            name="telemetry",
            status=CheckStatus.PASS,
            message=(
                "router telemetry enabled"
                if self.config.telemetry.enabled
                else "router telemetry disabled; Claude telemetry policy remains independent"
            ),
            metadata={
                "enabled": self.config.telemetry.enabled,
                "persist_prompts": self.config.telemetry.persist_prompts,
                "preserve_claude_default": self.config.telemetry.preserve_claude_default,
            },
        )

    def _timeout_check(self) -> DoctorCheck:
        return DoctorCheck(
            name="timeouts",
            status=CheckStatus.PASS,
            message="effective timeouts are valid",
            metadata={
                "classifier_ms": self.config.classifier.timeout_ms,
                "connect_ms": self.config.timeouts.connect_ms,
                "request_ms": self.config.timeouts.request_ms,
                "stream_idle_ms": self.config.timeouts.stream_idle_ms,
            },
        )

    async def _live_checks(self) -> list[DoctorCheck]:
        checks = [await self._live_classifier()]
        checks.extend(
            [
                await self._live_completion(ComplexityTier.SIMPLE),
                await self._live_completion(ComplexityTier.MEDIUM),
            ]
        )
        if self.config.doctor.check_streaming:
            checks.append(await self._live_stream())
        if self.config.doctor.check_tool_calls:
            checks.append(await self._live_tool_call())
        checks.append(await self._live_anthropic())
        return checks

    async def _live_classifier(self) -> DoctorCheck:
        try:
            result = await asyncio.wait_for(
                self.classifier.classify(
                    {"messages": [{"role": "user", "content": "Explain briefly."}]}
                ),
                timeout=self.config.doctor.probe_timeout_ms / 1000,
            )
        except Exception as exc:
            return DoctorCheck(
                name="live:classifier",
                status=CheckStatus.FAIL,
                message=f"classifier probe failed: {type(exc).__name__}",
            )
        return DoctorCheck(
            name="live:classifier",
            status=CheckStatus.PASS,
            message=f"classifier returned {result.tier.value}",
            metadata={"method": result.method},
        )

    async def _live_completion(self, tier: ComplexityTier) -> DoctorCheck:
        route = route_for_tier(tier, self.config)
        provider = self.providers.get(route)
        try:
            response = await asyncio.wait_for(
                provider.complete(
                    {
                        "messages": [{"role": "user", "content": "Reply OK."}],
                        "max_tokens": 2,
                    },
                    {},
                ),
                timeout=self.config.doctor.probe_timeout_ms / 1000,
            )
        except Exception as exc:
            return DoctorCheck(
                name=f"live:{tier.value}",
                status=CheckStatus.FAIL,
                message=f"{tier.value} completion probe failed: {type(exc).__name__}",
            )
        return DoctorCheck(
            name=f"live:{tier.value}",
            status=CheckStatus.PASS,
            message=f"{tier.value} completion probe succeeded",
            metadata={"response_type": response.get("type", "unknown")},
        )

    async def _live_stream(self) -> DoctorCheck:
        route = route_for_tier(ComplexityTier.SIMPLE, self.config)
        provider = self.providers.get(route)
        try:
            stream = provider.stream(
                {
                    "messages": [{"role": "user", "content": "Reply OK."}],
                    "max_tokens": 2,
                    "stream": True,
                },
                {},
            )
            first = await asyncio.wait_for(
                anext(stream),
                timeout=self.config.doctor.probe_timeout_ms / 1000,
            )
            await stream.aclose()
            if not first:
                raise ProviderError("empty streaming event")
        except Exception as exc:
            return DoctorCheck(
                name="live:streaming",
                status=CheckStatus.FAIL,
                message=f"streaming probe failed: {type(exc).__name__}",
            )
        return DoctorCheck(
            name="live:streaming",
            status=CheckStatus.PASS,
            message="streaming probe produced an event",
        )

    async def _live_tool_call(self) -> DoctorCheck:
        route = route_for_tier(ComplexityTier.SIMPLE, self.config)
        provider = self.providers.get(route)
        try:
            response = await asyncio.wait_for(
                provider.complete(
                    {
                        "messages": [{"role": "user", "content": "Call the ping tool."}],
                        "max_tokens": 8,
                        "tools": [
                            {
                                "name": "ping",
                                "description": "Return pong",
                                "input_schema": {"type": "object", "properties": {}},
                            }
                        ],
                    },
                    {},
                ),
                timeout=self.config.doctor.probe_timeout_ms / 1000,
            )
            content = response.get("content")
            has_tool = isinstance(content, list) and any(
                isinstance(block, dict) and block.get("type") == "tool_use" for block in content
            )
            if not has_tool:
                raise ProviderError("provider did not return tool_use")
        except Exception as exc:
            return DoctorCheck(
                name="live:tool-call",
                status=CheckStatus.FAIL,
                message=f"tool-call probe failed: {type(exc).__name__}",
            )
        return DoctorCheck(
            name="live:tool-call",
            status=CheckStatus.PASS,
            message="tool-call probe returned tool_use",
        )

    async def _live_anthropic(self) -> DoctorCheck:
        token = os.getenv("CLAUDE_CODE_OAUTH_TOKEN") or os.getenv("ANTHROPIC_AUTH_TOKEN")
        if not token:
            return DoctorCheck(
                name="live:anthropic-subscription",
                status=CheckStatus.WARN,
                required=False,
                message=(
                    "subscription auth probe skipped; set CLAUDE_CODE_OAUTH_TOKEN or "
                    "ANTHROPIC_AUTH_TOKEN to probe from the doctor CLI"
                ),
            )

        provider = self.providers.anthropic()
        try:
            await asyncio.wait_for(
                provider.complete(
                    {
                        "messages": [{"role": "user", "content": "Reply OK."}],
                        "max_tokens": 2,
                    },
                    {"authorization": f"Bearer {token}"},
                ),
                timeout=self.config.doctor.probe_timeout_ms / 1000,
            )
        except Exception as exc:
            return DoctorCheck(
                name="live:anthropic-subscription",
                status=CheckStatus.FAIL,
                message=f"Anthropic subscription probe failed: {type(exc).__name__}",
            )
        return DoctorCheck(
            name="live:anthropic-subscription",
            status=CheckStatus.PASS,
            message="Anthropic subscription probe succeeded",
        )


def format_report(report: DoctorReport) -> str:
    lines = []
    for check in report.checks:
        lines.append(f"{check.status.value:4}  {check.name}: {check.message}")
    return "\n".join(lines)
