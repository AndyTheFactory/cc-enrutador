from __future__ import annotations

import hashlib
import json
from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from cc_enrutador.models import ComplexityTier
from cc_enrutador.task_extraction import current_task_text, system_text

_TIER_RANK = {
    ComplexityTier.SIMPLE: 0,
    ComplexityTier.MEDIUM: 1,
    ComplexityTier.COMPLEX: 2,
}


@dataclass
class TaskState:
    task_id: str
    minimum_tier: ComplexityTier


def task_identity(
    request: Mapping[str, Any],
    headers: Mapping[str, str] | None = None,
) -> str:
    normalized_headers = {key.lower(): value for key, value in (headers or {}).items()}
    metadata = request.get("metadata")
    metadata_map = metadata if isinstance(metadata, Mapping) else {}

    explicit_session = next(
        (
            value
            for value in (
                metadata_map.get("session_id"),
                metadata_map.get("conversation_id"),
                normalized_headers.get("x-session-id"),
                normalized_headers.get("x-conversation-id"),
            )
            if isinstance(value, str) and value
        ),
        "",
    )
    anchor = current_task_text(request)
    payload = {
        "session": explicit_session,
        "anchor": anchor.strip(),
        "system": system_text(request).strip()[:500],
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class TaskStateStore:
    def __init__(self, max_tasks: int = 1000) -> None:
        self.max_tasks = max_tasks
        self._states: OrderedDict[str, TaskState] = OrderedDict()

    def apply_floor(
        self,
        task_id: str,
        proposed: ComplexityTier,
        *,
        never_demote: bool = True,
    ) -> ComplexityTier:
        state = self._states.get(task_id)
        if state is None:
            self._put(TaskState(task_id=task_id, minimum_tier=proposed))
            return proposed

        self._states.move_to_end(task_id)
        if not never_demote:
            state.minimum_tier = proposed
            return proposed

        if _TIER_RANK[proposed] > _TIER_RANK[state.minimum_tier]:
            state.minimum_tier = proposed
        return state.minimum_tier

    def promote(self, task_id: str, tier: ComplexityTier) -> None:
        state = self._states.get(task_id)
        if state is None:
            self._put(TaskState(task_id=task_id, minimum_tier=tier))
            return
        if _TIER_RANK[tier] > _TIER_RANK[state.minimum_tier]:
            state.minimum_tier = tier
        self._states.move_to_end(task_id)

    def get(self, task_id: str) -> TaskState | None:
        return self._states.get(task_id)

    def _put(self, state: TaskState) -> None:
        if self.max_tasks <= 0:
            return
        self._states[state.task_id] = state
        self._states.move_to_end(state.task_id)
        while len(self._states) > self.max_tasks:
            self._states.popitem(last=False)
