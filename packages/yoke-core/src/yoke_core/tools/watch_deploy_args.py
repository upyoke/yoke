"""Argument normalization for the deploy watcher wrapper."""

from __future__ import annotations

from yoke_core.tools import _watch_runner


def strip_separator(passthrough: list[str]) -> list[str]:
    """Drop a leading ``--`` left by ``argparse.REMAINDER``."""
    if passthrough and passthrough[0] == "--":
        return passthrough[1:]
    return passthrough


def extract_streaming_flag(argv: list[str]) -> tuple[list[str], bool]:
    """Pull the streaming-pair flag out of any argument position."""
    filtered: list[str] = []
    found = False
    for arg in argv:
        if arg == _watch_runner.PRINT_STREAMING_PAIR_FLAG:
            found = True
            continue
        filtered.append(arg)
    return filtered, found


__all__ = ["extract_streaming_flag", "strip_separator"]
