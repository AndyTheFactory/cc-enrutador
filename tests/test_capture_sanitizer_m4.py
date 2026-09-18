from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any


def load_sanitizer() -> ModuleType:
    path = Path("scripts/sanitize_capture.py")
    spec = importlib.util.spec_from_file_location("sanitize_capture", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_capture_sanitizer_redacts_credentials_ids_and_home_paths() -> None:
    module = load_sanitizer()
    payload: dict[str, Any] = {
        "headers": {
            "Authorization": "Bearer secret-oauth",
            "x-api-key": "secret-api-key",
            "x-request-id": "safe-request-id",
        },
        "metadata": {
            "session_id": "session-123",
            "nested": "Bearer another-secret",
        },
        "paths": [
            "/home/andrei/project/file.py",
            r"C:\Users\Andrei\project\file.py",
        ],
    }

    sanitized = module.sanitize(payload)
    serialized = repr(sanitized)

    assert "secret-oauth" not in serialized
    assert "secret-api-key" not in serialized
    assert "session-123" not in serialized
    assert "another-secret" not in serialized
    assert "/home/andrei/" not in serialized
    assert "Andrei" not in serialized
    assert "safe-request-id" in serialized
