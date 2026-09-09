"""``yoke projects lane-summary get`` — the effective lane routing read."""

from __future__ import annotations

import argparse
from typing import Any, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


PROJECTS_LANE_SUMMARY_GET_USAGE = (
    "yoke projects lane-summary get --project NAME [--session-id S] [--json]"
)


def _write_summary(response, stdout, stderr) -> None:
    del stderr
    if not response.success:
        return None
    result = response.result or {}
    lanes = result.get("lanes") or []
    if not lanes:
        stdout.write("no lanes configured\n")
        return None
    for lane in lanes:
        glyph = lane.get("glyph") or " "
        stdout.write(f"{glyph} {lane.get('label') or lane.get('id')}\n")
        stdout.write(f"  identity      {lane.get('id')}\n")
        matches = lane.get("matches") or []
        stdout.write(
            "  matches       "
            + (
                "; ".join(
                    f"harness={match.get('harness') or 'any'} "
                    f"model={match.get('model') or 'any'}"
                    for match in matches
                )
                or "no custom matches"
            )
            + "\n"
        )
        actions = lane.get("actions") or []
        stdout.write(f"  actions       {', '.join(actions) or 'None'}\n")
        defaults = lane.get("default_for") or []
        stdout.write(f"  default for   {', '.join(defaults) or 'None'}\n")
    if not result.get("configured"):
        stdout.write(
            "\nThis project stores no session-routing capability; the summary "
            "above is the built-in default.\n"
        )
    return None


def projects_lane_summary_get(args: List[str]) -> int:
    """Print the lanes a project routes onto, with their effective settings."""
    parser = argparse.ArgumentParser(
        prog="yoke projects lane-summary get",
        description=(
            "Read one project's effective session lane routing: each lane's "
            "label and glyph, the harness/model selectors that route to it, "
            "the actions it may run, and the harnesses that default to it. "
            "This is the same composition the Project settings screen shows. "
            "Edit any of it with `yoke projects capability-settings merge "
            "--project NAME --cap-type session-routing --set KEY.PATH=VALUE`."
        ),
    )
    parser.add_argument("--project", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed: Any = parse_or_usage_error(
        parser, args, PROJECTS_LANE_SUMMARY_GET_USAGE
    )
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="projects.lane_summary.get",
        target=TargetRef(kind="global"),
        payload={"project": parsed.project},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_summary,
    )


USAGE_BY_FUNCTION_ID = {
    "projects.lane_summary.get": PROJECTS_LANE_SUMMARY_GET_USAGE,
}


__all__ = [
    "PROJECTS_LANE_SUMMARY_GET_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "projects_lane_summary_get",
]
