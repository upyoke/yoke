"""CLI adapter for metadata-only project infrastructure discovery."""

from __future__ import annotations

import argparse
import json
from typing import List

from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)


PROJECTS_INFRASTRUCTURE_LIST_USAGE = (
    "yoke projects infrastructure list --project NAME "
    "[--session-id S] [--json]"
)


def projects_infrastructure_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects infrastructure list",
        description=(
            "List metadata-only site and environment inventory for a project."
        ),
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, PROJECTS_INFRASTRUCTURE_LIST_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        if response.success:
            print(json.dumps(response.result or {}, sort_keys=True), file=stdout)

    return dispatch_and_emit(
        function_id="projects.infrastructure.list",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "PROJECTS_INFRASTRUCTURE_LIST_USAGE",
    "projects_infrastructure_list",
]
