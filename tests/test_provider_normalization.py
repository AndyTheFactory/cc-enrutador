from __future__ import annotations

import json

from cc_enrutador.providers.normalization import (
    LiteLLMStreamNormalizer,
    anthropic_request_to_litellm,
    litellm_response_to_anthropic,
)


def test_anthropic_tools_and_tool_results_translate_to_litellm() -> None:
    body = {
        "system": "Work carefully.",
        "tools": [
            {
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            }
        ],
        "messages": [
            {"role": "user", "content": "Read config.yaml"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "read_file",
                        "input": {"path": "config.yaml"},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "server:\n  port: 8787",
                    }
                ],
            },
        ],
    }

    converted = anthropic_request_to_litellm(body)

    assert converted["messages"][0] == {"role": "system", "content": "Work carefully."}
    assistant = converted["messages"][2]
    assert assistant["tool_calls"][0]["function"]["name"] == "read_file"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {
        "path": "config.yaml"
    }
    assert converted["messages"][3] == {
        "role": "tool",
        "tool_call_id": "toolu_1",
        "content": "server:\n  port: 8787",
    }
    assert converted["tools"][0]["function"]["parameters"]["type"] == "object"


def test_litellm_tool_call_normalizes_to_anthropic_tool_use() -> None:
    response = {
        "id": "chatcmpl_1",
        "model": "test/model",
        "choices": [
            {
                "message": {
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "function": {
                                "name": "read_file",
                                "arguments": '{"path":"config.yaml"}',
                            },
                        }
                    ],
                },
                "finish_reason": "tool_calls",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 4},
    }

    normalized = litellm_response_to_anthropic(response, "test/model")

    assert normalized["stop_reason"] == "tool_use"
    assert normalized["content"] == [
        {
            "type": "tool_use",
            "id": "call_1",
            "name": "read_file",
            "input": {"path": "config.yaml"},
        }
    ]
    assert normalized["usage"] == {"input_tokens": 10, "output_tokens": 4}


def test_stream_normalizer_emits_text_event_order() -> None:
    normalizer = LiteLLMStreamNormalizer("test/model")

    first = normalizer.feed(
        {
            "id": "stream_1",
            "choices": [{"delta": {"content": "hel"}, "finish_reason": None}],
        }
    )
    final = normalizer.feed(
        {
            "id": "stream_1",
            "choices": [{"delta": {"content": "lo"}, "finish_reason": "stop"}],
        }
    )
    text = b"".join(first + final).decode()

    assert text.index("event: message_start") < text.index("event: content_block_start")
    assert '"text":"hel"' in text
    assert '"text":"lo"' in text
    assert text.index("event: message_delta") < text.index("event: message_stop")


def test_stream_normalizer_emits_tool_json_delta() -> None:
    normalizer = LiteLLMStreamNormalizer("test/model")
    events = normalizer.feed(
        {
            "id": "stream_2",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_1",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":',
                                },
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        }
    )
    events += normalizer.feed(
        {
            "id": "stream_2",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": '"config.yaml"}'},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
    )
    text = b"".join(events).decode()

    assert '"type":"tool_use"' in text
    assert '"type":"input_json_delta"' in text
    assert '"stop_reason":"tool_use"' in text
