"""Client-local adapter for building and opening Yokepedia."""

from __future__ import annotations

import importlib
from typing import List


def yokepedia(args: List[str]) -> int:
    return importlib.import_module("yoke_core.tools.yokepedia").main(args)


__all__ = ["yokepedia"]
