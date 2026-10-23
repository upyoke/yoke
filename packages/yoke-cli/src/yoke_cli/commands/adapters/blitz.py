"""Blitz direct-execution CLI adapters."""

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

BLITZ_SURVEY_USAGE = (
    "yoke direct-workflow blitz survey ITEM --path PATH [--path PATH ...] "
    "[--integration-target BRANCH] [--project P] [--session-id S] [--json]"
)


def blitz_survey(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke direct-workflow blitz survey",
        usage=BLITZ_SURVEY_USAGE,
    )
    parser.add_argument("item", help="Item to survey, as PREFIX-N.")
    parser.add_argument("--project", help="Project that owns the item.")
    parser.add_argument(
        "--path",
        dest="paths",
        action="append",
        required=True,
        help="Path the blitz will change; repeat for each path.",
    )
    parser.add_argument(
        "--integration-target",
        default="main",
        help="Branch the work merges into; default: main.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, BLITZ_SURVEY_USAGE)
    if parsed is None:
        return 2

    def _human(response, stdout, stderr) -> None:
        write_human(response.result or {}, stdout)

    return dispatch_and_emit(
        function_id="direct_workflow.blitz.survey",
        target=item_target("item", parsed.item, parsed.project),
        payload={
            "paths": parsed.paths,
            "integration_target": parsed.integration_target,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human,
    )


__all__ = ["BLITZ_SURVEY_USAGE", "blitz_survey"]
