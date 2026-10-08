"""``yoke projects level-summary get`` — the execution levels a project reads."""

from __future__ import annotations

import argparse
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.universe_levels import write_levels
from yoke_contracts.api.function_call import TargetRef


PROJECTS_LEVEL_SUMMARY_GET_USAGE = (
    "yoke projects level-summary get --project NAME [--session-id S] [--json]"
)


def _write_summary(response, stdout, stderr) -> None:
    del stderr
    if response.success:
        write_levels(response.result or {}, stdout)
    return None


def projects_level_summary_get(args: List[str]) -> int:
    """Print the levels a project reads and whether they are its override."""
    parser = argparse.ArgumentParser(
        prog="yoke projects level-summary get",
        description=(
            "Read the execution levels one project uses, lowest first, with "
            "each level's glyph and ordered launchable options, and whether "
            "they come from the project's override or the universe. Set an "
            "override with `yoke projects capability-settings set --project "
            "NAME --cap-type session-routing --settings-json "
            "'{\"levels\": [...]}' --new`; remove it with `yoke projects "
            "capability-settings remove` to read the universe levels again."
        ),
    )
    parser.add_argument("--project", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed: Any = parse_or_usage_error(parser, args, PROJECTS_LEVEL_SUMMARY_GET_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="projects.level_summary.get",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_summary,
    )


USAGE_BY_FUNCTION_ID = {
    "projects.level_summary.get": PROJECTS_LEVEL_SUMMARY_GET_USAGE,
}


__all__ = [
    "PROJECTS_LEVEL_SUMMARY_GET_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "projects_level_summary_get",
]
