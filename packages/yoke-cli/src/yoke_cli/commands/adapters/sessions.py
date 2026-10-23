"""``yoke sessions ...`` and ``yoke charge schedule`` adapters."""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.session_begin_corroboration import (
    uncorroborated_reason,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_queue_posture import SESSION_MODES


SESSIONS_TOUCH_USAGE = (
    "yoke sessions touch [--mode MODE] [--reason TEXT] [--session-id S] [--json]"
)
SESSIONS_IDENTITY_USAGE = "yoke sessions identity [--full] [--session-id S] [--json]"
SESSIONS_CHECKPOINT_USAGE = (
    "yoke sessions checkpoint --step N --action ACTION --chainable BOOL "
    "[--item PREFIX-N] [--task-num N] [--outcome O] [--status S] "
    "[--required-path P] [--pre-status PS] [--failure-class C] "
    "[--session-id S] [--json]"
)
SESSIONS_CHECKPOINT_READ_USAGE = (
    "yoke sessions checkpoint-read [--full] [--session-id S] [--json]"
)
SESSIONS_BEGIN_USAGE = (
    "yoke sessions begin --executor E --provider P --requested-model M --workspace W "
    "[--project ID] [--mode MODE] [--entrypoint E] [--session-id S] [--json]"
)
CHARGE_SCHEDULE_USAGE = (
    "yoke charge schedule [--project P] [--item PREFIX-N] "
    "[--workspace W] [--wip-cap N] [--session-id S] [--json]"
)


def _chainable(raw: str) -> bool:
    return str(raw).strip().lower() in ("true", "1", "yes")


def sessions_identity(args: List[str]) -> int:
    """Read the calling session's resolved identity back from the authority.

    Every value comes from the session row registration already resolved —
    canonical executor and display alias, provider, model, execution level and
    the paths that lane may execute, workspace, project, actor — plus the
    chain budget. Nothing is detected locally, so no field is advisory.
    """
    parser = argparse.ArgumentParser(
        prog="yoke sessions identity",
        usage=SESSIONS_IDENTITY_USAGE,
        description=(
            "Show this session as the server recorded it: executor, provider,\n"
            "model, execution level, workspace, project, actor and chain budget."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_IDENTITY_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="sessions.identity",
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def sessions_touch(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke sessions touch",
        usage=SESSIONS_TOUCH_USAGE,
    )
    parser.add_argument("--mode", choices=sorted(SESSION_MODES), metavar="MODE", help=f"Mode to set: {', '.join(sorted(SESSION_MODES))}.")
    parser.add_argument("--reason", metavar="TEXT", help="Why the session is in this mode.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_TOUCH_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.mode is not None:
        payload["mode"] = parsed.mode
    if parsed.reason is not None:
        payload["reason"] = parsed.reason
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
        usage=SESSIONS_CHECKPOINT_USAGE,
    )
    parser.add_argument("--step", type=int, required=True, metavar="N", help="Chain step number.")
    parser.add_argument("--action", required=True, metavar="ACTION", help="Action the step ran.")
    parser.add_argument(
        "--chainable", required=True, metavar="BOOL", help="true if the chain may continue."
    )
    parser.add_argument(
        "--item",
        dest="public_ref",
        default=None,
        metavar="PREFIX-N",
        help="The item the step worked on.",
    )
    parser.add_argument("--task-num", type=int, metavar="N", help="Task number the step worked on.")
    parser.add_argument(
        "--outcome", default="completed", metavar="O", help="Step outcome; default: completed."
    )
    parser.add_argument("--status", metavar="S", help="Item status after the step.")
    parser.add_argument("--required-path", metavar="P", help="Path the next step requires.")
    parser.add_argument("--pre-status", metavar="PS", help="Item status before the step.")
    parser.add_argument("--failure-class", metavar="C", help="Failure class when the step failed.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_CHECKPOINT_USAGE)
    if parsed is None:
        return 2
    if parsed.public_ref is not None:
        parsed.public_ref = item_target("item", parsed.public_ref).public_ref
    payload: Dict[str, Any] = {
        "step": parsed.step,
        "action": parsed.action,
        "chainable": _chainable(parsed.chainable),
        "outcome": parsed.outcome,
    }
    for key in (
        "public_ref",
        "task_num",
        "status",
        "required_path",
        "pre_status",
        "failure_class",
    ):
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
        usage=SESSIONS_CHECKPOINT_READ_USAGE,
        description="Show the last step this session recorded with yoke sessions checkpoint.",
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
        prog="yoke sessions begin",
        usage=SESSIONS_BEGIN_USAGE,
    )
    parser.add_argument("--executor", required=True, metavar="E", help="Harness running it.")
    parser.add_argument("--provider", required=True, metavar="P", help="Model provider.")
    parser.add_argument("--requested-model", required=True, metavar="M", help="Model asked for.")
    parser.add_argument("--workspace", required=True, metavar="W", help="Checkout path to work in.")
    parser.add_argument(
        "--project",
        metavar="ID",
        default=None,
        help="Numeric project id; default: the project mapped to the workspace.",
    )
    modes = sorted(SESSION_MODES)
    parser.add_argument(
        "--mode", default="wait", choices=modes, metavar="MODE",
        help=f"Start mode; default: wait. One of: {', '.join(modes)}.",
    )
    parser.add_argument(
        "--entrypoint", metavar="E", help="App that launched it, such as codex-desktop."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SESSIONS_BEGIN_USAGE)
    if parsed is None:
        return 2
    refusal = uncorroborated_reason(parsed.session_id)
    if refusal is not None:
        return usage_error(refusal)
    project_id = _resolve_begin_project_id(parsed.project, parsed.workspace)
    if parsed.project is not None and project_id is None:
        return usage_error("--project must be a positive numeric project id.")
    payload: Dict[str, Any] = {
        "executor": parsed.executor,
        "provider": parsed.provider,
        "requested_model": parsed.requested_model,
        "workspace": parsed.workspace,
        "project_id": project_id,
        "mode": parsed.mode,
    }
    if project_id is None:
        payload["machine_scope"] = True
    if parsed.entrypoint is not None:
        payload["entrypoint"] = parsed.entrypoint
    return dispatch_and_emit(
        function_id="sessions.begin",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def charge_schedule(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke charge schedule",
        usage=CHARGE_SCHEDULE_USAGE,
    )
    parser.add_argument("--project", default=None, metavar="P", help="Project to schedule from.")
    parser.add_argument(
        "--wip-cap",
        type=int,
        default=None,
        metavar="N",
        help="Most items in progress at once (1-100); default: project policy.",
    )
    parser.add_argument(
        "--item",
        default=None,
        metavar="PREFIX-N",
        help="Schedule this item even if it belongs to another workspace.",
    )
    parser.add_argument(
        "--workspace",
        default=None,
        metavar="W",
        help="Checkout whose items to schedule; default: current directory.",
    )
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
    if parsed.item is not None:
        payload["item"] = parsed.item
    workspace = parsed.workspace
    if workspace is None:
        from pathlib import Path

        workspace = str(Path.cwd())
    payload["workspace"] = workspace
    return dispatch_and_emit(
        function_id="charge.schedule",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


__all__ = [
    "sessions_begin",
    "sessions_identity",
    "sessions_touch",
    "sessions_checkpoint",
    "sessions_checkpoint_read",
    "charge_schedule",
    "SESSIONS_BEGIN_USAGE",
    "SESSIONS_IDENTITY_USAGE",
    "SESSIONS_TOUCH_USAGE",
    "SESSIONS_CHECKPOINT_USAGE",
    "SESSIONS_CHECKPOINT_READ_USAGE",
    "CHARGE_SCHEDULE_USAGE",
]
