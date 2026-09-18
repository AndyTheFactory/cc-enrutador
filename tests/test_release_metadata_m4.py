from __future__ import annotations

import tomllib
from pathlib import Path

from cc_enrutador import __version__


def test_runtime_version_matches_project_metadata() -> None:
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]

    assert __version__ == project["version"]
    assert __version__ == "1.0.0rc1"
