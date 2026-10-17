"""``yoke settings get|set|unset levels`` and ``yoke universe level-capacity get``."""

from __future__ import annotations

import argparse
from typing import Any, List, Mapping, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef, FunctionError

CAPACITY_FUNCTION_ID = "universe.level_capacity.get"
CAPACITY_USAGE = "yoke universe level-capacity get [--session-id S] [--json]"

_SOURCE_LINES = {
    "default": "source: shipped default (no universe levels stored)",
    "universe": "source: universe",
    "project": "source: project override",
}


def _option_line(option: Mapping[str, Any]) -> str:
    return f"{option.get('model')}  min_effort={option.get('min_effort')}"


def write_levels(result: Mapping[str, Any], stdout: TextIO) -> None:
    """Print a levels read: its source, then each level lowest first."""
    source = str(result.get("source") or "")
    stdout.write(_SOURCE_LINES.get(source, f"source: {source or 'unknown'}") + "\n")
    if "cleared" in result:
        stdout.write(
            "cleared the stored universe levels; the universe now follows "
            "shipped defaults\n"
            if result["cleared"]
            else "no universe levels were stored; the universe already "
            "follows shipped defaults\n"
        )
    differ = result.get("shipped_defaults_differ")
    if source == "universe" and differ is not None:
        stdout.write(
            "shipped defaults differ from these stored levels; the universe "
            "does not follow them. Follow them with `yoke settings unset levels`.\n"
            if differ
            else "these stored levels equal today's shipped defaults but will "
            "not follow future ones; `yoke settings unset levels` follows them.\n"
        )
    for level in result.get("levels") or []:
        stdout.write(f"{level.get('glyph') or ' '} {level.get('name')}\n")
        for option in level.get("options") or []:
            stdout.write(f"  {_option_line(option)}\n")


def _write(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    if response.success:
        write_levels(response.result or {}, stdout)


def _require_min_effort_response(response, _actor):
    missing = response.success and any(
        "min_effort" not in row
        for level in (response.result or {}).get("levels", [])
        for row in level.get("options", [])
    )
    old_schema = (
        response.error and response.error.code == "level_option_surface_unsupported"
    )
    if missing or old_schema:
        return response.model_copy(
            update={
                "success": False,
                "result": {},
                "error": FunctionError(
                    code="levels_schema_version_skew",
                    message="This serving build predates model/min_effort Levels (required floor: next-release). Recovery: ask the control-plane operator to serve the release carrying this contract; keep the existing stored Levels until its boot convergence completes.",
                ),
            }
        )
    return response


def write_capacity(result: Mapping[str, Any], stdout: TextIO) -> None:
    """Print model thresholds and observed native launch standing."""
    for level in result.get("levels") or []:
        stdout.write(f"{level.get('glyph') or ' '} {level.get('name')}\n")
        stdout.write(
            "  Launchable on: "
            + ", ".join(level.get("launchable_surfaces") or [])
            + "\n"
        )
        for index, entry in enumerate(level.get("options") or [], start=1):
            now = entry.get("now") or {}
            state = (
                "can launch"
                if now.get("state") == "can_launch"
                else "blocked: "
                + "; ".join(
                    str(blocker.get("label") or "")
                    for blocker in now.get("blockers") or []
                )
            )
            stdout.write(f"  {index}. {_option_line(entry)} [{state}]\n")
    stdout.write(
        "Cursor quota order: "
        + " -> ".join(result.get("cursor_quota_order") or [])
        + "\n"
    )


def _write_capacity(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    if response.success:
        write_capacity(response.result or {}, stdout)


def universe_levels_capacity(args: List[str]) -> int:
    """Print what each universe level can launch right now, and why."""
    parser = argparse.ArgumentParser(
        prog="yoke universe level-capacity get",
        description=(
            "Read each universe level's launch standing: per model row the "
            "native surfaces it can launch on, or the quota/native listing "
            "rule blocking it, plus the universe-wide Cursor monthly order."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CAPACITY_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id=CAPACITY_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_capacity,
        response_recovery=_require_min_effort_response,
    )


USAGE_BY_FUNCTION_ID = {
    CAPACITY_FUNCTION_ID: CAPACITY_USAGE,
}


__all__ = [
    "USAGE_BY_FUNCTION_ID",
    "universe_levels_capacity",
    "write_capacity",
    "write_levels",
]
