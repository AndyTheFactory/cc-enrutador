from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

_SENSITIVE_KEY = re.compile(
    r"(authorization|x-api-key|api[_-]?key|token|secret|cookie|session[_-]?id|user[_-]?id)",
    re.IGNORECASE,
)
_BEARER = re.compile(r"Bearer\s+[^\s\"']+", re.IGNORECASE)
_UNIX_HOME = re.compile(r"/(?:home|Users)/[^/\s]+/")
_WINDOWS_HOME = re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+\\")


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _SENSITIVE_KEY.search(str(key)):
                result[str(key)] = "<redacted>"
            else:
                result[str(key)] = sanitize(item)
        return result
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        value = _BEARER.sub("Bearer <redacted>", value)
        value = _UNIX_HOME.sub("/<home>/", value)
        value = _WINDOWS_HOME.sub(r"<home>\\", value)
        return value
    return value


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sanitize a JSON Claude Code compatibility capture before manual review."
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    raw = json.loads(args.input.read_text(encoding="utf-8"))
    sanitized = sanitize(raw)
    args.output.write_text(
        json.dumps(sanitized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
