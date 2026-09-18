from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from cc_enrutador.cli import main
from cc_enrutador.config import AppConfig
from cc_enrutador.doctor import CheckStatus, Doctor, DoctorReport, format_report
from cc_enrutador.models import ClassificationResult, ComplexityTier, RouteDecision


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def config(*, port: int | None = None, api_key_env: str | None = None) -> AppConfig:
    classifier_model: dict[str, Any] = {
        "provider": "litellm",
        "model": "classifier",
    }
    if api_key_env:
        classifier_model["api_key_env"] = api_key_env

    return AppConfig.model_validate(
        {
            "server": {"host": "127.0.0.1", "port": port or free_port()},
            "classifier": {"mode": "heuristic", "model": classifier_model},
            "models": {
                "simple": {"provider": "litellm", "model": "simple"},
                "medium": {"provider": "litellm", "model": "medium"},
                "complex": {
                    "provider": "anthropic_subscription",
                    "model": "complex",
                    "api_base": "https://api.anthropic.test",
                },
            },
        }
    )


class NoCallRegistry:
    def get(self, route: RouteDecision) -> Any:
        raise AssertionError("safe doctor must not call providers")

    def anthropic(self) -> Any:
        raise AssertionError("safe doctor must not call Anthropic")


class LiveProvider:
    async def complete(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> dict[str, Any]:
        if body.get("tools"):
            return {
                "type": "message",
                "content": [
                    {"type": "tool_use", "id": "toolu_1", "name": "ping", "input": {}}
                ],
            }
        return {"type": "message", "content": [{"type": "text", "text": "OK"}]}

    async def stream(
        self,
        body: Mapping[str, Any],
        headers: Mapping[str, str],
    ) -> AsyncIterator[bytes]:
        yield b"event: message_start\n\n"


class LiveRegistry:
    def __init__(self) -> None:
        self.provider = LiveProvider()

    def get(self, route: RouteDecision) -> LiveProvider:
        return self.provider

    def anthropic(self) -> LiveProvider:
        return self.provider


class LiveClassifier:
    async def classify(self, request: Mapping[str, Any]) -> ClassificationResult:
        return ClassificationResult(
            tier=ComplexityTier.MEDIUM,
            method="heuristic",
            reason="probe",
            confidence=1.0,
            latency_ms=0.1,
        )


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_safe_doctor_makes_no_provider_calls() -> None:
    report = run(Doctor(config(), providers=NoCallRegistry()).run())

    assert isinstance(report, DoctorReport)
    assert not any(check.name.startswith("live:") for check in report.checks)


def test_doctor_output_never_contains_secret_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_CLASSIFIER_KEY", "super-secret-value")
    report = run(
        Doctor(
            config(api_key_env="TEST_CLASSIFIER_KEY"),
            providers=NoCallRegistry(),
        ).run()
    )

    rendered = format_report(report) + report.model_dump_json()

    assert "TEST_CLASSIFIER_KEY" in rendered
    assert "super-secret-value" not in rendered


def test_live_doctor_runs_minimal_fake_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    report = run(
        Doctor(
            config(),
            providers=LiveRegistry(),
            classifier=LiveClassifier(),
        ).run(live=True)
    )
    statuses = {check.name: check.status for check in report.checks}

    assert statuses["live:classifier"] == CheckStatus.PASS
    assert statuses["live:simple"] == CheckStatus.PASS
    assert statuses["live:medium"] == CheckStatus.PASS
    assert statuses["live:streaming"] == CheckStatus.PASS
    assert statuses["live:tool-call"] == CheckStatus.PASS
    assert statuses["live:anthropic-subscription"] == CheckStatus.WARN


def test_doctor_report_exit_code_contract() -> None:
    passing = DoctorReport(
        checks=[
            {
                "name": "warn",
                "status": "WARN",
                "message": "warning",
                "required": False,
            }
        ]
    )
    failing = DoctorReport(
        checks=[
            {
                "name": "fail",
                "status": "FAIL",
                "message": "failure",
                "required": True,
            }
        ]
    )

    assert passing.exit_code == 0
    assert failing.exit_code == 1


def write_cli_config(path: Path, port: int) -> None:
    path.write_text(
        f"""
server:
  host: 127.0.0.1
  port: {port}
classifier:
  mode: heuristic
  model:
    provider: litellm
    model: classifier
models:
  simple:
    provider: litellm
    model: simple
  medium:
    provider: litellm
    model: medium
  complex:
    provider: anthropic_subscription
    model: complex
    api_base: https://api.anthropic.test
""",
        encoding="utf-8",
    )


def test_doctor_json_cli_is_machine_readable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "config.yaml"
    write_cli_config(path, free_port())

    code = main(["doctor", "--config", str(path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == payload["exit_code"]
    assert isinstance(payload["checks"], list)
    assert payload["live"] is False


def test_doctor_config_error_returns_exit_code_2_and_json(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("classifier: {}\n", encoding="utf-8")

    code = main(["doctor", "--config", str(path), "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert code == 2
    assert payload["error"] == "configuration"
