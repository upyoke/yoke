"""``yoke organizations ...`` identity and settings adapters.

Function ids handled here:

* ``organizations.create`` — found a new hosted org with the caller as its
  founding admin. Platform answers it on a machine's Yoke Cloud
  connection; a local or self-hosted universe refuses it by name.
* ``organizations.get`` — read the org identity card (slug, name, domain,
  created_at). Default reads the universe's identity card; ``--slug``
  addresses a specific org on a multi-org instance.
"""

from __future__ import annotations
from yoke_cli.transport.human_values import write_human

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.api_urls import HOSTED_PLATFORM_URL


__all__ = [
    "ORGANIZATION_USAGE",
    "ORGANIZATIONS_CREATE_USAGE",
    "ORGANIZATIONS_DOMAIN_SET_USAGE",
    "ORGANIZATIONS_GET_USAGE",
    "organizations_create",
    "organizations_domain_set",
    "organizations_get",
]


ORGANIZATIONS_CREATE_USAGE = (
    "yoke organizations create NAME [--slug SLUG] [--session-id S] [--json]"
)
ORGANIZATIONS_GET_USAGE = (
    "yoke organizations get [--slug SLUG] [--session-id S] [--json]"
)
ORGANIZATIONS_DOMAIN_SET_USAGE = (
    "yoke organizations domain set [DOMAIN] [--clear] [--org ORG] "
    "[--session-id S] [--json]"
)

ORGANIZATION_USAGE = {
    "organizations.create": ORGANIZATIONS_CREATE_USAGE,
    "organizations.get": ORGANIZATIONS_GET_USAGE,
    "organizations.domain.set": ORGANIZATIONS_DOMAIN_SET_USAGE,
}


def _add_org_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--org",
        default=None,
        help="Organization slug or id (default: universe identity card).",
    )


def _dispatch(function_id: str, parsed, payload: Dict[str, Any]) -> int:
    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        if response.success:
            write_human(response.result or {}, stdout)
        return None

    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def organizations_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke organizations create",
        description=(
            "Found a new hosted organization with you as its founding admin. "
            "Yoke Cloud answers this on this machine's hosted connection with "
            "the site's founding checks: a redeemed beta code, an unused slug, "
            "and a name of 1-80 characters. Resubmitting the same slug resumes "
            "your own unfinished founding. A local or self-hosted universe has "
            "exactly one org and refuses as organization_create_hosted_only. "
            "Then connect a machine to the new org with "
            f"`yoke setup --connect {HOSTED_PLATFORM_URL}`."
        ),
    )
    parser.add_argument("name", help="Organization display name (1-80 chars).")
    parser.add_argument(
        "--slug",
        default=None,
        help="URL slug (default: derived from NAME).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ORGANIZATIONS_CREATE_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"name": parsed.name}
    if parsed.slug:
        payload["slug"] = parsed.slug
    return _dispatch("organizations.create", parsed, payload)


def organizations_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke organizations get",
        description=(
            "Read the org identity card: slug, name, created_at. Without "
            "--slug this is the universe's identity card (the single org a "
            "local universe carries); --slug addresses a specific org."
        ),
    )
    parser.add_argument(
        "--slug",
        default=None,
        help="Org slug (default: the universe's identity card).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ORGANIZATIONS_GET_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.slug:
        payload["slug"] = parsed.slug

    return _dispatch("organizations.get", parsed, payload)


def organizations_domain_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke organizations domain set")
    parser.add_argument("domain", nargs="?", default=None)
    parser.add_argument("--clear", action="store_true")
    _add_org_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ORGANIZATIONS_DOMAIN_SET_USAGE)
    if parsed is None:
        return 2
    if bool(parsed.domain) == bool(parsed.clear):
        return usage_error("supply exactly one of DOMAIN or --clear")
    payload: Dict[str, Any] = {
        "domain": parsed.domain if not parsed.clear else None,
    }
    if parsed.org:
        payload["org"] = parsed.org
    return _dispatch("organizations.domain.set", parsed, payload)
