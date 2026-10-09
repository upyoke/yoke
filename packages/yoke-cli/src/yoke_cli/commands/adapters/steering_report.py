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


STEERING_REPORT_GET_USAGE = "yoke steering report get [--project P] [--full] [--json]"

STEERING_REPORT_GET_DESCRIPTION = """\
Read the fleet report for every steering scope this session holds.

Default human output shows changed scope, inbox and shared-machine sections
since this session's last pull read, plus an unchanged count. --full prints
everything and advances that read checkpoint. --json preserves every fact
without consuming the human read checkpoint. Hook/watcher delivery is separate.

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
reports appended to one session.

A session receives a report only when what its digest shows changed. The
hook and the fleet watcher share one delivery record per session, so a report
one of them delivered is not delivered again by the other. Deployment runs,
landed items, undelivered messages and launch failures belong to a project,
not a seat: they render once per project, under its first held scope. A
landed item already listed as a run member is not repeated, and each waiting
run member is one line with its blocker count — the per-requirement detail
is `yoke deployment-runs stages RUN`.

  yoke steering report get
  yoke steering report get --project yoke
  yoke steering report get --json
"""


def _print_report(response: Any, stdout, _stderr) -> None:
    result = response.result or {}
    body = str(result.get("delta_body", result.get("body")) or "").strip()
    print(body or "steering report: nothing to show", file=stdout)


def _print_full_report(response: Any, stdout, _stderr) -> None:
    print((response.result or {}).get("body") or "steering report: nothing to show", file=stdout)


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
    parser.add_argument("--full", action="store_true", help="Print every report section.")
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
        payload=({} if parsed.json_mode else {"read_delta": True, "full": parsed.full}),
        session_id=None,
        json_mode=parsed.json_mode,
        human_writer=(None if parsed.json_mode else _print_full_report if parsed.full else _print_report),
    )


USAGE_BY_FUNCTION_ID = {
    "steering.report.get": STEERING_REPORT_GET_USAGE,
}


__all__ = [
    "STEERING_REPORT_GET_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "steering_report_get",
]
