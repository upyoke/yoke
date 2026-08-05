"""Tool-shaped release-pin verification through sanctioned ``yoke`` tokens."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.release_pin_verify import (
    VERIFY_USAGE,
    release_pin_verify,
)

AdapterFn = Callable[[List[str]], int]

TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("release-pin", "verify"): release_pin_verify,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke release-pin verify": (
        "Compare environments.settings.release.yoke_pin to the configured "
        "health probe without deploying."
    ),
}


__all__ = [
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "VERIFY_USAGE",
]
