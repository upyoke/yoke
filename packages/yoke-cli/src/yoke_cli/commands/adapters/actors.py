"""Actor lifecycle and role commands backed by registered function calls."""

from __future__ import annotations

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


ACTOR_STATE_SET_USAGE = (
    "yoke actors state set ACTOR-ID (--enable | --disable) "
    "[--confirm-system-retirement] [--session-id S] [--json]"
)
ACTOR_ROLE_SET_USAGE = (
    "yoke actors role set (ACTOR-ID | --member EMAIL) --role ROLE "
    "[--session-id S] [--json]"
)
USAGE_BY_FUNCTION_ID = {
    "actors.state.set": ACTOR_STATE_SET_USAGE,
    "actors.role.set": ACTOR_ROLE_SET_USAGE,
}


def actors_state_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke actors state set",
        description=(
            "Enable or disable an actor. Disabling revokes all its keys and "
            "browser sessions. A system actor requires a dependency audit "
            "and --confirm-system-retirement; core and live deployment "
            "actors remain protected."
        ),
    )
    parser.add_argument("actor_id", type=int)
    state = parser.add_mutually_exclusive_group(required=True)
    state.add_argument("--enable", action="store_true")
    state.add_argument("--disable", action="store_true")
    parser.add_argument("--confirm-system-retirement", action="store_true")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ACTOR_STATE_SET_USAGE)
    if parsed is None:
        return 2
    if parsed.actor_id <= 0:
        parser.error("ACTOR-ID must be a positive integer")
    if parsed.enable and parsed.confirm_system_retirement:
        parser.error("--confirm-system-retirement applies only to --disable")
    return dispatch_and_emit(
        function_id="actors.state.set",
        target=TargetRef(kind="global"),
        payload={
            "actor_id": parsed.actor_id,
            "enabled": parsed.enable,
            "confirm_system_retirement": parsed.confirm_system_retirement,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def actors_role_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke actors role set",
        description=(
            "Set a person's one org role: admin, operator, or viewer. Name the "
            "person by ACTOR-ID or by the email of the member linked to an "
            "actor in this universe. Requires org admin. Refuses demoting the "
            "last active admin, machine-only roles, and system actors."
        ),
    )
    parser.add_argument("actor_id", type=int, nargs="?")
    parser.add_argument("--member", dest="member_email")
    parser.add_argument("--role", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ACTOR_ROLE_SET_USAGE)
    if parsed is None:
        return 2
    if (parsed.actor_id is None) == (parsed.member_email is None):
        parser.error("name the person by exactly one of ACTOR-ID or --member EMAIL")
    if parsed.actor_id is not None and parsed.actor_id <= 0:
        parser.error("ACTOR-ID must be a positive integer")
    payload = {"role": parsed.role}
    if parsed.actor_id is not None:
        payload["actor_id"] = parsed.actor_id
    else:
        payload["member_email"] = parsed.member_email
    return dispatch_and_emit(
        function_id="actors.role.set",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
