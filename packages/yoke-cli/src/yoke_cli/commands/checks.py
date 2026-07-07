"""Tool-shaped local checks exposed through sanctioned ``yoke`` tokens."""

from __future__ import annotations

import sys
from typing import Callable, Dict, List, Tuple

AdapterFn = Callable[[List[str]], int]

FILE_LINE_USAGE = (
    "yoke check file-line [--base REF | --staged] [--repo PATH] [--json]"
)

_FILE_LINE_HELP = """\
usage: yoke check file-line [--base REF | --staged] [--repo PATH] [--json]
       yoke check file-line report [--repo PATH] [--json]

Enforce Yoke's 350-line authored-file limit from a sanctioned local
CLI surface. The default mode checks branch-vs-base changes; use
--staged for the pre-commit shape. The report mode prints the tracked
file inventory.

Implementation owner: yoke_harness.git_hooks.file_line_check."""


def _wants_help(args: List[str]) -> bool:
    return any(a in ("-h", "--help") for a in args)


def check_file_line(args: List[str]) -> int:
    """Run the product-safe file-line gate."""
    if _wants_help(args):
        print(_FILE_LINE_HELP)
        return 0
    forwarded = list(args)
    if not forwarded or forwarded[0] not in ("check", "report"):
        forwarded.insert(0, "check")
    try:
        from yoke_harness.git_hooks.file_line_cli import main
    except ImportError as exc:
        sys.stderr.write(
            "yoke check file-line requires yoke-harness; "
            f"install/repair the product helper package ({exc}).\n"
        )
        return 1
    return int(main(forwarded))


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("check", "file-line"): check_file_line,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke check file-line": (
        "Run the authored-file line-limit gate; defaults to --base main, "
        "or pass --staged for pre-commit shape."
    ),
}


__all__ = [
    "FILE_LINE_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "check_file_line",
]
