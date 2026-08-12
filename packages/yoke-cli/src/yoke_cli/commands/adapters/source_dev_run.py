"""Client-local adapter for claimed-lane source commands."""

from __future__ import annotations

import importlib
from typing import List


def source_dev_run(args: List[str]) -> int:
    runner = importlib.import_module("yoke_core.tools.source_dev_run")
    return runner.main(args)


__all__ = ["source_dev_run"]
