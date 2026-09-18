from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence

from cc_enrutador import __version__
from cc_enrutador.app import create_app
from cc_enrutador.config import AppConfig, ConfigLoadError, load_config
from cc_enrutador.doctor import Doctor, format_report
from cc_enrutador.logging import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cc-enrutador",
        description="Task-aware model router for Claude Code.",
    )
    parser.add_argument("--version", action="version", version=__version__)

    subparsers = parser.add_subparsers(dest="command")

    serve = subparsers.add_parser("serve", help="Run the routing proxy.")
    serve.add_argument("--config", help="Path to YAML configuration.")

    doctor = subparsers.add_parser("doctor", help="Diagnose configuration and providers.")
    doctor.add_argument("--config", help="Path to YAML configuration.")
    doctor.add_argument("--live", action="store_true", help="Run minimal live provider probes.")
    doctor.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")

    return parser


def _load_or_report(config_path: str | None, *, as_json: bool = False) -> AppConfig | None:
    try:
        config = load_config(config_path)
    except ConfigLoadError as exc:
        if as_json:
            print(json.dumps({"error": "configuration", "message": str(exc)}))
        else:
            print(f"configuration error: {exc}")
        return None

    configure_logging(config.logging.level)
    return config


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "serve":
        config = _load_or_report(args.config)
        if config is None:
            return 2

        import uvicorn

        uvicorn.run(
            create_app(config),
            host=config.server.host,
            port=config.server.port,
        )
        return 0

    if args.command == "doctor":
        config = _load_or_report(args.config, as_json=args.json)
        if config is None:
            return 2

        report = asyncio.run(Doctor(config).run(live=args.live))
        if args.json:
            payload = report.model_dump(mode="json")
            payload["exit_code"] = report.exit_code
            print(json.dumps(payload, separators=(",", ":")))
        else:
            print(format_report(report))
        return report.exit_code

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
