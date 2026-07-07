"""Tool-shaped ``yoke merge audit`` read-only merge audit command."""

from __future__ import annotations

import argparse
import importlib
import re
import sys
from typing import Callable, Dict, List, Optional, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error


AdapterFn = Callable[[List[str]], int]

MERGE_AUDIT_USAGE = "yoke merge audit [YOK-N|N]"

_MERGE_AUDIT_HELP = """\
Render the read-only merge readiness audit. With an item ref, limit the
report to that epic/item id. The command does not mutate DB state, git
state, or GitHub state."""


def _parse_optional_epic(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    text = re.sub(r"^[Yy][Oo][Kk]-", "", raw.strip())
    try:
        return int(text)
    except (TypeError, ValueError):
        raise ValueError(f"invalid epic ID: {raw}")


def merge_audit(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke merge audit",
        description=f"{MERGE_AUDIT_USAGE}\n\n{_MERGE_AUDIT_HELP}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "epic",
        nargs="?",
        help="Optional epic/item ref; accepts YOK-N or bare N.",
    )
    parsed = parse_or_usage_error(parser, args, MERGE_AUDIT_USAGE)
    if parsed is None:
        return 2

    try:
        epic_filter = _parse_optional_epic(parsed.epic)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    try:
        engine = importlib.import_module("yoke_core.engines.merge_audit")
    except ImportError as exc:
        print(
            "yoke merge audit requires the Yoke source-dev/admin runtime "
            f"(yoke_core.engines.merge_audit import failed: {exc}).",
            file=sys.stderr,
        )
        return 1

    print(engine.generate_report(epic_filter), end="")
    return 0


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("merge", "audit"): merge_audit,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke merge audit": (
        "Render the read-only merge readiness audit; pass YOK-N to filter."
    ),
}


__all__ = [
    "MERGE_AUDIT_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "merge_audit",
]
