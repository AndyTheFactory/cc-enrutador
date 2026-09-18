from __future__ import annotations

import logging
import sys
from types import SimpleNamespace
from typing import Any

from cc_enrutador.providers import litellm_runtime


def test_load_litellm_suppresses_routine_noise(monkeypatch: Any) -> None:
    fake_litellm = SimpleNamespace(suppress_debug_info=False)
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)
    monkeypatch.delenv("LITELLM_LOG", raising=False)
    for name in ("LiteLLM", "LiteLLM Proxy", "LiteLLM Router"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.NOTSET)

    loaded = litellm_runtime.load_litellm()

    assert loaded is fake_litellm
    assert fake_litellm.suppress_debug_info is True
    assert all(
        logging.getLogger(name).level == logging.WARNING
        for name in ("LiteLLM", "LiteLLM Proxy", "LiteLLM Router")
    )
