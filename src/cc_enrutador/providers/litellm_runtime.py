from __future__ import annotations

import logging
import os
from typing import Any


def load_litellm() -> Any:
    os.environ.setdefault("LITELLM_LOG", "WARNING")

    import litellm

    litellm.suppress_debug_info = True
    level = getattr(logging, os.environ["LITELLM_LOG"].upper(), logging.WARNING)
    for name in ("LiteLLM", "LiteLLM Proxy", "LiteLLM Router"):
        logging.getLogger(name).setLevel(level)
    return litellm
