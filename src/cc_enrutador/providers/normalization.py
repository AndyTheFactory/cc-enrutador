from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from typing import Any


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "model_dump"):
        dumped = value.model_dump()
        if isinstance(dumped, dict):
            return dumped
    if hasattr(value, "dict"):
        dumped = value.dict()
        if isinstance(dumped, dict):
            return dumped
    raise ValueError("provider response is not dict-like")


def _content_to_openai(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return content

    parts: list[dict[str, Any]] = []
    for block in content:
        if not isinstance(block, Mapping):
            continue
        block_type = block.get("type")
        if block_type == "text":
            parts.append({"type": "text", "text": block.get("text", "")})
        elif block_type == "image":
            source = block.get("source")
            if isinstance(source, Mapping) and source.get("type") == "base64":
                media_type = source.get("media_type", "image/png")
                data = source.get("data", "")
                parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{media_type};base64,{data}"},
                    }
                )
        elif block_type == "tool_result":
            content_value = block.get("content", "")
            if isinstance(content_value, str):
                parts.append({"type": "text", "text": content_value})
    return parts or ""


def _tools_to_openai(tools: Any) -> list[dict[str, Any]] | None:
    if not isinstance(tools, list):
        return None
    converted: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, Mapping):
            continue
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": tool.get("name"),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {"type": "object"}),
                },
            }
        )
    return converted or None


def anthropic_request_to_litellm(body: Mapping[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system = body.get("system")
    if isinstance(system, str) and system:
        messages.append({"role": "system", "content": system})

    raw_messages = body.get("messages")
    if isinstance(raw_messages, list):
        for message in raw_messages:
            if not isinstance(message, Mapping):
                continue
            role = message.get("role")
            content = message.get("content")
            if role == "user" and isinstance(content, list):
                tool_results = [
                    block
                    for block in content
                    if isinstance(block, Mapping) and block.get("type") == "tool_result"
                ]
                if tool_results:
                    for block in tool_results:
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": block.get("tool_use_id"),
                                "content": block.get("content", ""),
                            }
                        )
                    remaining = [
                        block
                        for block in content
                        if not (isinstance(block, Mapping) and block.get("type") == "tool_result")
                    ]
                    if remaining:
                        messages.append({"role": "user", "content": _content_to_openai(remaining)})
                    continue
            messages.append({"role": role, "content": _content_to_openai(content)})

    result: dict[str, Any] = {"messages": messages}
    tools = _tools_to_openai(body.get("tools"))
    if tools:
        result["tools"] = tools

    for source, target in (
        ("max_tokens", "max_tokens"),
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("stop_sequences", "stop"),
    ):
        if source in body:
            result[target] = body[source]
    return result


def litellm_response_to_anthropic(response: Any, model: str) -> dict[str, Any]:
    data = _as_dict(response)
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValueError("LiteLLM response has no choices")
    first = choices[0]
    if not isinstance(first, Mapping):
        raise ValueError("LiteLLM choice is invalid")
    message = first.get("message")
    message_data = _as_dict(message)

    content_blocks: list[dict[str, Any]] = []
    content = message_data.get("content")
    if isinstance(content, str) and content:
        content_blocks.append({"type": "text", "text": content})

    tool_calls = message_data.get("tool_calls")
    if isinstance(tool_calls, list):
        for call in tool_calls:
            call_data = _as_dict(call)
            function = _as_dict(call_data.get("function"))
            arguments = function.get("arguments", "{}")
            if isinstance(arguments, str):
                try:
                    parsed_arguments = json.loads(arguments)
                except json.JSONDecodeError:
                    parsed_arguments = {"raw": arguments}
            elif isinstance(arguments, dict):
                parsed_arguments = arguments
            else:
                parsed_arguments = {}
            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": call_data.get("id") or f"toolu_{uuid.uuid4().hex[:16]}",
                    "name": function.get("name", ""),
                    "input": parsed_arguments,
                }
            )

    usage = data.get("usage")
    usage_data = _as_dict(usage) if usage is not None else {}
    finish_reason = first.get("finish_reason")
    stop_reason = "tool_use" if tool_calls else _map_stop_reason(finish_reason)

    return {
        "id": data.get("id") or f"msg_{uuid.uuid4().hex}",
        "type": "message",
        "role": "assistant",
        "model": data.get("model") or model,
        "content": content_blocks,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {
            "input_tokens": usage_data.get("prompt_tokens", 0),
            "output_tokens": usage_data.get("completion_tokens", 0),
        },
    }


def _map_stop_reason(reason: Any) -> str | None:
    if reason in {"stop", "stop_sequence"}:
        return "end_turn"
    if reason in {"length", "max_tokens"}:
        return "max_tokens"
    return None


def _sse(event: str, payload: dict[str, Any]) -> bytes:
    encoded = json.dumps(payload, separators=(",", ":"))
    return f"event: {event}\ndata: {encoded}\n\n".encode()


def litellm_chunk_to_anthropic_sse(
    chunk: Any,
    *,
    model: str,
    include_start: bool,
) -> list[bytes]:
    data = _as_dict(chunk)
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return []
    first = choices[0]
    if not isinstance(first, Mapping):
        return []
    delta = first.get("delta")
    delta_data = _as_dict(delta) if delta is not None else {}

    events: list[bytes] = []
    if include_start:
        events.append(
            _sse(
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": data.get("id") or f"msg_{uuid.uuid4().hex}",
                        "type": "message",
                        "role": "assistant",
                        "model": data.get("model") or model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 0, "output_tokens": 0},
                    },
                },
            )
        )

    text = delta_data.get("content")
    if isinstance(text, str) and text:
        events.append(
            _sse(
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": text},
                },
            )
        )

    finish_reason = first.get("finish_reason")
    if finish_reason is not None:
        events.append(
            _sse(
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": _map_stop_reason(finish_reason), "stop_sequence": None},
                    "usage": {"output_tokens": 0},
                },
            )
        )
        events.append(_sse("message_stop", {"type": "message_stop"}))
    return events
