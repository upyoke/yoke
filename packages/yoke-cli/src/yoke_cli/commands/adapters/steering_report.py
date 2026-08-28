"""CLI adapter for the ``steering.report.*`` family."""

from __future__ import annotations

import argparse
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


STEERING_REPORT_GET_USAGE = "yoke steering report get --project P [--json]"

STEERING_REPORT_GET_DESCRIPTION = """\
Read this steering scope's fleet report.

The report names what a steering session cannot see from inside its own turn:
runnable work nobody picked up, work whose owner was released and never
replaced, claim holders that have gone quiet, and which machine/surface pairs
a launch could actually reach right now. It reports; it never staffs.

Runs from the live steering claim holder. The same report is appended to the
messages that session receives, so this command is the pull form of what
already arrives on its own -- reach for it when you want the picture between
wakes.

Two `project-policy` keys tune it: `steering_report_stale_minutes` (default
20) is how long work sits unowned, or a holder stays quiet, before the report
names it, and `steering_report_interval_minutes` (default 2) is the shortest
gap between reports appended to one session's messages.

  yoke steering report get --project yoke
  yoke steering report get --project yoke --json
"""


def _print_report(response: Any, stdout, _stderr) -> None:
    result = response.result or {}
    body = str(result.get("body") or "").strip()
    print(body or "steering report: nothing to show", file=stdout)


def steering_report_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke steering report get",
        usage=STEERING_REPORT_GET_USAGE,
        description=STEERING_REPORT_GET_DESCRIPTION,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STEERING_REPORT_GET_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="steering.report.get",
        target=TargetRef(
            kind="global",
            project_id=client_project_context(parsed.project),
        ),
        payload={},
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _print_report,
    )


USAGE_BY_FUNCTION_ID = {
    "steering.report.get": STEERING_REPORT_GET_USAGE,
}


__all__ = [
    "STEERING_REPORT_GET_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "steering_report_get",
]
