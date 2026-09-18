from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, cast

from cc_enrutador.config import AppConfig, ClassifierConfig
from cc_enrutador.models import ClassificationResult, ComplexityTier, HeuristicDecision
from cc_enrutador.task_extraction import (
    has_images,
    is_agentic,
    is_mid_loop,
    latest_user_text,
    message_count,
    system_text,
    tool_count,
    user_message_count,
)

# Adapted in behavior from serhiileniv/claude-router (MIT).
_TRANSFORM_RE = re.compile(
    r"\b(translate|reformat|format|convert|rename|extract|list|count|spell|"
    r"capitalize|capitalise|lowercase|uppercase|sort)\b",
    re.IGNORECASE,
)
_DEPTH_RE = re.compile(
    r"\b(architect|prove|derive|critique|threat\s+model|migration\s+plan|"
    r"trade[- ]?offs?|end[- ]to[- ]end|from\s+scratch)\b|"
    r"\bdesign\s+(?:a|an|the)\s+[^\n]{0,80}\b(?:system|architecture)\b",
    re.IGNORECASE,
)
_LONG_HORIZON_RE = re.compile(
    r"\b(?:refactor|rewrite)\s+(?:the\s+)?(?:whole|entire)\b|"
    r"\bmulti[- ]step\b|"
    r"\bstep[- ]by[- ]step\s+plan\b|"
    r"\bacross\s+(?:the\s+)?(?:codebase|repo|repository)\b",
    re.IGNORECASE,
)
_CODE_FENCE_RE = re.compile(r"```")


AICompletion = Callable[[str, ClassifierConfig], Awaitable[str]]


def heuristic_classify(
    request: Mapping[str, Any],
    config: ClassifierConfig,
) -> HeuristicDecision:
    task = latest_user_text(request)
    system = system_text(request)
    agentic = is_agentic(request)
    mid_loop = is_mid_loop(request)

    if agentic:
        if mid_loop:
            return HeuristicDecision(
                tier=ComplexityTier.MEDIUM,
                reason="agentic:mid-loop",
                confidence=0.9,
                explicit_gate=True,
            )
        if _has_complex_evidence(task):
            return HeuristicDecision(
                tier=ComplexityTier.COMPLEX,
                reason="agentic:explicit-depth",
                confidence=0.9,
                explicit_gate=True,
            )
        # The three agentic outcomes are always decisive (functional.md §4.3): fall
        # through to the simple gate only when explicitly opted in, and floor at
        # MEDIUM otherwise instead of ever reaching the non-agentic "abstain" path
        # below, which would incorrectly let hybrid mode invoke the AI classifier.
        if config.heuristic.allow_simple_in_agentic and _simple_gate(request, task, system, config):
            return HeuristicDecision(
                tier=ComplexityTier.SIMPLE,
                reason="simple:mechanical-transform",
                confidence=0.9,
                explicit_gate=True,
            )
        return HeuristicDecision(
            tier=ComplexityTier.MEDIUM,
            reason="agentic:floor-medium",
            confidence=0.8,
            explicit_gate=True,
        )

    if _simple_gate(request, task, system, config):
        return HeuristicDecision(
            tier=ComplexityTier.SIMPLE,
            reason="simple:mechanical-transform",
            confidence=0.9,
            explicit_gate=True,
        )

    if _has_complex_evidence(task):
        return HeuristicDecision(
            tier=ComplexityTier.COMPLEX,
            reason="complex:explicit-depth-or-long-horizon",
            confidence=0.9,
            explicit_gate=True,
        )

    return HeuristicDecision(
        tier=ComplexityTier.MEDIUM,
        reason="default:medium",
        confidence=0.5,
        explicit_gate=False,
    )


def _simple_gate(
    request: Mapping[str, Any],
    task: str,
    system: str,
    config: ClassifierConfig,
) -> bool:
    if not task:
        return False
    if user_message_count(request) != 1 or message_count(request) != 1:
        return False
    if len(task) > config.heuristic.simple_max_chars:
        return False
    if len(system) > config.heuristic.system_max_chars:
        return False
    if _CODE_FENCE_RE.search(task):
        return False
    if has_images(request):
        return False
    if _has_complex_evidence(task):
        return False
    return _TRANSFORM_RE.search(task) is not None


def _has_complex_evidence(task: str) -> bool:
    return bool(_DEPTH_RE.search(task) or _LONG_HORIZON_RE.search(task))


def build_classifier_snippet(
    request: Mapping[str, Any],
    config: ClassifierConfig,
) -> tuple[str, str]:
    task = latest_user_text(request)
    system = system_text(request)
    extraction = config.extraction

    head = task[: extraction.task_head_chars]
    if extraction.task_tail_chars and len(task) > extraction.task_head_chars:
        tail = task[-extraction.task_tail_chars :]
        compact_task = head + "\n...\n" + tail
    else:
        compact_task = head

    return compact_task, system[: extraction.system_prefix_chars]


def render_classifier_prompt(request: Mapping[str, Any], config: ClassifierConfig) -> str:
    task, system = build_classifier_snippet(request, config)
    values = {
        "task": task,
        "system": system,
        "is_agentic": str(is_agentic(request)).lower(),
        "is_mid_loop": str(is_mid_loop(request)).lower(),
        "message_count": message_count(request),
        "tool_count": tool_count(request),
    }
    return config.prompt.format(**values)


def parse_classifier_output(raw: str, config: ClassifierConfig) -> ComplexityTier:
    value = raw.strip()
    mapping = {
        config.output.simple.strip(): ComplexityTier.SIMPLE,
        config.output.medium.strip(): ComplexityTier.MEDIUM,
        config.output.complex.strip(): ComplexityTier.COMPLEX,
    }
    if value not in mapping:
        raise ValueError(f"unrecognized classifier output: {value!r}")
    return mapping[value]


def classifier_cache_key(request: Mapping[str, Any]) -> str:
    normalized = {
        "task": latest_user_text(request).strip(),
        "system": system_text(request).strip(),
        "message_count": message_count(request),
        "tool_count": tool_count(request),
        "agentic": is_agentic(request),
        "mid_loop": is_mid_loop(request),
    }
    payload = json.dumps(normalized, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ClassificationCache:
    def __init__(self, max_size: int) -> None:
        self.max_size = max_size
        self._values: OrderedDict[str, ComplexityTier] = OrderedDict()

    def get(self, key: str) -> ComplexityTier | None:
        value = self._values.get(key)
        if value is None:
            return None
        self._values.move_to_end(key)
        return value

    def put(self, key: str, value: ComplexityTier) -> None:
        if self.max_size <= 0:
            return
        self._values[key] = value
        self._values.move_to_end(key)
        while len(self._values) > self.max_size:
            self._values.popitem(last=False)

    def __len__(self) -> int:
        return len(self._values)


async def litellm_completion(prompt: str, config: ClassifierConfig) -> str:
    import litellm

    kwargs: dict[str, Any] = {
        "model": config.model.model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": config.max_output_tokens,
        "temperature": config.temperature,
        "timeout": config.timeout_ms / 1000,
    }
    if config.model.api_base:
        kwargs["api_base"] = config.model.api_base

    if config.model.api_key_env:
        import os

        api_key = os.getenv(config.model.api_key_env)
        if api_key:
            kwargs["api_key"] = api_key

    # ClassifierService.classify() already wraps every ai_completion call (this one
    # included) in asyncio.wait_for(timeout_ms); litellm's own "timeout" kwarg above
    # covers the request itself. A second asyncio.wait_for here would be redundant.
    response = await litellm.acompletion(**kwargs)
    response_any = cast(Any, response)
    content = response_any.choices[0].message.content
    if not isinstance(content, str):
        raise ValueError("classifier returned non-text content")
    return content


class ClassifierService:
    def __init__(
        self,
        app_config: AppConfig,
        ai_completion: AICompletion = litellm_completion,
    ) -> None:
        self.config = app_config.classifier
        self.ai_completion = ai_completion
        self.cache = ClassificationCache(self.config.cache_size)

    async def classify(self, request: Mapping[str, Any]) -> ClassificationResult:
        started = time.perf_counter()
        heuristic = heuristic_classify(request, self.config)

        if self.config.mode == "heuristic":
            return self._heuristic_result(heuristic, started)

        if self.config.mode == "hybrid" and heuristic.explicit_gate:
            return self._heuristic_result(heuristic, started)

        cache_key = classifier_cache_key(request)
        cached = self.cache.get(cache_key)
        if cached is not None:
            return ClassificationResult(
                tier=cached,
                method="ai" if self.config.mode == "ai" else "hybrid",
                reason="ai:cache-hit",
                confidence=0.75,
                latency_ms=(time.perf_counter() - started) * 1000,
                cached=True,
            )

        try:
            prompt = render_classifier_prompt(request, self.config)
            raw = await asyncio.wait_for(
                self.ai_completion(prompt, self.config),
                timeout=self.config.timeout_ms / 1000,
            )
            tier = parse_classifier_output(raw, self.config)
        except Exception:
            # Classifier/provider failures must never block the routed user request.
            # asyncio.CancelledError is a BaseException and still propagates correctly.
            return self._heuristic_result(heuristic, started, reason_prefix="ai-fallback:")

        self.cache.put(cache_key, tier)
        return ClassificationResult(
            tier=tier,
            method="ai" if self.config.mode == "ai" else "hybrid",
            reason="ai:classified",
            confidence=0.75,
            latency_ms=(time.perf_counter() - started) * 1000,
            cached=False,
        )

    @staticmethod
    def _heuristic_result(
        decision: HeuristicDecision,
        started: float,
        reason_prefix: str = "",
    ) -> ClassificationResult:
        return ClassificationResult(
            tier=decision.tier,
            method="heuristic",
            reason=reason_prefix + decision.reason,
            confidence=decision.confidence,
            latency_ms=(time.perf_counter() - started) * 1000,
            cached=False,
        )
