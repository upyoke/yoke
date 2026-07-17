"""``yoke projects capabilities list`` adapter (read-only capability roster).

Split from :mod:`yoke_cli.commands.adapters.projects` (which owns the
projects get/list/resolve wrappers) to keep that module under the
authored-file line cap.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


PROJECTS_CAPABILITIES_LIST_USAGE = (
    "yoke projects capabilities list [--project P] [--session-id S] [--json]"
)


def projects_capabilities_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects capabilities list",
        description=PROJECTS_CAPABILITIES_LIST_USAGE,
    )
    parser.add_argument("--project", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, PROJECTS_CAPABILITIES_LIST_USAGE,
    )
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        fields = result.get("fields") or []
        for row in result.get("rows") or []:
            print(
                "|".join(
                    "" if row.get(field) is None else str(row.get(field))
                    for field in fields
                ),
                file=stdout,
            )
        return None

    payload: Dict[str, Any] = {}
    if parsed.project is not None:
        payload["project"] = parsed.project
    return dispatch_and_emit(
        function_id="projects.capabilities.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "PROJECTS_CAPABILITIES_LIST_USAGE",
    "projects_capabilities_list",
]
