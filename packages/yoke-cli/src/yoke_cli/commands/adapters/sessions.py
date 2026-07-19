"""``yoke sessions ...`` and ``yoke charge schedule`` adapters."""

from __future__ import annotations

import argparse
import subprocess
import sys
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


SESSIONS_TOUCH_USAGE = (
    "yoke sessions touch [--mode MODE] [--session-id S] [--json]"
)
SESSIONS_INIT_USAGE = "yoke sessions init"
SESSIONS_CHECKPOINT_USAGE = (
    "yoke sessions checkpoint --step N --action ACTION --chainable BOOL "
    "[--item-id I] [--task-num N] [--outcome O] [--status S] "
    "[--required-path P] [--pre-status PS] [--session-id S] [--json]"
)
SESSIONS_CHECKPOINT_READ_USAGE = (
    "yoke sessions checkpoint-read [--session-id S] [--json]"
)
SESSIONS_BEGIN_USAGE = (
    "yoke sessions begin --executor E --provider P --model M --workspace W "
    "[--project ID] [--mode MODE] [--entrypoint E] [--session-id S] [--json]"
)
SESSIONS_OFFER_USAGE = (
    "yoke sessions offer --executor E --provider P --workspace W "
    "[--model M] [--lane L] [--step N] [--supported-paths P] "
    "[--project IDS] [--session-id S] [--json]"
)
SESSIONS_OWNERSHIP_GUARD_USAGE = (
    "yoke sessions ownership-guard --item PREFIX-N [--session-id S] [--json]"
)
CHARGE_SCHEDULE_USAGE = (
    "yoke charge schedule [--project P] [--wip-cap N] "
    "[--session-id S] [--json]"
)


def _chainable(raw: str) -> bool:
    return str(raw).strip().lower() in ("true", "1", "yes")


def sessions_init(args: List[str]) -> int:
    """Run session bootstrap with the interpreter that owns ``yoke``.

    The bootstrap helper spans CLI, core, and harness packages. Invoking it
    through an ambient ``python3`` is unreliable for packaged installs, while
    this wrapper guarantees the sibling runtime packages are importable.
    """
    parser = argparse.ArgumentParser(
        prog="yoke sessions init", description=SESSIONS_INIT_USAGE,
    )
    parsed = parse_or_usage_error(parser, args, SESSIONS_INIT_USAGE)
    if parsed is None:
        return 2
    completed = subprocess.run(
        [sys.executable, "-m", "yoke_core.tools.session_init"],
        check=False,
    )
    return int(completed.returncode)


def sessions_touch(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions touch", description=SESSIONS_TOUCH_USAGE,
    )
    parser.add_argument("--mode", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_TOUCH_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.mode is not None:
        payload["mode"] = parsed.mode
    return dispatch_and_emit(
        function_id="sessions.touch",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def sessions_checkpoint(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions checkpoint",
        description=SESSIONS_CHECKPOINT_USAGE,
    )
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--chainable", required=True)
    parser.add_argument("--item-id", default=None)
    parser.add_argument("--task-num", type=int, default=None)
    parser.add_argument("--outcome", default="completed")
    parser.add_argument("--status", default=None)
    parser.add_argument("--required-path", default=None)
    parser.add_argument("--pre-status", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_CHECKPOINT_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "step": parsed.step,
        "action": parsed.action,
        "chainable": _chainable(parsed.chainable),
        "outcome": parsed.outcome,
    }
    for key in ("item_id", "task_num", "status", "required_path", "pre_status"):
        value = getattr(parsed, key)
        if value is not None:
            payload[key] = value
    return dispatch_and_emit(
        function_id="sessions.checkpoint",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def sessions_checkpoint_read(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions checkpoint-read",
        description=SESSIONS_CHECKPOINT_READ_USAGE,
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_CHECKPOINT_READ_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="sessions.checkpoint_read",
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def _resolve_begin_project_id(explicit: str | None, workspace: str):
    """Resolve the numeric project id client-side — never a server round-trip.

    Mirrors the checkout->project resolution the operator-debug
    ``session-begin`` path uses, but on the CLIENT so the resolved id
    ships in the dispatch envelope. This keeps the transport-keyed begin
    correct over https: the remote server never sees the caller's checkout
    map, so project identity is resolved here and passed as ``project_id``.
    Returns ``None`` when neither an explicit positive-int project nor a
    mapped checkout resolves.
    """
    if explicit:
        try:
            pid = int(explicit)
        except (TypeError, ValueError):
            return None
        return pid if pid > 0 else None
    try:
        from pathlib import Path

        from yoke_cli.config import machine_config

        return machine_config.project_id(Path(workspace))
    except Exception:
        return None


def sessions_begin(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions begin", description=SESSIONS_BEGIN_USAGE,
    )
    parser.add_argument("--executor", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument(
        "--project", metavar="ID", default=None,
        help="numeric project id; otherwise resolve the workspace mapping",
    )
    parser.add_argument("--mode", default="wait")
    parser.add_argument("--entrypoint", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_BEGIN_USAGE)
    if parsed is None:
        return 2
    project_id = _resolve_begin_project_id(parsed.project, parsed.workspace)
    if project_id is None:
        return usage_error(
            "Session registration requires a project id. Run Yoke setup for "
            "this checkout or pass --project."
        )
    payload: Dict[str, Any] = {
        "executor": parsed.executor,
        "provider": parsed.provider,
        "model": parsed.model,
        "workspace": parsed.workspace,
        "project_id": project_id,
        "mode": parsed.mode,
    }
    if parsed.entrypoint is not None:
        payload["entrypoint"] = parsed.entrypoint
    return dispatch_and_emit(
        function_id="sessions.begin",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def sessions_offer(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions offer", description=SESSIONS_OFFER_USAGE,
    )
    parser.add_argument("--executor", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--lane", default=None)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument("--supported-paths", default=None)
    parser.add_argument("--project", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_OFFER_USAGE)
    if parsed is None:
        return 2
    supported_paths = [
        p.strip() for p in (parsed.supported_paths or "").split(",") if p.strip()
    ]
    payload: Dict[str, Any] = {
        "executor": parsed.executor,
        "provider": parsed.provider,
        "workspace": parsed.workspace,
        "step": parsed.step,
        "supported_paths": supported_paths,
    }
    for key in ("model", "lane", "project"):
        value = getattr(parsed, key)
        if value is not None:
            payload[key] = value
    return dispatch_and_emit(
        function_id="sessions.offer",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def sessions_ownership_guard(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions ownership-guard",
        description=SESSIONS_OWNERSHIP_GUARD_USAGE,
    )
    parser.add_argument("--item", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_OWNERSHIP_GUARD_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="sessions.ownership_guard",
        target=item_target("item", parsed.item, parsed.project),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def charge_schedule(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke charge schedule", description=CHARGE_SCHEDULE_USAGE,
    )
    parser.add_argument("--project", default=None)
    parser.add_argument("--wip-cap", type=int, default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, CHARGE_SCHEDULE_USAGE)
    if parsed is None:
        return 2
    if parsed.wip_cap is not None and not 1 <= parsed.wip_cap <= 100:
        return usage_error("--wip-cap must be between 1 and 100")
    payload: Dict[str, Any] = {}
    if parsed.project is not None:
        payload["project"] = parsed.project
    if parsed.wip_cap is not None:
        payload["wip_cap"] = parsed.wip_cap
    return dispatch_and_emit(
        function_id="charge.schedule",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "sessions_begin", "sessions_touch", "sessions_checkpoint",
    "sessions_checkpoint_read",
    "sessions_offer", "sessions_ownership_guard", "charge_schedule",
    "SESSIONS_BEGIN_USAGE", "SESSIONS_TOUCH_USAGE", "SESSIONS_CHECKPOINT_USAGE",
    "SESSIONS_CHECKPOINT_READ_USAGE", "SESSIONS_OFFER_USAGE",
    "SESSIONS_OWNERSHIP_GUARD_USAGE", "CHARGE_SCHEDULE_USAGE",
]
