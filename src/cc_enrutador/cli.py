from __future__ import annotations

import argparse
from collections.abc import Sequence

from cc_enrutador import __version__
from cc_enrutador.app import create_app
from cc_enrutador.config import ConfigLoadError, load_config
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
    doctor.add_argument("--live", action="store_true", help="Reserved for live probes.")
    doctor.add_argument("--json", action="store_true", help="Reserved for JSON diagnostics.")

    return parser


def _load_or_report(config_path: str | None) -> int:
    try:
        config = load_config(config_path)
    except ConfigLoadError as exc:
        print(f"configuration error: {exc}")
        return 2

    configure_logging(config.logging.level)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "serve":
        try:
            config = load_config(args.config)
        except ConfigLoadError as exc:
            print(f"configuration error: {exc}")
            return 2
        configure_logging(config.logging.level)

        import uvicorn

        uvicorn.run(
            create_app(config),
            host=config.server.host,
            port=config.server.port,
        )
        return 0

    if args.command == "doctor":
        status = _load_or_report(args.config)
        if status:
            return status
        print("doctor command is reserved for M3 diagnostics implementation")
        return 0

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
