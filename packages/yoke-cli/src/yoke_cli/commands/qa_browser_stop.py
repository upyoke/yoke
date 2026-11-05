"""Stop the machine-local Browser QA daemon."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error, usage_error
from yoke_cli.config.project_selection import required_project_context
from yoke_contracts.browser_identity import BrowserIdentityError
from yoke_contracts.project_defaults import MissingProjectError


QA_BROWSER_STOP_USAGE = (
    "yoke qa browser stop --check-id ID [--project PROJECT] [--identity NAME] [--json]"
)


def qa_browser_stop(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser stop",
        description="Stop a private QA check and delete its copied sign-in state.",
    )
    parser.add_argument("--check-id", required=True, help="Private check id to close.")
    parser.add_argument(
        "--project",
        default=None,
        help="Project whose browser to stop; default: the current project.",
    )
    parser.add_argument(
        "--identity",
        default=None,
        help="Browser identity whose daemon to stop; default: default.",
    )
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Print JSON instead of text.",
    )
    parsed = parse_or_usage_error(parser, args, QA_BROWSER_STOP_USAGE)
    if parsed is None:
        return 2
    try:
        parsed.project = required_project_context(parsed.project)
    except MissingProjectError as exc:
        return usage_error(str(exc))

    try:
        from yoke_harness import browser_check_profile  # noqa: F401
    except ImportError as exc:
        print(
            f"yoke qa browser stop requires yoke-harness in the product install: {exc}",
            file=sys.stderr,
        )
        return 2

    try:
        from yoke_harness.browser_check_profile import check_scope

        with check_scope(parsed.project, parsed.identity, check_id=parsed.check_id):
            pass
    except (RuntimeError, BrowserIdentityError) as exc:
        text = str(exc)
        if text == "daemon not running":
            return _emit(parsed.json_mode, {"status": "not_running"})
        print(
            f"yoke qa browser stop: {text}. "
            "Run `yoke qa browser status` to inspect the daemon, then retry.",
            file=sys.stderr,
        )
        return 1
    return _emit(parsed.json_mode, {"status": "stopped"})


def _emit(json_mode: bool, payload: dict[str, str]) -> int:
    if json_mode:
        print(json.dumps(payload))
    else:
        print(payload["status"])
    return 0


__all__ = [
    "QA_BROWSER_STOP_USAGE",
    "qa_browser_stop",
]
