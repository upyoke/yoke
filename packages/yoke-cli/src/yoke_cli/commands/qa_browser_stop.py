"""Stop the machine-local Browser QA daemon."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error, usage_error
from yoke_cli.config.project_selection import required_project_context
from yoke_contracts.project_defaults import MissingProjectError


QA_BROWSER_STOP_USAGE = "yoke qa browser stop [--project PROJECT] [--json]"


def _profile_dir(project: str) -> str:
    """The profile whose daemon status reports, or ``""`` for the clean one."""
    from yoke_cli.config.browser_profile import authorized_profile_dir

    authorized = authorized_profile_dir(project)
    return str(authorized) if authorized is not None else ""


def qa_browser_stop(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser stop",
        description=(
            "Stop the machine-local Browser QA daemon for the project's "
            "browser profile. A daemon that is already stopped is reported "
            "as not_running."
        ),
    )
    parser.add_argument("--project", default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, QA_BROWSER_STOP_USAGE)
    if parsed is None:
        return 2
    try:
        parsed.project = required_project_context(parsed.project)
    except MissingProjectError as exc:
        return usage_error(str(exc))

    try:
        from yoke_harness import browser_client
    except ImportError as exc:
        print(
            f"yoke qa browser stop requires yoke-harness in the product install: {exc}",
            file=sys.stderr,
        )
        return 2

    profile = _profile_dir(parsed.project)
    try:
        browser_client.daemon_stop(profile_dir=profile)
    except RuntimeError as exc:
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
