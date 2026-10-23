"""One-line plain-language summaries for every ``yoke`` command and group.

Summaries live in ``summaries/<top-level command>.json``, one object per
file keyed by the command path without ``yoke`` (``"items get"``). Help
pages print a command's summary first, and group catalogs print each
child's summary beside its name. An alias or alternate spelling that runs
the same adapter as a canonical command shares that command's summary.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Dict, Tuple

SUMMARY_MAX_CHARS = 60

Route = Tuple[str, ...]


@lru_cache(maxsize=1)
def explicit_summaries() -> Dict[Route, str]:
    """Every authored summary, keyed by route tuple."""
    out: Dict[Route, str] = {}
    root = files("yoke_cli.commands") / "summaries"
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        if not entry.name.endswith(".json"):
            continue
        for key, text in json.loads(entry.read_text(encoding="utf-8")).items():
            route = tuple(key.split())
            if route in out:
                raise ValueError(
                    f"command summary for 'yoke {key}' appears twice; "
                    f"keep one entry ({entry.name})"
                )
            out[route] = text
    return out


@lru_cache(maxsize=1)
def _adapter_summaries() -> Dict[object, str]:
    from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
    from yoke_cli.commands.tool_shaped import TOOL_SHAPED_SUBCOMMANDS

    authored = explicit_summaries()
    canonical = {
        **{route: adapter for route, (_fid, adapter) in SUBCOMMAND_REGISTRY.items()},
        **TOOL_SHAPED_SUBCOMMANDS,
    }
    by_adapter: Dict[object, set] = {}
    for route, adapter in canonical.items():
        if route in authored:
            by_adapter.setdefault(adapter, set()).add(authored[route])
    return {adapter: next(iter(texts)) for adapter, texts in by_adapter.items() if len(texts) == 1}


def summary_for(route: Route) -> str:
    """The summary for ``route``, or ``""`` when none is authored."""
    route = tuple(route)
    authored = explicit_summaries().get(route)
    if authored:
        return authored
    from yoke_cli.commands.command_tree import command_routes

    target = command_routes().get(route)
    if target is None:
        return ""
    return _adapter_summaries().get(target[1], "")


__all__ = ["SUMMARY_MAX_CHARS", "explicit_summaries", "summary_for"]
