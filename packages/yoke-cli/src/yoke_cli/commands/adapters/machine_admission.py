"""List waiting machines and personally approve or deny a matching code."""

import argparse
import sys

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.admission_floor_recovery import admission_floor_hint
from yoke_cli.config.local_reachability import LOCAL_REACHABILITY_NOTICE
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher, emit_response
from yoke_contracts.api.function_call import TargetRef

PENDING_USAGE = "yoke machines pending [--json]"
APPROVE_USAGE = "yoke machines approve CODE [--json]"
DENY_USAGE = "yoke machines deny CODE [--json]"
USAGE_BY_FUNCTION_ID = {
    "machine_authorization.pending": PENDING_USAGE,
    "machine_authorization.get": APPROVE_USAGE,
    "machine_authorization.resolve": f"{APPROVE_USAGE} | {DENY_USAGE}",
}


def _parse(args, action):
    usage = {"pending": PENDING_USAGE, "approve": APPROVE_USAGE, "deny": DENY_USAGE}[
        action
    ]
    parser = argparse.ArgumentParser(
        prog=f"yoke machines {action}",
        description=(
            "List machines waiting to connect, or decide your own matching code. "
            "Approval gives the new machine your signed-in identity. "
            "Check the machine and code before approving."
        ),
    )
    if action != "pending":
        parser.add_argument("code", help="Match code shown by your connecting machine")
    add_json_arg(parser)
    add_session_arg(parser)
    return parse_or_usage_error(parser, args, usage)


def _person(identity):
    return f"{identity['name'] or 'Unnamed person'} (actor {identity['actor_id']})"


def _pending_writer(response, stdout, stderr):
    result = response.result
    if result["mode"] == "local":
        print(LOCAL_REACHABILITY_NOTICE, file=stdout)
        return
    print(f"Signed in as {_person(result['viewer'])}", file=stdout)
    if not result["requests"]:
        print("No machines waiting for approval.", file=stdout)
        return
    print("Code\tMachine\tRequested by\tExpires", file=stdout)
    for row in result["requests"]:
        requester = _person(row["requested_by"]) if row["requested_by"] else "Unbound"
        print(
            f"{row['code']}\t{row['machine']}\t{requester}\t{row['expires_at']}",
            file=stdout,
        )


def machines_pending(args):
    parsed = _parse(args, "pending")
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id="machine_authorization.pending",
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_pending_writer,
        function_hint=admission_floor_hint,
    )


def _decide(args, action):
    parsed = _parse(args, action)
    if parsed is None:
        return 2
    code = parsed.code.strip().upper()
    ensure_handlers_loaded()
    detail = call_dispatcher(
        function_id="machine_authorization.get",
        target=TargetRef(kind="global"),
        payload={"code": code},
        actor=build_actor(session_id=parsed.session_id),
        _function_hint=admission_floor_hint,
    )
    if not detail.success:
        return emit_response(detail, json_mode=parsed.json_mode)
    authorization = detail.result["authorization"]
    person = _person(authorization["viewer"])
    stream = sys.stderr if parsed.json_mode else sys.stdout
    print(
        f"Deciding as {person}: {authorization['machine']} ({code})",
        file=stream,
        flush=True,
    )

    def _decided(response, stdout, stderr):
        verb = (
            "Approved"
            if response.result["authorization"]["decision"] == "approve"
            else "Denied"
        )
        print(f"{verb} {authorization['machine']} ({code}) as {person}.", file=stdout)

    return dispatch_and_emit(
        function_id="machine_authorization.resolve",
        target=TargetRef(kind="global"),
        payload={"code": code, "action": action},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_decided,
        function_hint=admission_floor_hint,
    )


def machines_approve(args):
    return _decide(args, "approve")


def machines_deny(args):
    return _decide(args, "deny")
