from __future__ import annotations

import json
from pathlib import Path

FIXTURE_DIR = Path(__file__).parent / "fixtures"


def test_json_fixtures_are_valid_and_sanitized() -> None:
    fixture_paths = sorted(FIXTURE_DIR.glob("*.json"))
    assert fixture_paths

    serialized = ""
    for path in fixture_paths:
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert isinstance(payload, dict)
        serialized += json.dumps(payload).lower()

    forbidden = ["sk-ant-", "bearer eyj", "andrei@"]
    assert all(item not in serialized for item in forbidden)
