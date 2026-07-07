"""Tool-shaped ``yoke resync`` source-dev/admin command."""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error


AdapterFn = Callable[[List[str]], int]

RESYNC_USAGE = "yoke resync [--fix]"

_RESYNC_HELP_DEEP = """\
Detect drift between the Yoke backlog DB and linked GitHub issues.
Without flags, the command is read-only and prints the drift report.
Pass --fix to repair fixable GitHub drift so GitHub matches the backlog.

This is the sanctioned source-dev/admin command surface for the resync
skill. It delegates to the resync engine boundary and preserves the
human-readable drift report."""


def resync(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke resync",
        description=f"{RESYNC_USAGE}\n\n{_RESYNC_HELP_DEEP}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--detect-only",
        action="store_true",
        help="Read-only drift report (default).",
    )
    mode.add_argument(
        "--fix",
        action="store_true",
        help="Repair fixable GitHub drift.",
    )
    parsed = parse_or_usage_error(parser, args, RESYNC_USAGE)
    if parsed is None:
        return 2

    try:
        engine = importlib.import_module("yoke_core.engines.resync")
    except ImportError as exc:
        print(
            "yoke resync requires the Yoke source-dev/admin runtime "
            f"(yoke_core.engines.resync import failed: {exc}).",
            file=sys.stderr,
        )
        return 1

    forwarded = ["--fix"] if parsed.fix else ["--detect-only"]
    return int(engine.main(forwarded))


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("resync",): resync,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke resync": (
        "Detect backlog/GitHub drift; pass --fix to repair fixable drift."
    ),
}


__all__ = [
    "RESYNC_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "resync",
]
