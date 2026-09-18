from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

_SESSION_RE = re.compile(r"<session>.*</session>", re.IGNORECASE | re.DOTALL)


def is_injected_context(block: object) -> bool:
    if not isinstance(block, Mapping):
        return False
    if block.get("type") != "text":
        return False
    text = block.get("text")
    if not isinstance(text, str):
        return False
    stripped = text.strip()
    return stripped.startswith("<system-reminder>") and stripped.endswith("</system-reminder>")


def strip_quoted_session(text: str) -> str:
    return _SESSION_RE.sub("", text).strip()


def _text_from_content(content: object, *, include_tool_results: bool = False) -> str:
    if isinstance(content, str):
        return strip_quoted_session(content)
    if not isinstance(content, list):
        return ""

    parts: list[str] = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        if is_injected_context(block):
            continue

        block_type = block.get("type")
        if block_type == "text":
            text = block.get("text")
            if isinstance(text, str):
                cleaned = strip_quoted_session(text)
                if cleaned:
                    parts.append(cleaned)
        elif include_tool_results and block_type == "tool_result":
            result = block.get("content")
            if isinstance(result, str):
                parts.append(result)
    return "\n".join(parts).strip()


def latest_user_text(request: Mapping[str, Any]) -> str:
    messages = request.get("messages")
    if not isinstance(messages, list):
        return ""

    for message in reversed(messages):
        if not isinstance(message, Mapping) or message.get("role") != "user":
            continue
        return _text_from_content(message.get("content"))
    return ""


def current_task_text(request: Mapping[str, Any]) -> str:
    """Return the latest semantic user instruction, skipping tool-result-only turns."""
    messages = request.get("messages")
    if not isinstance(messages, list):
        return ""

    for message in reversed(messages):
        if not isinstance(message, Mapping) or message.get("role") != "user":
            continue
        text = _text_from_content(message.get("content"))
        if text:
            return text
    return ""


def system_text(request: Mapping[str, Any]) -> str:
    system = request.get("system")
    if isinstance(system, str):
        return system
    if not isinstance(system, list):
        return ""

    parts: list[str] = []
    for block in system:
        if not isinstance(block, Mapping) or is_injected_context(block):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(str(block["text"]))
    return "\n".join(parts).strip()


def is_harm_monitor_request(request: Mapping[str, Any]) -> bool:
    """Identify Claude Code's transcript-based autonomous-agent harm check."""
    system = system_text(request).lower()
    task = latest_user_text(request).lower()
    return (
        "security monitor for autonomous ai coding agents" in system
        and task.lstrip().startswith("<transcript>")
        and "</transcript>" in task
        and "<severity>n</severity>" in task
        and "grade harm only" in task
    )


def message_count(request: Mapping[str, Any]) -> int:
    messages = request.get("messages")
    return len(messages) if isinstance(messages, list) else 0


def user_message_count(request: Mapping[str, Any]) -> int:
    messages = request.get("messages")
    if not isinstance(messages, list):
        return 0
    return sum(
        1 for message in messages if isinstance(message, Mapping) and message.get("role") == "user"
    )


def tool_count(request: Mapping[str, Any]) -> int:
    tools = request.get("tools")
    return len(tools) if isinstance(tools, list) else 0


def has_images(request: Mapping[str, Any]) -> bool:
    messages = request.get("messages")
    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, Mapping) and block.get("type") in {"image", "image_url"}:
                return True
    return False


def _has_tool_block(request: Mapping[str, Any], block_type: str) -> bool:
    messages = request.get("messages")
    if not isinstance(messages, list):
        return False
    for message in messages:
        if not isinstance(message, Mapping):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        if any(isinstance(block, Mapping) and block.get("type") == block_type for block in content):
            return True
    return False


def is_agentic(request: Mapping[str, Any]) -> bool:
    return (
        tool_count(request) > 0
        or _has_tool_block(request, "tool_use")
        or _has_tool_block(request, "tool_result")
    )


def is_mid_loop(request: Mapping[str, Any]) -> bool:
    messages = request.get("messages")
    if not isinstance(messages, list):
        return False

    for message in reversed(messages):
        if not isinstance(message, Mapping) or message.get("role") != "user":
            continue
        content = message.get("content")
        if not isinstance(content, list):
            return False
        return any(
            isinstance(block, Mapping) and block.get("type") == "tool_result" for block in content
        )
    return False
