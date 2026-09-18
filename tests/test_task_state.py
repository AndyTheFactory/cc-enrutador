from __future__ import annotations

from cc_enrutador.models import ComplexityTier
from cc_enrutador.state import TaskStateStore, task_identity
from cc_enrutador.task_extraction import current_task_text


def test_current_task_text_skips_trailing_tool_result() -> None:
    request = {
        "messages": [
            {"role": "user", "content": "Fix the parser bug."},
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
                        "content": "architect from scratch",
                    }
                ],
            },
        ]
    }

    assert current_task_text(request) == "Fix the parser bug."


def test_task_identity_stays_stable_through_tool_loop() -> None:
    initial = {
        "messages": [{"role": "user", "content": "Fix the parser bug."}]
    }
    continued = {
        "messages": [
            {"role": "user", "content": "Fix the parser bug."},
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
                        "content": "file contents",
                    }
                ],
            },
        ]
    }

    assert task_identity(initial) == task_identity(continued)


def test_fresh_user_instruction_changes_task_identity() -> None:
    first = {
        "messages": [{"role": "user", "content": "Fix the parser bug."}]
    }
    second = {
        "messages": [
            {"role": "user", "content": "Fix the parser bug."},
            {"role": "assistant", "content": "Done."},
            {"role": "user", "content": "Now rename foo to bar."},
        ]
    }

    assert task_identity(first) != task_identity(second)


def test_minimum_tier_never_demotes_within_task() -> None:
    store = TaskStateStore()

    assert store.apply_floor("task", ComplexityTier.MEDIUM) == ComplexityTier.MEDIUM
    assert store.apply_floor("task", ComplexityTier.SIMPLE) == ComplexityTier.MEDIUM
    assert store.apply_floor("task", ComplexityTier.COMPLEX) == ComplexityTier.COMPLEX
    assert store.apply_floor("task", ComplexityTier.MEDIUM) == ComplexityTier.COMPLEX


def test_floor_can_be_disabled() -> None:
    store = TaskStateStore()

    store.apply_floor("task", ComplexityTier.COMPLEX)
    assert (
        store.apply_floor(
            "task",
            ComplexityTier.SIMPLE,
            never_demote=False,
        )
        == ComplexityTier.SIMPLE
    )
