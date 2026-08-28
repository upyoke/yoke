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

The report names what a steering session cannot see from inside its own turn.
It leads with available work -- everything runnable and unclaimed, each row
marked `new` (never started) or `stopped` (owner released) and flagged `!`
once it has waited past the staffing threshold -- and then names the failures
that arrive as silence: claim holders that have gone quiet, envelopes the
delivery plane never injected, launches past their deadline that never
registered a session, branches that landed while their item stayed open, and
idle holders waiting on an answer that cannot arrive. It closes with the
machine/surface pairs a launch could actually reach. It reports; it never
staffs. A detector with nothing to say prints nothing.

Runs from the live steering claim holder. The same report is appended to the
messages that session receives, so this command is the pull form of what
already arrives on its own -- reach for it when you want the picture between
wakes.

Three `project-policy` keys tune it. `steering_report_staffing_minutes`
(default 5) is how long runnable unclaimed work may sit before the report
marks it overdue. `steering_report_idle_minutes` (default 20) is how long a
claim holder stays quiet before the report presumes it stuck -- a separate
judgment from the staffing one, not the same number twice. And
`steering_report_interval_minutes` (default 2) is the shortest gap between
reports appended to one session's messages.

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
