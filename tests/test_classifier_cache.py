from __future__ import annotations

from cc_enrutador.classifier import ClassificationCache
from cc_enrutador.models import ComplexityTier


def test_lru_cache_evicts_oldest_entry() -> None:
    cache = ClassificationCache(2)
    cache.put("a", ComplexityTier.SIMPLE)
    cache.put("b", ComplexityTier.MEDIUM)
    assert cache.get("a") == ComplexityTier.SIMPLE

    cache.put("c", ComplexityTier.COMPLEX)

    assert cache.get("a") == ComplexityTier.SIMPLE
    assert cache.get("b") is None
    assert cache.get("c") == ComplexityTier.COMPLEX


def test_zero_sized_cache_stores_nothing() -> None:
    cache = ClassificationCache(0)
    cache.put("a", ComplexityTier.SIMPLE)
    assert cache.get("a") is None
    assert len(cache) == 0
