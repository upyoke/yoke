"""Tool-shaped ``yoke usher reconcile-github`` recovery command."""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error


AdapterFn = Callable[[List[str]], int]

USHER_RECONCILE_GITHUB_USAGE = (
    "yoke usher reconcile-github PREFIX-N [--workflow-run-id ID] [--project P]"
)

_USHER_RECONCILE_GITHUB_HELP = """\
Correct Yoke's deploy records for an item when the usher deploy reported a
failure but the GitHub Actions workflow succeeded. Pass --workflow-run-id
when you know which GitHub Actions run proves the success. Needs the Yoke
source-dev or admin runtime."""


def usher_reconcile_github(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke usher reconcile-github",
        usage=USHER_RECONCILE_GITHUB_USAGE,
        description=_USHER_RECONCILE_GITHUB_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("item", metavar="PREFIX-N", help="The item whose deploy to correct.")
    parser.add_argument(
        "--workflow-run-id",
        default="",
        metavar="ID",
        help="GitHub Actions run id to use as evidence.",
    )
    parser.add_argument(
        "--project",
        default=None,
        metavar="P",
        help="Ignored; the project comes from the item's deployment run.",
    )
    parsed = parse_or_usage_error(
        parser,
        args,
        USHER_RECONCILE_GITHUB_USAGE,
    )
    if parsed is None:
        return 2

    forwarded = [parsed.item]
    if parsed.workflow_run_id:
        forwarded.extend(["--workflow-run-id", parsed.workflow_run_id])

    try:
        engine = importlib.import_module("yoke_core.engines.usher_reconcile_github")
    except ImportError as exc:
        print(
            "yoke usher reconcile-github requires the Yoke "
            "source-dev/admin runtime "
            f"(yoke_core.engines.usher_reconcile_github import failed: {exc}).",
            file=sys.stderr,
        )
        return 1

    return int(engine.main(forwarded))


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("usher", "reconcile-github"): usher_reconcile_github,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke usher reconcile-github": (
        "Align failed deploy records with GitHub Actions truth before resume."
    ),
}


__all__ = [
    "USHER_RECONCILE_GITHUB_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "usher_reconcile_github",
]
