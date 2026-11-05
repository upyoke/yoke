"""File operator questions and read a session's question history."""

from __future__ import annotations

import argparse
from pathlib import Path

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef

ASK_USAGE = (
    "yoke decision-requests ask [--session REQUESTING-SESSION-ID] --key SLUG --question TEXT "
    "[--context-file PATH] [--option ID=LABEL[::DETAIL] ...] [--recommend ID] "
    "[--no-freeform] [--item ITEM] [--replaces ID] [--json]"
)
LIST_USAGE = "yoke decision-requests list (--requesting-session SESSION-ID | --mine) [--status pending|resolved|withdrawn] [--json]"
USAGE_BY_FUNCTION_ID = {
    "decision_requests.ask": ASK_USAGE,
    "decision_requests.list": LIST_USAGE,
}


def _option(text):
    option_id, separator, label_detail = text.partition("=")
    if not separator:
        raise argparse.ArgumentTypeError("Use --option ID=LABEL[::DETAIL]")
    label, _, detail = label_detail.partition("::")
    return {"id": option_id, "label": label, **({"detail": detail} if detail else {})}


def decision_requests_ask(args):
    parser = argparse.ArgumentParser(
        prog="yoke decision-requests ask",
        description="File a durable operator question; its answer arrives as Fleet mail.",
    )
    parser.add_argument("--session", dest="requesting_session_id")
    parser.add_argument("--key", required=True)
    parser.add_argument("--question", required=True)
    parser.add_argument("--context-file", type=Path)
    parser.add_argument("--option", action="append", type=_option, default=[])
    parser.add_argument("--recommend")
    parser.add_argument("--no-freeform", action="store_true")
    parser.add_argument("--item")
    parser.add_argument("--replaces", type=int)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ASK_USAGE)
    if parsed is None:
        return 2
    try:
        context = parsed.context_file.read_text() if parsed.context_file else ""
    except OSError as exc:
        parser.error(
            f"operator_question_context_unreadable: {exc}; provide a readable --context-file"
        )
    return dispatch_and_emit(
        function_id="decision_requests.ask",
        target=TargetRef(kind="global"),
        payload={
            "requesting_session_id": parsed.requesting_session_id,
            "key": parsed.key,
            "question": parsed.question,
            "context": context,
            "options": parsed.option,
            "recommended_option": parsed.recommend,
            "allow_freeform": not parsed.no_freeform,
            "item": parsed.item,
            "replaces": parsed.replaces,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def decision_requests_list(args):
    parser = argparse.ArgumentParser(
        prog="yoke decision-requests list",
        description="Read questions, answers, decision actors and timestamps for one session.",
    )
    selector = parser.add_mutually_exclusive_group(required=True)
    selector.add_argument("--requesting-session", dest="requesting_session_id")
    selector.add_argument("--mine", action="store_true")
    parser.add_argument("--status", choices=("pending", "resolved", "withdrawn"))
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, LIST_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="decision_requests.list",
        target=TargetRef(kind="global"),
        payload={
            "requesting_session_id": parsed.requesting_session_id,
            "status": parsed.status,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


WITHDRAW_USAGE = "yoke decision-requests withdraw REQUEST_ID --reason TEXT [--json]"
USAGE_BY_FUNCTION_ID["decision_requests.withdraw"] = WITHDRAW_USAGE


def decision_requests_withdraw(args):
    parser = argparse.ArgumentParser(
        prog="yoke decision-requests withdraw",
        description="Cancel a pending question as its requesting session or steering.",
    )
    parser.add_argument("request_id", type=int)
    parser.add_argument("--reason", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, WITHDRAW_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="decision_requests.withdraw",
        target=TargetRef(kind="global"),
        payload={"request_id": parsed.request_id, "reason": parsed.reason},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
