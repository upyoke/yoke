"""CLI adapters for steerer-managed surface disable marks."""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from typing import Any, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.session_control_human_output import (
    Column,
    utc_time,
    write_summary,
    write_table,
)
from yoke_contracts.api.function_call import TargetRef


SURFACE_POLICY_DISABLE_USAGE = (
    "yoke session-control surface-policy disable --project P --machine M "
    "--surface S --reason TEXT [--evidence TEXT] [--json]"
)
SURFACE_POLICY_ENABLE_USAGE = (
    "yoke session-control surface-policy enable --project P --machine M "
    "--surface S [--json]"
)
SURFACE_POLICY_LIST_USAGE = (
    "yoke session-control surface-policy list [--machine M] [--surface S] "
    "[--include-cleared] [--json]"
)


def _write_mark(response: Any, stdout: TextIO, _stderr: TextIO) -> None:
    result = response.result or {}
    mark = result.get("mark") if isinstance(result.get("mark"), Mapping) else {}
    write_summary(
        "SURFACE POLICY",
        [
            ("Mark ID", mark.get("mark_id")),
            ("Machine", mark.get("machine_id")),
            ("Surface", mark.get("surface")),
            ("State", mark.get("state")),
            ("Reason", mark.get("reason")),
            ("Set by actor", mark.get("set_by_actor_id")),
            ("Created (UTC)", utc_time(mark.get("created_at"))),
            ("Cleared (UTC)", utc_time(mark.get("cleared_at"))),
        ],
        stdout,
    )


def _write_list(response: Any, stdout: TextIO, _stderr: TextIO) -> None:
    result = response.result or {}
    columns: tuple[Column, ...] = (
        ("MACHINE", lambda row: row.get("machine_id"), None),
        ("SURFACE", lambda row: row.get("surface"), 16),
        ("REASON", lambda row: row.get("reason"), 28),
        ("CREATED (UTC)", lambda row: utc_time(row.get("created_at")), 22),
        ("CLEARED (UTC)", lambda row: utc_time(row.get("cleared_at")), 22),
    )
    write_table(
        "SURFACE POLICY MARKS",
        columns,
        result.get("marks") or [],
        stdout,
        empty="No live surface disable marks.",
    )


def session_surface_policy_disable(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke session-control surface-policy disable",
        description=SURFACE_POLICY_DISABLE_USAGE,
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--machine", dest="machine_id", required=True)
    parser.add_argument("--surface", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--evidence", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SURFACE_POLICY_DISABLE_USAGE)
    if parsed is None:
        return 2
    payload: dict[str, Any] = {
        "project": parsed.project,
        "machine_id": parsed.machine_id,
        "surface": parsed.surface,
        "reason": parsed.reason,
    }
    if parsed.evidence is not None:
        payload["evidence"] = parsed.evidence
    return dispatch_and_emit(
        function_id="session_control.surface_policy.set",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_mark,
    )


def session_surface_policy_enable(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke session-control surface-policy enable",
        description=SURFACE_POLICY_ENABLE_USAGE,
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--machine", dest="machine_id", required=True)
    parser.add_argument("--surface", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SURFACE_POLICY_ENABLE_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="session_control.surface_policy.clear",
        target=TargetRef(kind="global"),
        payload={
            "project": parsed.project,
            "machine_id": parsed.machine_id,
            "surface": parsed.surface,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_mark,
    )


def session_surface_policy_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke session-control surface-policy list",
        description=SURFACE_POLICY_LIST_USAGE,
    )
    parser.add_argument("--machine", dest="machine_id", default=None)
    parser.add_argument("--surface", default=None)
    parser.add_argument("--include-cleared", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SURFACE_POLICY_LIST_USAGE)
    if parsed is None:
        return 2
    payload: dict[str, Any] = {"include_cleared": bool(parsed.include_cleared)}
    if parsed.machine_id:
        payload["machine_id"] = parsed.machine_id
    if parsed.surface:
        payload["surface"] = parsed.surface
    return dispatch_and_emit(
        function_id="session_control.surface_policy.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_list,
    )


__all__ = [
    "SURFACE_POLICY_DISABLE_USAGE",
    "SURFACE_POLICY_ENABLE_USAGE",
    "SURFACE_POLICY_LIST_USAGE",
    "session_surface_policy_disable",
    "session_surface_policy_enable",
    "session_surface_policy_list",
]
