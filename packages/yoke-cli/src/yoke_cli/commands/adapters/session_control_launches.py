"""CLI adapters for previewing and managing attested session launches."""

from __future__ import annotations

import argparse
from typing import Any, get_args, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.adapters.session_control_common import (
    read_stdin_payload,
    write_launch_result,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_control.models import LaunchState


LAUNCH_PREVIEW_USAGE = (
    "yoke session-control launch preview --project P --surface S "
    "[--machine M] [--model M] [--allow-surface-fallback] [--json]"
)
LAUNCH_CREATE_USAGE = (
    "yoke session-control launch create --project P --surface S --stdin "
    "--idempotency-key K [--machine M] [--model M] [--presentation P] "
    "[--allow-surface-fallback] [--json]"
)
SESSIONS_CREATE_USAGE = (
    "yoke sessions create --project P --surface S "
    "(--preview | --stdin --idempotency-key K) "
    "[--machine M] [--model M] [--presentation P] "
    "[--allow-surface-fallback] [--json]"
)
LAUNCH_GET_USAGE = "yoke session-control launch get LAUNCH-ID [--json]"
LAUNCH_LIST_USAGE = (
    "yoke session-control launch list --project P [--state STATE] [--limit N] [--json]"
)
LAUNCH_CANCEL_USAGE = "yoke session-control launch cancel LAUNCH-ID [--json]"
LAUNCH_RETRY_USAGE = "yoke session-control launch retry LAUNCH-ID [--json]"
LAUNCH_RECONCILE_USAGE = (
    "yoke session-control launch reconcile LAUNCH-ID [--observed-native-id ID] [--json]"
)


def _add_launch_selector(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", required=True)
    parser.add_argument("--surface", required=True, dest="executor_surface")
    parser.add_argument("--machine", default=None, dest="machine_id")
    parser.add_argument("--model", default=None)
    parser.add_argument("--allow-surface-fallback", action="store_true")


def _preview_payload(parsed: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project": parsed.project,
        "executor_surface": parsed.executor_surface,
        "allow_surface_fallback": parsed.allow_surface_fallback,
    }
    for key in ("machine_id", "model"):
        value = getattr(parsed, key)
        if value:
            payload[key] = value
    return payload


def _dispatch_launch(
    parsed: argparse.Namespace,
    *,
    function_id: str,
    payload: dict[str, Any],
    sensitive_values: tuple[str, ...] = (),
) -> int:
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=write_launch_result,
        sensitive_values=sensitive_values,
    )


def session_launch_preview(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke session-control launch preview",
        description=LAUNCH_PREVIEW_USAGE,
    )
    _add_launch_selector(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, LAUNCH_PREVIEW_USAGE)
    if parsed is None:
        return 2
    return _dispatch_launch(
        parsed,
        function_id="session_control.launch.preview",
        payload=_preview_payload(parsed),
    )


def _launch_create_parser(
    prog: str, usage: str, *, preview: bool
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    _add_launch_selector(parser)
    if preview:
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--preview", action="store_true")
        mode.add_argument(
            "--stdin",
            action="store_true",
            help="Read instructions from stdin; instructions never enter native argv.",
        )
    else:
        parser.add_argument("--stdin", action="store_true", required=True)
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument("--presentation", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    return parser


def _create(args: List[str], *, alias: bool) -> int:
    usage = SESSIONS_CREATE_USAGE if alias else LAUNCH_CREATE_USAGE
    prog = "yoke sessions create" if alias else "yoke session-control launch create"
    parser = _launch_create_parser(prog, usage, preview=alias)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    if alias and parsed.preview:
        return _dispatch_launch(
            parsed,
            function_id="session_control.launch.preview",
            payload=_preview_payload(parsed),
        )
    if not parsed.idempotency_key:
        return usage_error("launch create requires --idempotency-key")
    instructions = read_stdin_payload(parsed)
    if instructions is None:
        return usage_error("launch create requires non-empty instructions on --stdin")
    payload = {
        **_preview_payload(parsed),
        "instructions": instructions,
        "idempotency_key": parsed.idempotency_key,
    }
    if parsed.presentation:
        payload["presentation"] = parsed.presentation
    return _dispatch_launch(
        parsed,
        function_id="session_control.launch.create",
        payload=payload,
        sensitive_values=(instructions,),
    )


def session_launch_create(args: List[str]) -> int:
    return _create(args, alias=False)


def sessions_create(args: List[str]) -> int:
    return _create(args, alias=True)


def session_launch_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke session-control launch list",
        description=LAUNCH_LIST_USAGE,
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--state", choices=get_args(LaunchState), default=None)
    parser.add_argument("--limit", type=int, default=50)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, LAUNCH_LIST_USAGE)
    if parsed is None:
        return 2
    payload: dict[str, Any] = {"project": parsed.project, "limit": parsed.limit}
    if parsed.state:
        payload["state"] = parsed.state
    return _dispatch_launch(
        parsed,
        function_id="session_control.launch.list",
        payload=payload,
    )


def _launch_by_id(args: List[str], operation: str) -> int:
    usage = {
        "get": LAUNCH_GET_USAGE,
        "cancel": LAUNCH_CANCEL_USAGE,
        "retry": LAUNCH_RETRY_USAGE,
        "reconcile": LAUNCH_RECONCILE_USAGE,
    }[operation]
    parser = argparse.ArgumentParser(
        prog=f"yoke session-control launch {operation}",
        description=usage,
    )
    parser.add_argument("launch_id")
    if operation == "reconcile":
        parser.add_argument("--observed-native-id", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    payload = {"launch_id": parsed.launch_id}
    native_id = getattr(parsed, "observed_native_id", None)
    if native_id:
        payload["observed_native_id"] = native_id
    return _dispatch_launch(
        parsed,
        function_id=f"session_control.launch.{operation}",
        payload=payload,
    )


def session_launch_get(args: List[str]) -> int:
    return _launch_by_id(args, "get")


def session_launch_cancel(args: List[str]) -> int:
    return _launch_by_id(args, "cancel")


def session_launch_retry(args: List[str]) -> int:
    return _launch_by_id(args, "retry")


def session_launch_reconcile(args: List[str]) -> int:
    return _launch_by_id(args, "reconcile")


__all__ = [
    "LAUNCH_CANCEL_USAGE",
    "LAUNCH_CREATE_USAGE",
    "LAUNCH_GET_USAGE",
    "LAUNCH_LIST_USAGE",
    "LAUNCH_PREVIEW_USAGE",
    "LAUNCH_RECONCILE_USAGE",
    "LAUNCH_RETRY_USAGE",
    "SESSIONS_CREATE_USAGE",
    "session_launch_cancel",
    "session_launch_create",
    "session_launch_get",
    "session_launch_list",
    "session_launch_preview",
    "session_launch_reconcile",
    "session_launch_retry",
    "sessions_create",
]
