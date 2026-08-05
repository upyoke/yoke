"""Session inspection and admin command handlers.

Covers ``harness-capabilities`` — resolve shared capabilities plus manifest
limits.
"""

from __future__ import annotations

import json
import sys


def cmd_harness_capabilities(args: list[str]) -> int:
    """Resolve shared harness capabilities keyed by executor.

    Usage: harness-capabilities --executor E --workspace W

    Prints JSON with downstream_paths and source.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="harness-capabilities", add_help=False)
    parser.add_argument("--executor", required=True)
    parser.add_argument("--workspace", required=True)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print("Usage: harness-capabilities --executor E --workspace W", file=sys.stderr)
        return 2

    from yoke_core.domain.sessions import resolve_harness_capabilities
    result = resolve_harness_capabilities(parsed.executor, parsed.workspace)
    print(json.dumps(result))
    return 0


__all__ = [
    "cmd_harness_capabilities",
]
