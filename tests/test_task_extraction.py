from __future__ import annotations

import json
from pathlib import Path

from cc_enrutador.task_extraction import (
    is_agentic,
    is_harm_monitor_request,
    is_mid_loop,
    latest_user_text,
    strip_quoted_session,
)

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict[str, object]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def test_latest_user_text_ignores_system_reminder() -> None:
    request = load_fixture("injected_context_request.json")
    assert latest_user_text(request) == "List the files in src."


def test_latest_user_text_strips_quoted_session() -> None:
    request = load_fixture("quoted_session_request.json")
    assert latest_user_text(request) == "Write a short title for this session."


def test_strip_quoted_session_is_greedy() -> None:
    text = "<session>first</session> ignored <session>second</session>\nActual task"
    assert strip_quoted_session(text) == "Actual task"


def test_tools_mark_request_agentic() -> None:
    request = load_fixture("tool_request.json")
    assert is_agentic(request) is True
    assert is_mid_loop(request) is False


def test_tool_result_marks_mid_loop_but_is_not_semantic_text() -> None:
    request = load_fixture("tool_result_request.json")
    assert is_agentic(request) is True
    assert is_mid_loop(request) is True
    assert latest_user_text(request) == ""


def test_harm_monitor_request_requires_system_and_protocol_markers() -> None:
    request = {
        "system": "You are a security monitor for autonomous AI coding agents.",
        "messages": [
            {
                "role": "user",
                "content": (
                    '<transcript>\n{"user":"delete generated files"}\n</transcript>\n'
                    "Grade HARM ONLY. Respond with <severity>N</severity> ONLY."
                ),
            }
        ],
    }

    assert is_harm_monitor_request(request) is True
    request["system"] = "You are a coding assistant."
    assert is_harm_monitor_request(request) is False
