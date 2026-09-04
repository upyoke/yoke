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
from yoke_cli.commands.adapters.session_control_launch_selection import (
    selector_payload,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_control.models import LaunchState
from yoke_contracts.session_control.sender_surface import CLI_SENDER_SURFACE


LAUNCH_PREVIEW_USAGE = (
    "yoke session-control launch preview --project P --surface S "
    "[--machine M] [--model M] [--reasoning-effort E] [--context-window N] "
    "[--allow-surface-fallback] [--list-models] [--json]"
)
LAUNCH_CREATE_USAGE = (
    "yoke session-control launch create --project P --surface S "
    "--item PREFIX-N --idempotency-key K [--stdin] [--raw-instructions] "
    "[--machine M] [--model M] [--reasoning-effort E] [--context-window N] "
    "[--presentation P] "
    "[--allow-surface-fallback] [--list-models] [--json]"
)
SESSIONS_CREATE_USAGE = (
    "yoke sessions create --project P --surface S "
    "(--preview | --item PREFIX-N --idempotency-key K [--stdin] [--raw-instructions]) "
    "[--machine M] [--model M] [--reasoning-effort E] [--context-window N] "
    "[--presentation P] "
    "[--allow-surface-fallback] [--list-models] [--json]"
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
    from yoke_contracts.session_control.model_selection import (
        parse_context_window_tokens,
    )

    parser.add_argument("--project", required=True)
    parser.add_argument("--surface", required=True, dest="executor_surface")
    parser.add_argument("--machine", default=None, dest="machine_id")
    parser.add_argument("--model", default=None)
    parser.add_argument("--reasoning-effort", default=None)
    parser.add_argument(
        "--context-window",
        dest="context_window_tokens",
        type=parse_context_window_tokens,
        default=None,
        metavar="TOKENS",
    )
    parser.add_argument("--allow-surface-fallback", action="store_true")


def _maybe_list_models(args: List[str]) -> int | None:
    if "--list-models" not in args:
        return None
    from yoke_contracts.machine_config.preferred_session_models import (
        list_preferred_models,
        render_list_models,
    )

    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--surface", dest="executor_surface", default=None)
    add_json_arg(parser)
    parsed, _unknown = parser.parse_known_args(args)
    report = list_preferred_models(parsed.executor_surface)
    print(render_list_models(report, json_mode=parsed.json_mode), end="")
    return 0


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
    listed = _maybe_list_models(args)
    if listed is not None:
        return listed
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
    payload = selector_payload(parsed)
    if payload is None:
        return 2
    return _dispatch_launch(
        parsed,
        function_id="session_control.launch.preview",
        payload=payload,
    )


def _launch_create_parser(
    prog: str, usage: str, *, preview: bool
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    _add_launch_selector(parser)
    if preview:
        mode = parser.add_mutually_exclusive_group(required=False)
        mode.add_argument("--preview", action="store_true")
        mode.add_argument(
            "--stdin",
            action="store_true",
            help="Optional extras appended after the server-composed mandate.",
        )
    else:
        parser.add_argument(
            "--stdin",
            action="store_true",
            help="Optional extras appended after the server-composed mandate.",
        )
    parser.add_argument(
        "--raw-instructions",
        action="store_true",
        help="Treat --stdin as the full instruction body; skip mandate composition.",
    )
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument("--item", default=None)
    parser.add_argument(
        "--presentation",
        default=None,
        help="Requested native presentation; Claude accepts only 'local'.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    return parser


def _create(args: List[str], *, alias: bool) -> int:
    listed = _maybe_list_models(args)
    if listed is not None:
        return listed
    usage = SESSIONS_CREATE_USAGE if alias else LAUNCH_CREATE_USAGE
    prog = "yoke sessions create" if alias else "yoke session-control launch create"
    parser = _launch_create_parser(prog, usage, preview=alias)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    selector = selector_payload(parsed)
    if selector is None:
        return 2
    if alias and parsed.preview:
        return _dispatch_launch(
            parsed,
            function_id="session_control.launch.preview",
            payload=selector,
        )
    if not parsed.idempotency_key:
        return usage_error("launch create requires --idempotency-key")
    if not parsed.item:
        return usage_error("launch create requires --item PREFIX-N")
    instructions = read_stdin_payload(parsed) or ""
    if parsed.raw_instructions and not instructions.strip():
        return usage_error("raw instruction launches require non-empty --stdin")
    payload = {
        **selector,
        "instructions": instructions,
        "idempotency_key": parsed.idempotency_key,
        "item": parsed.item,
        "sender_surface": CLI_SENDER_SURFACE,
    }
    if parsed.raw_instructions:
        payload["compose_mandate"] = False
    if parsed.presentation:
        payload["presentation"] = parsed.presentation
    return _dispatch_launch(
        parsed,
        function_id="session_control.launch.create",
        payload=payload,
        sensitive_values=(instructions,) if instructions else (),
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
