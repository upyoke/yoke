"""``yoke identity ...`` adapters — sign-in admission administration.

Function ids handled here (all org-admin-gated at dispatch):

* ``identity.invite.create`` — invite an email into the org, optionally
  granting an org role on acceptance or pre-linking an existing actor.
* ``identity.invite.list`` — list invites (filter by status).
* ``identity.invite.revoke`` — revoke a pending invite.
* ``identity.link.set`` — bind an external identity (issuer+subject) or
  pre-link an email to an existing actor.
* ``identity.autojoin.set`` — set or clear the org auto-join email domain.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "IDENTITY_USAGE",
    "identity_autojoin_set",
    "identity_invite_create",
    "identity_invite_list",
    "identity_invite_revoke",
    "identity_link_set",
]


IDENTITY_INVITE_CREATE_USAGE = (
    "yoke identity invite create EMAIL [--role ROLE] [--actor ACTOR] "
    "[--org ORG] [--json]"
)
IDENTITY_INVITE_LIST_USAGE = (
    "yoke identity invite list [--status STATUS] [--org ORG] [--json]"
)
IDENTITY_INVITE_REVOKE_USAGE = "yoke identity invite revoke INVITE_ID [--json]"
IDENTITY_LINK_SET_USAGE = (
    "yoke identity link set --actor ACTOR (--issuer I --subject S [--email E] "
    "| --email E) [--org ORG] [--json]"
)
IDENTITY_AUTOJOIN_SET_USAGE = (
    "yoke identity autojoin set [DOMAIN] [--clear] [--org ORG] [--json]"
)

IDENTITY_USAGE: Dict[str, str] = {
    "identity.invite.create": IDENTITY_INVITE_CREATE_USAGE,
    "identity.invite.list": IDENTITY_INVITE_LIST_USAGE,
    "identity.invite.revoke": IDENTITY_INVITE_REVOKE_USAGE,
    "identity.link.set": IDENTITY_LINK_SET_USAGE,
    "identity.autojoin.set": IDENTITY_AUTOJOIN_SET_USAGE,
}


def _print_result(response, stdout, stderr) -> None:
    if not response.success:
        return None
    print(json.dumps(response.result or {}, sort_keys=True), file=stdout)
    return None


def _dispatch(function_id: str, payload: Dict[str, Any], parsed) -> int:
    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_print_result,
    )


def _add_org_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--org", default=None,
        help="Org slug or id (default: the universe's identity-card org).",
    )


def identity_invite_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke identity invite create",
        description=(
            "Invite an email address into the org. A pending invite admits "
            "the next verified OIDC sign-in with that email; --role grants "
            "an org role on acceptance; --actor pre-links the sign-in to an "
            "existing actor instead of creating a new one."
        ),
    )
    parser.add_argument("email", help="Email address to admit.")
    parser.add_argument(
        "--role", default=None,
        help="Org role name granted on acceptance (e.g. admin, viewer).",
    )
    parser.add_argument(
        "--actor", default=None,
        help="Existing actor id or label to bind the sign-in to.",
    )
    _add_org_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, IDENTITY_INVITE_CREATE_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"email": parsed.email}
    if parsed.role:
        payload["role"] = parsed.role
    if parsed.actor:
        payload["actor"] = parsed.actor
    if parsed.org:
        payload["org"] = parsed.org
    return _dispatch("identity.invite.create", payload, parsed)


def identity_invite_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke identity invite list",
        description="List actor invites, optionally filtered by status.",
    )
    parser.add_argument(
        "--status", default=None,
        help="Filter: pending, accepted, or revoked.",
    )
    _add_org_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, IDENTITY_INVITE_LIST_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.status:
        payload["status"] = parsed.status
    if parsed.org:
        payload["org"] = parsed.org
    return _dispatch("identity.invite.list", payload, parsed)


def identity_invite_revoke(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke identity invite revoke",
        description="Revoke a pending invite so it no longer admits sign-ins.",
    )
    parser.add_argument("invite_id", type=int, help="Invite row id.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, IDENTITY_INVITE_REVOKE_USAGE)
    if parsed is None:
        return 2
    return _dispatch(
        "identity.invite.revoke", {"invite_id": parsed.invite_id}, parsed,
    )


def identity_link_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke identity link set",
        description=(
            "Bind sign-in admission to an EXISTING actor. Two shapes: "
            "--issuer + --subject writes the external identity link "
            "directly; --email alone pre-links the next verified sign-in "
            "with that email to the actor."
        ),
    )
    parser.add_argument(
        "--actor", required=True, help="Target actor id or label.",
    )
    parser.add_argument("--issuer", default=None, help="OIDC issuer URL.")
    parser.add_argument("--subject", default=None, help="OIDC subject claim.")
    parser.add_argument("--email", default=None, help="Email address.")
    _add_org_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, IDENTITY_LINK_SET_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"actor": parsed.actor}
    for key in ("issuer", "subject", "email", "org"):
        value = getattr(parsed, key)
        if value:
            payload[key] = value
    return _dispatch("identity.link.set", payload, parsed)


def identity_autojoin_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke identity autojoin set",
        description=(
            "Set the org's auto-join email domain: any verified OIDC "
            "sign-in whose email is under the domain is admitted without "
            "an invite. Pass --clear to turn auto-join off."
        ),
    )
    parser.add_argument(
        "domain", nargs="?", default=None,
        help="Email domain to admit (e.g. example.com).",
    )
    parser.add_argument(
        "--clear", action="store_true",
        help="Clear the auto-join domain (no domain-based admission).",
    )
    _add_org_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, IDENTITY_AUTOJOIN_SET_USAGE)
    if parsed is None:
        return 2
    if bool(parsed.domain) == bool(parsed.clear):
        print(
            f"Usage: {IDENTITY_AUTOJOIN_SET_USAGE}\n"
            "supply exactly one of DOMAIN or --clear",
        )
        return 2
    payload: Dict[str, Any] = {"domain": parsed.domain if not parsed.clear else None}
    if parsed.org:
        payload["org"] = parsed.org
    return _dispatch("identity.autojoin.set", payload, parsed)
