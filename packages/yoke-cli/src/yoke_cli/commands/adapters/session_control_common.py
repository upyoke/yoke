"""Shared parsing and rendering for fleet session-control commands."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, TextIO

from yoke_contracts.session_control.liveness import LIVENESS_CHOICES

from yoke_cli.commands.adapters.session_control_human_output import (
    write_message_result as write_human_message_result,
)
from yoke_cli.commands.adapters.session_control_launch_output import (
    write_launch_result as write_human_launch_result,
)


#: Union anchors first, in the order a reader should reach for them: the
#: work addresses its own holder, so --item leads and --session is the
#: fallback for a recipient no claim names.
SELECTOR_ARGUMENTS = (
    ("public_refs", "--item"),
    ("actors", "--actor"),
    ("epic_tasks", "--epic-task"),
    ("process_keys", "--process"),
    ("projects", "--project"),
    ("session_ids", "--session"),
    ("executor_families", "--executor"),
    ("executor_surfaces", "--surface"),
    ("work_roles", "--role"),
    ("execution_lanes", "--execution-lane"),
    ("worktree_lanes", "--worktree"),
    ("machine_ids", "--machine"),
    ("liveness", "--liveness"),
    ("exclude_session_ids", "--exclude-session"),
)


#: The shape --steering-scope names, quoted for a shell.
STEERING_SCOPE_EXAMPLE = '\'{"project_id": 1}\''


def steering_scope_argument(raw: str) -> dict[str, Any]:
    """Decode --steering-scope, naming the shape it must have when it is not."""
    try:
        scope = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(
            f"--steering-scope must be a JSON object such as "
            f"{STEERING_SCOPE_EXAMPLE}; {exc}"
        ) from exc
    if not isinstance(scope, dict):
        raise argparse.ArgumentTypeError(
            "--steering-scope must be a JSON object such as "
            f"{STEERING_SCOPE_EXAMPLE}"
        )
    return scope


def add_selector_arguments(parser: argparse.ArgumentParser) -> None:
    """Add union anchors followed by intersecting recipient filters."""
    anchor_help = {
        "actors": (
            "ANCHOR (union). Human organization member by exact actor id or "
            "registered resolution label (repeatable)."
        ),
        "public_refs": (
            "ANCHOR (union). Item whose current holder is a recipient "
            "(repeatable). The address to prefer: one live claim, one "
            "holder, no id to copy."
        ),
        "epic_tasks": "ANCHOR (union). Epic task as QUALIFIED-ITEM:TASK.",
        "process_keys": "ANCHOR (union). Claimed process key (repeatable).",
        "projects": (
            "ANCHOR (union). Every session in the project — this WIDENS the "
            "audience, it does not narrow another anchor."
        ),
        "session_ids": (
            "ANCHOR (union). Exact whole top-level Yoke session id "
            "(repeatable). For a recipient no claim addresses; prefixes "
            "collide, so never assemble, pad, or complete one."
        ),
    }
    filter_help = {
        "executor_families": "FILTER. Keep recipients from this executor family.",
        "executor_surfaces": "FILTER. Keep recipients on this exact surface (repeatable).",
        "work_roles": "FILTER. Keep recipients with this work role (repeatable).",
        "execution_lanes": "FILTER. Keep recipients in this execution lane (repeatable).",
        "worktree_lanes": "FILTER. Keep recipients on this worktree or branch (repeatable).",
        "machine_ids": "FILTER. Keep recipients on this machine (repeatable).",
        "liveness": (
            "FILTER. Keep recipients in this liveness state (repeatable). "
            "--project and --universe resolve against active sessions "
            "unless this widens them; 'all' restores every state."
        ),
        "exclude_session_ids": "FILTER. Remove this exact session from the result (repeatable).",
    }
    for dest, flag in SELECTOR_ARGUMENTS:
        parser.add_argument(
            flag,
            dest=dest,
            action="append",
            default=[],
            choices=LIVENESS_CHOICES if dest == "liveness" else None,
            help=anchor_help.get(dest) or filter_help[dest],
        )
    parser.add_argument(
        "--universe",
        action="store_true",
        help=(
            "ANCHOR (union). Every visible session; exact preview "
            "confirmation may apply."
        ),
    )
    parser.add_argument(
        "--steering",
        action="store_true",
        help=(
            "ANCHOR (union). The steering ROLE covering the work you hold — "
            "no argument, no session id. Resolves at delivery to whichever "
            "seat covers your item's scope, and parks for the next seat when "
            "none is live."
        ),
    )
    parser.add_argument(
        "--steering-scope",
        dest="steering_scope",
        type=steering_scope_argument,
        default=None,
        help=(
            "ANCHOR (union). The steering scope to address when you hold no "
            'item, as JSON: \'{"project_id": N}\'. Implies --steering.'
        ),
    )


def selector_payload(parsed: argparse.Namespace) -> dict[str, Any]:
    selector = {
        dest: list(getattr(parsed, dest))
        for dest, _flag in SELECTOR_ARGUMENTS
        if getattr(parsed, dest)
    }
    if parsed.universe:
        selector["universe"] = True
    if getattr(parsed, "steering", False):
        selector["steering"] = True
    raw_scope = getattr(parsed, "steering_scope", None)
    if raw_scope:
        selector["steering_scope"] = raw_scope
    return selector


def read_stdin_payload(parsed: argparse.Namespace) -> str | None:
    """Read sensitive text only from stdin, never from the process arguments."""
    if not parsed.stdin:
        return None
    value = sys.stdin.read()
    return value if value.strip() else None


def write_message_result(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    write_human_message_result(response.result or {}, stdout)


def write_launch_result(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    write_human_launch_result(response.result or {}, stdout)


__all__ = [
    "STEERING_SCOPE_EXAMPLE",
    "add_selector_arguments",
    "read_stdin_payload",
    "selector_payload",
    "steering_scope_argument",
    "write_launch_result",
    "write_message_result",
]
