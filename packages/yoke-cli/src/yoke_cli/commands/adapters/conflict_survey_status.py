"""Read-only conflict-survey status CLI adapter for direct workflows."""

from __future__ import annotations
from yoke_cli.transport.human_values import write_human

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)

CONFLICT_SURVEY_STATUS_USAGE = (
    "yoke direct-workflow conflict-survey status PREFIX-N "
    "[--project P] [--full] [--session-id S] [--json]"
)


def conflict_survey_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke direct-workflow conflict-survey status",
        usage=CONFLICT_SURVEY_STATUS_USAGE,
    )
    parser.add_argument("item", metavar="PREFIX-N", help="Item to read, as PREFIX-N.")
    parser.add_argument("--project", metavar="P", help="Project that owns the item.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CONFLICT_SURVEY_STATUS_USAGE)
    if parsed is None:
        return 2

    def _human(response, stdout, stderr) -> None:
        write_human(response.result or {}, stdout)

    return dispatch_and_emit(
        function_id="direct_workflow.conflict_survey.status",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human,
    )


__all__ = ["CONFLICT_SURVEY_STATUS_USAGE", "conflict_survey_status"]
