"""Actor lifecycle command backed by the registered function call."""

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
USAGE_BY_FUNCTION_ID = {"actors.state.set": ACTOR_STATE_SET_USAGE}


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
