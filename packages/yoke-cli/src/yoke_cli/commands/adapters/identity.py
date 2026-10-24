"""Bind an external sign-in identity or pre-link an email to an existing actor."""

from __future__ import annotations

import argparse
from yoke_cli.transport.human_values import write_human
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
    "identity_link_set",
]


IDENTITY_LINK_SET_USAGE = (
    "yoke identity link set --actor ACTOR (--issuer I --subject S "
    "[--email E] | --email E) [--org ORG] [--json] [--session-id S]"
)
IDENTITY_USAGE: Dict[str, str] = {
    "identity.link.set": IDENTITY_LINK_SET_USAGE,
}


def _print_result(response, stdout, stderr) -> None:
    if not response.success:
        return None
    write_human(response.result or {}, stdout)
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
        "--org",
        default=None,
        help="Org slug or id (default: the universe's identity-card org).",
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
        "--actor",
        required=True,
        help="Target actor id or label.",
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
