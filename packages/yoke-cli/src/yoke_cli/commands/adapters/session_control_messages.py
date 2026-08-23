"""CLI adapters for durable fleet session messages."""

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
    add_selector_arguments,
    read_stdin_payload,
    selector_payload,
    write_message_result,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.session_control.models import MessageState
from yoke_contracts.session_execution import is_subagent_execution


SAY_USAGE = (
    "yoke say (--preview | --stdin) "
    "(--session S | --item ITEM | --epic-task ITEM:N | --process P | "
    "--project P | --universe) [recipient filters] [--json]"
)
MESSAGE_PREVIEW_USAGE = "yoke session-control message preview [selector] [--json]"
MESSAGE_SEND_USAGE = (
    "yoke session-control message send --stdin [selector] "
    "[--idempotency-key K] [--confirmation-token T] [--json]"
)
MESSAGE_LIST_USAGE = (
    "yoke messages list [--state STATE] [--recipient-session S] [--limit N] [--json]"
)
MESSAGE_GET_USAGE = "yoke messages get MESSAGE-ID [--json]"
MESSAGE_ACKNOWLEDGE_USAGE = "yoke messages acknowledge MESSAGE-ID [--json]"
MESSAGE_CANCEL_USAGE = "yoke messages cancel MESSAGE-ID [--json]"


def _refuse_subagent_message_operation(operation: str) -> int | None:
    if not is_subagent_execution():
        return None
    return usage_error(
        f"in-process subagents cannot {operation} Fleet messages; "
        "report to the parent through the harness-native subagent channel"
    )


def _selector_parser(prog: str, usage: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    add_selector_arguments(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    return parser


def _dispatch_selector(
    parsed: argparse.Namespace,
    *,
    function_id: str,
    body: str | None = None,
) -> int:
    payload: dict[str, Any] = {"selector": selector_payload(parsed)}
    sensitive_values: tuple[str, ...] = ()
    if body is not None:
        payload["body"] = body
        sensitive_values = (body,)
        for key in ("idempotency_key", "confirmation_token"):
            value = getattr(parsed, key, None)
            if value:
                payload[key] = value
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=write_message_result,
        sensitive_values=sensitive_values,
    )


def session_message_preview(args: List[str]) -> int:
    parser = _selector_parser(
        "yoke session-control message preview",
        MESSAGE_PREVIEW_USAGE,
    )
    parsed = parse_or_usage_error(parser, args, MESSAGE_PREVIEW_USAGE)
    if parsed is None:
        return 2
    return _dispatch_selector(
        parsed,
        function_id="session_control.message.preview",
    )


def _add_send_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--stdin",
        action="store_true",
        help="Read the message body from stdin so it never appears in argv.",
    )
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument("--confirmation-token", default=None)


def session_message_send(args: List[str]) -> int:
    parser = _selector_parser(
        "yoke session-control message send",
        MESSAGE_SEND_USAGE,
    )
    _add_send_arguments(parser)
    parsed = parse_or_usage_error(parser, args, MESSAGE_SEND_USAGE)
    if parsed is None:
        return 2
    refused = _refuse_subagent_message_operation("send")
    if refused is not None:
        return refused
    body = read_stdin_payload(parsed)
    if body is None:
        return usage_error("message send requires non-empty content on --stdin")
    return _dispatch_selector(
        parsed,
        function_id="session_control.message.send",
        body=body,
    )


def say(args: List[str]) -> int:
    parser = _selector_parser("yoke say", SAY_USAGE)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--preview",
        action="store_true",
        help="Resolve and authorize recipients without creating a message.",
    )
    mode.add_argument(
        "--stdin",
        action="store_true",
        help="Send the message body read from stdin.",
    )
    parser.add_argument("--idempotency-key", default=None)
    parser.add_argument("--confirmation-token", default=None)
    parsed = parse_or_usage_error(parser, args, SAY_USAGE)
    if parsed is None:
        return 2
    if parsed.preview:
        return _dispatch_selector(
            parsed,
            function_id="session_control.message.preview",
        )
    refused = _refuse_subagent_message_operation("send")
    if refused is not None:
        return refused
    body = read_stdin_payload(parsed)
    if body is None:
        return usage_error("yoke say requires non-empty content on --stdin")
    return _dispatch_selector(
        parsed,
        function_id="session_control.message.send",
        body=body,
    )


def session_message_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke messages list",
        description=MESSAGE_LIST_USAGE,
    )
    parser.add_argument(
        "--state",
        choices=get_args(MessageState),
        default=None,
    )
    parser.add_argument("--recipient-session", default=None)
    parser.add_argument("--limit", type=int, default=50)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, MESSAGE_LIST_USAGE)
    if parsed is None:
        return 2
    payload: dict[str, Any] = {"limit": parsed.limit}
    if parsed.state:
        payload["state"] = parsed.state
    if parsed.recipient_session:
        payload["session_id"] = parsed.recipient_session
    return dispatch_and_emit(
        function_id="session_control.message.list",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=write_message_result,
    )


def _message_by_id(args: List[str], operation: str) -> int:
    usage_by_operation = {
        "get": MESSAGE_GET_USAGE,
        "acknowledge": MESSAGE_ACKNOWLEDGE_USAGE,
        "cancel": MESSAGE_CANCEL_USAGE,
    }
    usage = usage_by_operation[operation]
    parser = argparse.ArgumentParser(
        prog=f"yoke messages {operation}",
        description=usage,
    )
    parser.add_argument("message_id")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    if operation == "acknowledge":
        refused = _refuse_subagent_message_operation("acknowledge")
        if refused is not None:
            return refused
    return dispatch_and_emit(
        function_id=f"session_control.message.{operation}",
        target=TargetRef(kind="global"),
        payload={"message_id": parsed.message_id},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=write_message_result,
    )


def session_message_get(args: List[str]) -> int:
    return _message_by_id(args, "get")


def session_message_acknowledge(args: List[str]) -> int:
    return _message_by_id(args, "acknowledge")


def session_message_cancel(args: List[str]) -> int:
    return _message_by_id(args, "cancel")


__all__ = [
    "MESSAGE_ACKNOWLEDGE_USAGE",
    "MESSAGE_CANCEL_USAGE",
    "MESSAGE_GET_USAGE",
    "MESSAGE_LIST_USAGE",
    "MESSAGE_PREVIEW_USAGE",
    "MESSAGE_SEND_USAGE",
    "SAY_USAGE",
    "say",
    "session_message_acknowledge",
    "session_message_cancel",
    "session_message_get",
    "session_message_list",
    "session_message_preview",
    "session_message_send",
]
