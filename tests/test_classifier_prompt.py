from __future__ import annotations

from cc_enrutador.classifier import parse_classifier_output, render_classifier_prompt
from cc_enrutador.config import ClassifierConfig
from cc_enrutador.models import ComplexityTier


def test_configurable_prompt_receives_structural_fields() -> None:
    config = ClassifierConfig.model_validate(
        {
            "model": {"provider": "litellm", "model": "test/classifier"},
            "prompt": (
                "task={task};system={system};agentic={is_agentic};"
                "mid={is_mid_loop};messages={message_count};tools={tool_count}"
            ),
        }
    )
    request = {
        "system": "repo rules",
        "tools": [{"name": "read"}],
        "messages": [{"role": "user", "content": "Fix parser."}],
    }

    prompt = render_classifier_prompt(request, config)

    assert "task=Fix parser." in prompt
    assert "system=repo rules" in prompt
    assert "agentic=true" in prompt
    assert "messages=1" in prompt
    assert "tools=1" in prompt


def test_prompt_uses_task_before_trailing_tool_result() -> None:
    config = ClassifierConfig.model_validate(
        {
            "model": {"provider": "litellm", "model": "test/classifier"},
            "prompt": "Task: {task}",
        }
    )
    request = {
        "messages": [
            {"role": "user", "content": "Fix parser."},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "toolu_1", "name": "read", "input": {}}],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "toolu_1",
                        "content": "parser source",
                    }
                ],
            },
        ]
    }

    assert render_classifier_prompt(request, config) == "Task: Fix parser."


def test_configurable_output_labels_are_parsed() -> None:
    config = ClassifierConfig.model_validate(
        {
            "model": {"provider": "litellm", "model": "test/classifier"},
            "output": {
                "simple": "SIMPLE",
                "medium": "MEDIUM",
                "complex": "COMPLEX",
            },
        }
    )

    assert parse_classifier_output(" MEDIUM\n", config) == ComplexityTier.MEDIUM
