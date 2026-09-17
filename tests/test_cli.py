from __future__ import annotations

import pytest

from cc_enrutador.cli import build_parser, main


def test_parser_supports_serve() -> None:
    args = build_parser().parse_args(["serve", "--config", "config.yaml"])
    assert args.command == "serve"
    assert args.config == "config.yaml"


def test_parser_supports_doctor_flags() -> None:
    args = build_parser().parse_args(["doctor", "--live", "--json"])
    assert args.command == "doctor"
    assert args.live is True
    assert args.json is True


def test_root_help_exits_successfully() -> None:
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["--help"])
    assert exc.value.code == 0


def test_main_without_command_prints_help(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert "Task-aware model router" in capsys.readouterr().out
