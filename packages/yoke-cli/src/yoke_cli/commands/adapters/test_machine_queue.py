"""Steering adapters for shared Test Machine turns."""

import argparse

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef

PLACE_USAGE = (
    "yoke test-machine queue place --execution ID --host H --position N --reason TEXT "
    "[--project P] [--session-id S] [--json]"
)
HAND_OVER_USAGE = (
    "yoke test-machine queue hand-over --from ID --to ID --host H --reason TEXT "
    "[--project P] [--session-id S] [--json]"
)
FUNCTION_USAGE = {
    "test_machine.queue.place": PLACE_USAGE,
    "test_machine.queue.hand_over": HAND_OVER_USAGE,
}


def _command(args, *, action, summary, configure):
    function_id = f"test_machine.queue.{action.replace('-', '_')}"
    usage = FUNCTION_USAGE[function_id]
    parser = argparse.ArgumentParser(
        prog=f"yoke test-machine queue {action}",
        description=summary,
        epilog="Requires a steering seat covering the execution's project.",
    )
    configure(parser)
    parser.add_argument(
        "--host", required=True, help="Test Machine whose line to edit."
    )
    parser.add_argument(
        "--reason", required=True, help="Reason to record with the edit."
    )
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if isinstance(parsed, int):
        return parsed
    payload = vars(parsed)
    project = client_project_context(payload.pop("project"))
    session_id = payload.pop("session_id")
    json_mode = payload.pop("json_mode")
    if not project:
        return usage_error(
            "Pass --project P or run from the execution's project checkout."
        )

    def write_result(response, out, _err):
        result = response.result
        execution = result["execution_id"]
        position = result["position"]
        if position is None:
            print(
                f"Execution {execution} took a turn on another eligible host.", file=out
            )
        else:
            print(
                f"Execution {execution} is at position {position} for {result['host']}.",
                file=out,
            )

    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global", project_id=project),
        payload=payload,
        session_id=session_id,
        json_mode=json_mode,
        human_writer=write_result,
    )


def _place_args(parser):
    parser.add_argument("--execution", required=True, help="Waiting QA plan execution.")
    parser.add_argument(
        "--position",
        type=int,
        required=True,
        help="Place before this waiter, counting from 1.",
    )


def queue_place(args):
    return _command(
        args,
        action="place",
        summary="Move a QA execution to one place across its host lines.",
        configure=_place_args,
    )


def _handover_args(parser):
    parser.add_argument(
        "--from",
        dest="from_execution",
        required=True,
        help="Execution with the unstarted turn.",
    )
    parser.add_argument(
        "--to",
        dest="to_execution",
        required=True,
        help="Waiting execution that should take the turn.",
    )


def queue_hand_over(args):
    return _command(
        args,
        action="hand-over",
        summary="Give an unstarted reservation to another QA execution.",
        configure=_handover_args,
    )
