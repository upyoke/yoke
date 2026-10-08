"""``yoke models level-proposal`` — propose level changes from the catalog."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef

LEVEL_PROPOSAL_FUNCTION_ID = "models.level_proposal.run"
LEVEL_PROPOSAL_USAGE = "yoke models level-proposal [--stdin] [--levels-only] [--json]"


def _option_text(option: Dict[str, Any]) -> str:
    context = option.get("context_window_tokens") or "default"
    return (
        f"{option.get('surface')} {option.get('model')} "
        f"effort={option.get('reasoning_effort')} context={context}"
    )


def _change_line(change: Dict[str, Any]) -> str:
    kind = change.get("kind")
    option = change.get("option") or {}
    if kind == "add":
        where = f"to {change.get('level')}"
        if change.get("position") is not None:
            where += f" at {change['position']}"
        head = f"add {_option_text(option)} {where}"
    elif kind == "move":
        head = f"move {_option_text(option)} to {change.get('to_level')}"
    elif kind == "retire":
        head = f"retire {_option_text(option)}"
    else:
        updates = ", ".join(
            f"{key}={change[key]}"
            for key in ("reasoning_effort", "context_window_tokens")
            if key in change
        )
        head = f"change {_option_text(option)} -> {updates}"
    return f"  {head}  ({change.get('reason') or 'no reason given'})"


def _print_level_proposal(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    if not response.success:
        error = response.error
        print(error.message if error else "level proposal failed", file=stderr)
        return
    result = response.result or {}
    source = "generated from the catalog" if result.get("generated") else "authored"
    changes = result.get("changes") or []
    print(
        f"catalog {result.get('revision_id')}; base levels: "
        f"{result.get('base_source')}; {len(changes)} change(s), {source}",
        file=stdout,
    )
    for change in changes:
        print(_change_line(change), file=stdout)
    for entry in result.get("unverified") or []:
        print(
            f"unverified: {entry.get('level')} {entry.get('surface')} "
            f"{entry.get('model')} — {entry.get('reason')}",
            file=stdout,
        )
    for entry in result.get("unplaced_models") or []:
        print(
            f"unplaced: {entry.get('model_id')} ({entry.get('provider')}) — "
            "no level launches it; add it with an authored change if it belongs",
            file=stdout,
        )
    print(
        "Approve: `yoke models level-proposal --levels-only [--stdin < "
        f"changes.json] > levels.json`, then `{result.get('apply_command')} < "
        "levels.json`.",
        file=stdout,
    )


def _print_levels_only(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    if not response.success:
        error = response.error
        print(error.message if error else "level proposal failed", file=stderr)
        return
    levels = (response.result or {}).get("levels") or []
    print(json.dumps({"levels": levels}, ensure_ascii=False, indent=2), file=stdout)


def models_level_proposal(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke models level-proposal",
        description=(
            "Propose universe level changes from the current model catalog. "
            "Without --stdin, changes are extrapolated: an option whose model "
            "the catalog supersedes is replaced in place by its successor, and "
            "an effort or context window the model does not publish moves to "
            "the nearest published effort or the default window. With --stdin, "
            "read a JSON list of authored changes instead, each "
            '{"kind": "add", "level", "option", "position"?} | '
            '{"kind": "move", "option", "to_level"} | '
            '{"kind": "retire", "option"} | '
            '{"kind": "change", "option", "reasoning_effort"?, '
            '"context_window_tokens"?}, plus "reason"; an option is addressed '
            "by surface, model, and reasoning_effort. Options whose effort or "
            "context contradicts the model's published values are refused. "
            "Nothing is stored: after operator approval, pipe --levels-only "
            "output to `yoke universe levels set --stdin`."
        ),
    )
    parser.add_argument(
        "--stdin", action="store_true", help="Read a JSON list of authored changes."
    )
    parser.add_argument(
        "--levels-only",
        action="store_true",
        help="Print only the proposed levels document, the approval input.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, LEVEL_PROPOSAL_USAGE)
    if parsed is None:
        return 2
    if parsed.levels_only and parsed.json_mode:
        return usage_error("choose --levels-only or --json, not both")
    payload: Dict[str, Any] = {}
    if parsed.stdin:
        try:
            changes = json.loads(sys.stdin.read())
        except json.JSONDecodeError as exc:
            return usage_error(f"level changes stdin is not JSON: {exc}")
        if not isinstance(changes, list) or not all(
            isinstance(change, dict) for change in changes
        ):
            return usage_error("level changes stdin must be a JSON list of objects")
        payload["changes"] = changes
    return dispatch_and_emit(
        function_id=LEVEL_PROPOSAL_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=(
            None
            if parsed.json_mode
            else _print_levels_only
            if parsed.levels_only
            else _print_level_proposal
        ),
    )


USAGE_BY_FUNCTION_ID = {LEVEL_PROPOSAL_FUNCTION_ID: LEVEL_PROPOSAL_USAGE}

__all__ = [
    "LEVEL_PROPOSAL_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "models_level_proposal",
]
