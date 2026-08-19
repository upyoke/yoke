"""Read-only conflict-survey status CLI adapter for direct workflows."""

from __future__ import annotations

import argparse
from typing import List

from yoke_contracts.conflict_survey import (
    DURABLE_RECORDED,
    DURABLE_UNREADABLE,
)
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)

CONFLICT_SURVEY_STATUS_USAGE = (
    "yoke direct-workflow conflict-survey status ITEM "
    "[--project P] [--session-id S] [--json]"
)


def conflict_survey_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke direct-workflow conflict-survey status",
        description=CONFLICT_SURVEY_STATUS_USAGE,
    )
    parser.add_argument("item")
    parser.add_argument("--project")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CONFLICT_SURVEY_STATUS_USAGE)
    if parsed is None:
        return 2

    def _human(response, stdout, stderr) -> None:
        result = response.result or {}
        durable_state = str(
            result.get("durable_state") or DURABLE_UNREADABLE
        )
        if durable_state != DURABLE_RECORDED:
            print(f"survey-{durable_state}", file=stdout)
            return
        if result.get("clear"):
            print("survey-clear", file=stdout)
            return
        for blocker in result.get("blockers") or []:
            print(
                "survey-blocked|"
                + "|".join(
                    str(blocker.get(key) or "")
                    for key in (
                        "kind", "owner_item_id", "path", "state", "detail",
                    )
                ),
                file=stdout,
            )

    return dispatch_and_emit(
        function_id="direct_workflow.conflict_survey.status",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human,
    )


__all__ = ["CONFLICT_SURVEY_STATUS_USAGE", "conflict_survey_status"]
