"""``yoke universe levels get|set`` — the universe execution levels."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, List, Mapping, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef

GET_FUNCTION_ID = "universe.levels.get"
SET_FUNCTION_ID = "universe.levels.set"
GET_USAGE = "yoke universe levels get [--session-id S] [--json]"
SET_USAGE = "yoke universe levels set --stdin [--session-id S] [--json]"

_SOURCE_LINES = {
    "default": "source: shipped default (no universe levels stored)",
    "universe": "source: universe",
    "project": "source: project override",
}


def _option_line(option: Mapping[str, Any]) -> str:
    context = option.get("context_window_tokens")
    line = (
        f"{option.get('surface')}  {option.get('model')}  "
        f"effort={option.get('reasoning_effort')}  "
        f"context={context if context else 'default'}"
    )
    fallback = option.get("fallback")
    if isinstance(fallback, Mapping):
        line += f"  (exhausted -> {_option_line(fallback)})"
    return line


def write_levels(result: Mapping[str, Any], stdout: TextIO) -> None:
    """Print a levels read: its source, then each level lowest first."""
    source = str(result.get("source") or "")
    stdout.write(_SOURCE_LINES.get(source, f"source: {source or 'unknown'}") + "\n")
    for level in result.get("levels") or []:
        stdout.write(f"{level.get('glyph') or ' '} {level.get('name')}\n")
        for option in level.get("options") or []:
            stdout.write(f"  {_option_line(option)}\n")


def _write(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    if response.success:
        write_levels(response.result or {}, stdout)


def universe_levels_get(args: List[str]) -> int:
    """Print the universe levels every project without an override reads."""
    parser = argparse.ArgumentParser(
        prog="yoke universe levels get",
        description=(
            "Read the universe execution levels, lowest first: each level's "
            "glyph and its ordered launchable options. Projects read these "
            "unless their session-routing capability carries a levels "
            "override (`yoke projects level-summary get --project P`)."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GET_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id=GET_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write,
    )


def universe_levels_set(args: List[str]) -> int:
    """Store the universe levels from a JSON list on stdin."""
    parser = argparse.ArgumentParser(
        prog="yoke universe levels set",
        description=(
            "Replace the universe execution levels with the JSON list on "
            "stdin, lowest level first. Each level is "
            '{"name", "glyph", "options": [...]}; each option is '
            '{"surface", "model", "reasoning_effort", '
            '"context_window_tokens"} plus an optional same-surface '
            '"fallback". Start from `yoke universe levels get --json`. '
            "Org admin required."
        ),
    )
    parser.add_argument("--stdin", action="store_true", help="Read the levels JSON.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SET_USAGE)
    if parsed is None:
        return 2
    if not parsed.stdin:
        return usage_error("universe levels set requires --stdin")
    try:
        levels = json.loads(sys.stdin.read())
    except json.JSONDecodeError as exc:
        return usage_error(f"levels stdin is not JSON: {exc}")
    if isinstance(levels, dict) and isinstance(levels.get("levels"), list):
        levels = levels["levels"]
    if not isinstance(levels, list):
        return usage_error(
            "levels stdin must be a JSON list of levels (or the object "
            "`yoke universe levels get --json` returns)"
        )
    return dispatch_and_emit(
        function_id=SET_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={"levels": levels},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write,
    )


USAGE_BY_FUNCTION_ID = {GET_FUNCTION_ID: GET_USAGE, SET_FUNCTION_ID: SET_USAGE}


__all__ = [
    "USAGE_BY_FUNCTION_ID",
    "universe_levels_get",
    "universe_levels_set",
    "write_levels",
]
