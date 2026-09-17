from __future__ import annotations

from typing import Any

from cc_enrutador.classifier import heuristic_classify
from cc_enrutador.config import ClassifierConfig
from cc_enrutador.models import ComplexityTier


def config() -> ClassifierConfig:
    return ClassifierConfig.model_validate(
        {
            "mode": "heuristic",
            "model": {"provider": "litellm", "model": "test/classifier"},
        }
    )


def request(task: str, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"messages": [{"role": "user", "content": task}]}
    payload.update(extra)
    return payload


def test_short_mechanical_transform_is_simple() -> None:
    result = heuristic_classify(request("Rename foo to bar."), config())
    assert result.tier == ComplexityTier.SIMPLE
    assert result.explicit_gate is True


def test_ordinary_coding_defaults_medium() -> None:
    result = heuristic_classify(request("Fix the parser bug in this function."), config())
    assert result.tier == ComplexityTier.MEDIUM
    assert result.explicit_gate is False


def test_explicit_architecture_intent_is_complex() -> None:
    result = heuristic_classify(
        request("Design the authentication system architecture end-to-end."), config()
    )
    assert result.tier == ComplexityTier.COMPLEX


def test_long_horizon_refactor_is_complex() -> None:
    result = heuristic_classify(
        request("Refactor the entire repository and provide a migration plan."), config()
    )
    assert result.tier == ComplexityTier.COMPLEX


def test_code_fence_blocks_simple_gate() -> None:
    task = "Format this code:\n" + chr(96) * 3 + "python\nprint('x')\n" + chr(96) * 3
    result = heuristic_classify(request(task), config())
    assert result.tier == ComplexityTier.MEDIUM


def test_image_blocks_simple_gate() -> None:
    payload = {
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "List the visible labels."},
                    {"type": "image", "source": {"type": "base64", "data": "abc"}},
                ],
            }
        ]
    }
    result = heuristic_classify(payload, config())
    assert result.tier == ComplexityTier.MEDIUM


def test_agentic_fresh_turn_has_medium_floor() -> None:
    result = heuristic_classify(
        request(
            "Rename foo to bar.",
            tools=[{"name": "edit", "input_schema": {"type": "object"}}],
        ),
        config(),
    )
    assert result.tier == ComplexityTier.MEDIUM
    assert result.reason == "agentic:floor-medium"


def test_agentic_fresh_complex_turn_is_complex() -> None:
    result = heuristic_classify(
        request(
            "Design the new service architecture from scratch.",
            tools=[{"name": "edit", "input_schema": {"type": "object"}}],
        ),
        config(),
    )
    assert result.tier == ComplexityTier.COMPLEX


def test_mid_loop_is_medium_even_if_tool_result_contains_depth_words() -> None:
    payload = {
        "tools": [{"name": "read", "input_schema": {"type": "object"}}],
        "messages": [
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "x", "name": "read", "input": {}}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "x",
                        "content": "architect end-to-end from scratch",
                    }
                ],
            },
        ],
    }
    result = heuristic_classify(payload, config())
    assert result.tier == ComplexityTier.MEDIUM
    assert result.reason == "agentic:mid-loop"


def test_unrelated_technical_words_do_not_add_up_to_complex() -> None:
    result = heuristic_classify(
        request("Update the database API cache test and Docker config."), config()
    )
    assert result.tier == ComplexityTier.MEDIUM


def test_non_english_ordinary_request_defaults_medium() -> None:
    result = heuristic_classify(
        request("Corectează această funcție Python care dă o eroare."), config()
    )
    assert result.tier == ComplexityTier.MEDIUM
