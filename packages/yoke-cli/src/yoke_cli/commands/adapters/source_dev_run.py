"""Client-local adapter for claimed-lane source commands."""

from __future__ import annotations

import importlib
from typing import List


def source_dev_run(args: List[str]) -> int:
    runner = importlib.import_module("yoke_core.tools.source_dev_run")
    return runner.main(args)


def ruff_changed(args: List[str]) -> int:
    runner = importlib.import_module("yoke_core.tools.source_dev_run")
    return runner.run(["python3", "-m", "yoke_core.tools.ruff_changed", *args])


__all__ = ["ruff_changed", "source_dev_run"]
