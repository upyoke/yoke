"""Blitz direct-execution CLI adapters."""

from __future__ import annotations

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
        description=BLITZ_SURVEY_USAGE,
    )
    parser.add_argument("item")
    parser.add_argument("--project")
    parser.add_argument("--path", dest="paths", action="append", required=True)
    parser.add_argument("--integration-target", default="main")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, BLITZ_SURVEY_USAGE)
    if parsed is None:
        return 2

    def _human(response, stdout, stderr) -> None:
        result = response.result or {}
        if result.get("clear"):
            print(f"survey-clear|{result.get('fingerprint') or ''}", file=stdout)
            return
        for blocker in result.get("blockers") or []:
            print(
                "survey-blocked|"
                + "|".join(
                    str(blocker.get(key) or "")
                    for key in ("kind", "owner_item_id", "path", "state", "detail")
                ),
                file=stdout,
            )

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
