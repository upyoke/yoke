"""Tool-shaped ``yoke usher reconcile-github`` recovery command."""

from __future__ import annotations

import argparse
import importlib
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error


AdapterFn = Callable[[List[str]], int]

USHER_RECONCILE_GITHUB_USAGE = (
    "yoke usher reconcile-github YOK-N [--workflow-run-id ID]"
)

_USHER_RECONCILE_GITHUB_HELP = """\
Align Yoke deploy records with GitHub Actions truth when an usher deploy
reported failure but the GitHub workflow actually succeeded. Pass
--workflow-run-id when the operator has an explicit GH run id to use as
evidence."""


def usher_reconcile_github(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke usher reconcile-github",
        description=(
            f"{USHER_RECONCILE_GITHUB_USAGE}\n\n"
            f"{_USHER_RECONCILE_GITHUB_HELP}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("item", help="Item ref (YOK-N or bare N).")
    parser.add_argument(
        "--workflow-run-id",
        default="",
        help="Operator-provided GitHub Actions run id.",
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
        engine = importlib.import_module(
            "yoke_core.engines.usher_reconcile_github"
        )
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
