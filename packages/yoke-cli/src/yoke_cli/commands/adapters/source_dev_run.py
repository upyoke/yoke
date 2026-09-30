"""Client-local adapter for claimed-lane source commands."""

from __future__ import annotations

import importlib
from typing import List


def _source_runner():
    return importlib.import_module("yoke_core.tools.source_dev_run")


def source_dev_run(args: List[str]) -> int:
    return _source_runner().main(args)


def ruff_changed(args: List[str]) -> int:
    return _source_runner().run(
        ["python3", "-m", "yoke_core.tools.ruff_changed", *args]
    )


def import_check(args: List[str]) -> int:
    return _source_runner().run(
        ["python3", "-m", "yoke_core.tools.import_check", *args]
    )


__all__ = ["import_check", "ruff_changed", "source_dev_run"]
