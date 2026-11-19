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
ACTOR_ROLE_REMOVE_USAGE = (
    "yoke actors role remove (ACTOR-ID | --member EMAIL) [--session-id S] [--json]"
)
ACTOR_PROJECT_ROLE_SET_USAGE = (
    "yoke actors project-role set (ACTOR-ID | --member EMAIL) --project P "
    "--role ROLE [--session-id S] [--json]"
)
ACTOR_PROJECT_ROLE_REMOVE_USAGE = (
    "yoke actors project-role remove (ACTOR-ID | --member EMAIL) --project P "
    "[--session-id S] [--json]"
)
USAGE_BY_FUNCTION_ID = {
    "actors.state.set": ACTOR_STATE_SET_USAGE,
    "actors.role.set": ACTOR_ROLE_SET_USAGE,
    "actors.role.remove": ACTOR_ROLE_REMOVE_USAGE,
    "actors.project_role.set": ACTOR_PROJECT_ROLE_SET_USAGE,
    "actors.project_role.remove": ACTOR_PROJECT_ROLE_REMOVE_USAGE,
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
    parser.add_argument(
        "actor_id", type=int, help="Id of the actor to enable or disable."
    )
    state = parser.add_mutually_exclusive_group(required=True)
    state.add_argument("--enable", action="store_true", help="Enable the actor.")
    state.add_argument(
        "--disable",
        action="store_true",
        help="Disable the actor and revoke its keys and browser sessions.",
    )
    parser.add_argument(
        "--confirm-system-retirement",
        action="store_true",
        help="Confirm retiring a system actor; applies only to --disable.",
    )
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


def _person_command(
    args: List[str],
    *,
    prog: str,
    description: str,
    usage: str,
    function_id: str,
    project: bool = False,
    role: str | None = None,
) -> int:
    """Parse one person (ACTOR-ID or --member) plus options, then dispatch."""
    parser = argparse.ArgumentParser(prog=prog, description=description)
    parser.add_argument(
        "actor_id", type=int, nargs="?", help="Id of the person's actor; or use --member."
    )
    parser.add_argument(
        "--member",
        dest="member_email",
        help="Email of the org member whose linked actor to change.",
    )
    if project:
        parser.add_argument("--project", required=True, help="Project slug or id.")
    if role:
        parser.add_argument("--role", required=True, help=role)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    if (parsed.actor_id is None) == (parsed.member_email is None):
        parser.error("name the person by exactly one of ACTOR-ID or --member EMAIL")
    if parsed.actor_id is not None and parsed.actor_id <= 0:
        parser.error("ACTOR-ID must be a positive integer")
    payload = (
        {"actor_id": parsed.actor_id}
        if parsed.actor_id is not None
        else {"member_email": parsed.member_email}
    )
    if project:
        payload["project"] = parsed.project
    if role:
        payload["role"] = parsed.role
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


_REFUSALS = (
    "Requires org owner or admin. Only owners may edit owners or grant owner; "
    "refuses removing the last active owner, machine-only roles, and system actors."
)


def actors_role_set(args: List[str]) -> int:
    return _person_command(
        args,
        prog="yoke actors role set",
        description=(
            "Set a person's one org role: owner, admin, operator, or viewer. It "
            "reaches every project in the org. Name the person by ACTOR-ID or by "
            "the email of the member linked to an actor in this universe. "
            + _REFUSALS
        ),
        usage=ACTOR_ROLE_SET_USAGE,
        function_id="actors.role.set",
        role="Role to set: owner, admin, operator, or viewer.",
    )


def actors_role_remove(args: List[str]) -> int:
    return _person_command(
        args,
        prog="yoke actors role remove",
        description=(
            "Remove a person's org role, so they reach only the projects granted "
            "to them with `yoke actors project-role set`. Removing nothing "
            "succeeds. " + _REFUSALS
        ),
        usage=ACTOR_ROLE_REMOVE_USAGE,
        function_id="actors.role.remove",
    )


def actors_project_role_set(args: List[str]) -> int:
    return _person_command(
        args,
        prog="yoke actors project-role set",
        description=(
            "Make ROLE a person's only role on one project. With no org role, "
            "the person sees only the projects granted this way. " + _REFUSALS
        ),
        usage=ACTOR_PROJECT_ROLE_SET_USAGE,
        function_id="actors.project_role.set",
        project=True,
        role="Project role to set: owner, admin, operator, or viewer.",
    )


def actors_project_role_remove(args: List[str]) -> int:
    return _person_command(
        args,
        prog="yoke actors project-role remove",
        description=(
            "Remove a person's role on one project. Removing nothing succeeds. "
            + _REFUSALS
        ),
        usage=ACTOR_PROJECT_ROLE_REMOVE_USAGE,
        function_id="actors.project_role.remove",
        project=True,
    )
