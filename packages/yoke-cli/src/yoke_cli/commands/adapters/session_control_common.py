"""Shared parsing and rendering for fleet session-control commands."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Iterable, TextIO


SELECTOR_ARGUMENTS = (
    ("session_ids", "--session"),
    ("item_refs", "--item"),
    ("epic_tasks", "--epic-task"),
    ("process_keys", "--process"),
    ("projects", "--project"),
    ("executor_families", "--executor"),
    ("executor_surfaces", "--surface"),
    ("work_roles", "--role"),
    ("execution_lanes", "--execution-lane"),
    ("worktree_lanes", "--worktree"),
    ("machine_ids", "--machine"),
    ("liveness", "--liveness"),
    ("exclude_session_ids", "--exclude-session"),
)


def add_selector_arguments(parser: argparse.ArgumentParser) -> None:
    """Add union anchors followed by intersecting recipient filters."""
    anchor_help = {
        "session_ids": "Exact top-level Yoke session id (repeatable).",
        "item_refs": "Item whose current holder is a recipient (repeatable).",
        "epic_tasks": "Epic task as QUALIFIED-ITEM:TASK (repeatable).",
        "process_keys": "Claimed process key (repeatable).",
        "projects": "Project slug or id (repeatable).",
    }
    for dest, flag in SELECTOR_ARGUMENTS:
        parser.add_argument(
            flag,
            dest=dest,
            action="append",
            default=[],
            help=anchor_help.get(dest, "Recipient filter (repeatable)."),
        )
    parser.add_argument(
        "--universe",
        action="store_true",
        help="Select every visible session; exact preview confirmation may apply.",
    )


def selector_payload(parsed: argparse.Namespace) -> dict[str, Any]:
    selector = {
        dest: list(getattr(parsed, dest))
        for dest, _flag in SELECTOR_ARGUMENTS
        if getattr(parsed, dest)
    }
    if parsed.universe:
        selector["universe"] = True
    return selector


def read_stdin_payload(parsed: argparse.Namespace) -> str | None:
    """Read sensitive text only from stdin, never from the process arguments."""
    if not parsed.stdin:
        return None
    value = sys.stdin.read()
    return value if value.strip() else None


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def write_recipient_rows(
    recipients: Iterable[dict[str, Any]],
    stdout: TextIO,
) -> None:
    for recipient in recipients:
        print(
            "recipient|"
            + "|".join(
                str(recipient.get(field) or "")
                for field in (
                    "session_id",
                    "project",
                    "executor",
                    "executor_surface",
                    "machine_id",
                    "liveness",
                )
            )
            + "|"
            + compact_json(recipient.get("messageability") or {}),
            file=stdout,
        )


def write_message_result(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    result = response.result or {}
    if "recipients" in result:
        identity = result.get("message_id") or "preview"
        print(
            f"message|{identity}|{result.get('recipient_count', 0)}|"
            f"{str(bool(result.get('deduplicated'))).lower()}",
            file=stdout,
        )
        token = result.get("confirmation_token")
        if token:
            print(f"confirmation|{token}", file=stdout)
        write_recipient_rows(result.get("recipients") or [], stdout)
        return
    if "messages" in result:
        for message in result.get("messages") or []:
            print(compact_json(message), file=stdout)
        return
    print(compact_json(result.get("message", result)), file=stdout)


def write_launch_result(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    result = response.result or {}
    if "launches" in result:
        for launch in result.get("launches") or []:
            print(compact_json(launch), file=stdout)
        return
    print(compact_json(result), file=stdout)


__all__ = [
    "add_selector_arguments",
    "compact_json",
    "read_stdin_payload",
    "selector_payload",
    "write_launch_result",
    "write_message_result",
    "write_recipient_rows",
]
