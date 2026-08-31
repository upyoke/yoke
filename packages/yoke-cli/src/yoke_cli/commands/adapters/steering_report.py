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


STEERING_REPORT_GET_USAGE = "yoke steering report get [--project P] [--json]"

STEERING_REPORT_GET_DESCRIPTION = """\
Read the fleet report for every steering scope this session holds.

Omit --project to compose one report covering each live steering claim, with
a section named by that claim's scope descriptor (today, the project slug).
Pass --project to keep single-scope behavior. The same combined report rides
the messages this session already receives.

The report names what a steering session cannot see from inside its own turn.
It leads with available work -- everything runnable and unclaimed, each row
marked `new` (never started) or `stopped` (owner released) and flagged `!`
once it has waited past the staffing threshold -- and then names the failures
that arrive as silence. It reports; it never staffs. Scopes with actionable
rows sort first. A detector with nothing to say prints nothing.

Three `project-policy` keys tune each scope. `steering_report_staffing_minutes`
(default 5) is how long runnable unclaimed work may sit before the report
marks it overdue. `steering_report_idle_minutes` (default 20) is how long a
claim holder stays quiet before the report presumes it stuck. And
`steering_report_interval_minutes` (default 2) is the shortest gap between
reports appended to one session; one combined report per interval, attached
when any held scope changed or needs a decision.

  yoke steering report get
  yoke steering report get --project yoke
  yoke steering report get --json
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
    parser.add_argument(
        "--project",
        default=None,
        help="Optional filter: one held scope (slug or id). Omit to compose all.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, STEERING_REPORT_GET_USAGE)
    if parsed is None:
        return 2
    explicit = (parsed.project or "").strip() or None
    return dispatch_and_emit(
        function_id="steering.report.get",
        target=TargetRef(
            kind="global",
            project_id=client_project_context(explicit) if explicit else None,
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
