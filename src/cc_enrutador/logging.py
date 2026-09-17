from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

_SENSITIVE_KEY = re.compile(
    r"(authorization|api[-_]?key|token|secret|password|cookie)",
    re.IGNORECASE,
)

_BEARER = re.compile(r"\b(Bearer\s+)[A-Za-z0-9._~+/=-]+", re.IGNORECASE)
_API_KEY_INLINE = re.compile(
    r"\b(api[-_]?key|token|secret|password)\s*[=:]\s*([^\s,;]+)",
    re.IGNORECASE,
)


def redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: ("[REDACTED]" if _SENSITIVE_KEY.search(str(key)) else redact_value(item))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, str):
        value = _BEARER.sub(r"\1[REDACTED]", value)
        return _API_KEY_INLINE.sub(lambda m: f"{m.group(1)}=[REDACTED]", value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_value(record.msg)
        if record.args:
            record.args = redact_value(record.args)
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.addFilter(RedactingFilter())
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
