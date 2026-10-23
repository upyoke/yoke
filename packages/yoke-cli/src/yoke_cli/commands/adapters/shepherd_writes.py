"""``yoke shepherd verdict / caveat-disposition`` write adapters."""

from __future__ import annotations

import argparse
from yoke_cli.transport.human_values import write_human
from typing import Any, Dict, List, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    item_target,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import FunctionCallResponse


SHEPHERD_VERDICT_USAGE = (
    "yoke shepherd verdict --item PREFIX-N --transition T --worker W "
    "--verdict V [--caveats TEXT] [--project P] [--session-id S] [--json]"
)


def _write_verdict_id(
    response: FunctionCallResponse,
    stdout: TextIO,
    _stderr: TextIO,
) -> None:
    if "verdict_id" in response.result:
        print(response.result["verdict_id"], file=stdout)
    else:
        write_human(response.result, stdout)


def shepherd_verdict(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke shepherd verdict",
        usage=SHEPHERD_VERDICT_USAGE,
        description="Prints the new verdict's id.",
    )
    parser.add_argument(
        "--item", required=True, metavar="PREFIX-N", help="Item id (PREFIX-N)."
    )
    parser.add_argument(
        "--transition", required=True, metavar="T", help="Lifecycle transition being judged."
    )
    parser.add_argument(
        "--worker",
        required=True,
        metavar="W",
        help="Name of the worker that produced the judged work.",
    )
    parser.add_argument(
        "--verdict",
        required=True,
        metavar="V",
        help="Gate verdict, e.g. READY, CAVEATS, BLOCKED, SKIPPED.",
    )
    parser.add_argument(
        "--caveats", default=None, metavar="TEXT", help="Caveat text, if any."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, SHEPHERD_VERDICT_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "transition": parsed.transition,
        "worker": parsed.worker,
        "verdict": parsed.verdict,
    }
    if parsed.caveats is not None:
        payload["caveats"] = parsed.caveats
    return dispatch_and_emit(
        function_id="shepherd.verdict.run",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_verdict_id,
    )


SHEPHERD_CAVEAT_DISPOSITION_USAGE = (
    "yoke shepherd caveat-disposition --item PREFIX-N --transition T "
    "--attempt N --caveat-num N --caveat-text TEXT "
    "--disposition RESOLVED|DEFERRED|ANALYZED "
    "[--resolution-details TEXT] [--verdict-id N] [--project P] [--session-id S] [--json]"
)

USAGE_BY_FUNCTION_ID = {
    "shepherd.verdict.run": SHEPHERD_VERDICT_USAGE,
    "shepherd.caveat_disposition.run": SHEPHERD_CAVEAT_DISPOSITION_USAGE,
}


def _write_caveat_result(
    response: FunctionCallResponse,
    stdout: TextIO,
    _stderr: TextIO,
) -> None:
    if "result" in response.result:
        print(response.result["result"], file=stdout)
    else:
        write_human(response.result, stdout)


def shepherd_caveat_disposition(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke shepherd caveat-disposition",
        usage=SHEPHERD_CAVEAT_DISPOSITION_USAGE,
    )
    parser.add_argument(
        "--item", required=True, metavar="PREFIX-N", help="Item id (PREFIX-N)."
    )
    parser.add_argument(
        "--transition", required=True, metavar="T", help="Lifecycle transition being judged."
    )
    parser.add_argument(
        "--attempt", type=int, required=True, metavar="N", help="Verdict attempt number."
    )
    parser.add_argument(
        "--caveat-num",
        dest="caveat_num",
        type=int,
        required=True,
        metavar="N",
        help="Caveat number, counting from 1.",
    )
    parser.add_argument(
        "--caveat-text",
        dest="caveat_text",
        required=True,
        metavar="TEXT",
        help="The caveat's original text.",
    )
    parser.add_argument(
        "--disposition",
        required=True,
        choices=("RESOLVED", "DEFERRED", "ANALYZED"),
        metavar="RESOLVED|DEFERRED|ANALYZED",
        help="How the caveat was handled.",
    )
    parser.add_argument(
        "--resolution-details",
        dest="resolution_details",
        default=None,
        metavar="TEXT",
        help="How it was resolved, if it was.",
    )
    parser.add_argument(
        "--verdict-id",
        dest="verdict_id",
        type=int,
        default=None,
        metavar="N",
        help="Id of the verdict the caveat came from, as `yoke shepherd verdict` printed it.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser,
        args,
        SHEPHERD_CAVEAT_DISPOSITION_USAGE,
    )
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "transition": parsed.transition,
        "attempt": int(parsed.attempt),
        "caveat_num": int(parsed.caveat_num),
        "caveat_text": parsed.caveat_text,
        "disposition": parsed.disposition,
    }
    if parsed.resolution_details is not None:
        payload["resolution_details"] = parsed.resolution_details
    if parsed.verdict_id is not None:
        payload["verdict_id"] = int(parsed.verdict_id)
    return dispatch_and_emit(
        function_id="shepherd.caveat_disposition.run",
        target=item_target("item", parsed.item, parsed.project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_write_caveat_result,
    )


__all__ = [
    "SHEPHERD_VERDICT_USAGE",
    "SHEPHERD_CAVEAT_DISPOSITION_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "shepherd_verdict",
    "shepherd_caveat_disposition",
]
