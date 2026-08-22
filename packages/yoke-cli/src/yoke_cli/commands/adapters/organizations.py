"""``yoke organizations ...`` identity and settings adapters.

Function ids handled here:

* ``organizations.get`` — read the org identity card (slug, name, domain,
  created_at). Default reads the universe's identity card; ``--slug``
  addresses a specific org on a multi-org instance.
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
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "ORGANIZATION_USAGE",
    "ORGANIZATIONS_DOMAIN_SET_USAGE",
    "ORGANIZATIONS_GET_USAGE",
    "ORGANIZATIONS_SETTINGS_GET_USAGE",
    "ORGANIZATIONS_SETTINGS_MERGE_USAGE",
    "organizations_domain_set",
    "organizations_get",
    "organizations_settings_get",
    "organizations_settings_merge",
]


ORGANIZATIONS_GET_USAGE = (
    "yoke organizations get [--slug SLUG] [--session-id S] [--json]"
)
ORGANIZATIONS_SETTINGS_GET_USAGE = (
    "yoke organizations settings get --path KEY.PATH [--org ORG] "
    "[--session-id S] [--json]"
)
ORGANIZATIONS_SETTINGS_MERGE_USAGE = (
    "yoke organizations settings merge --set KEY.PATH=VALUE [--set ...] "
    "[--org ORG] [--session-id S] [--json]"
)
ORGANIZATIONS_DOMAIN_SET_USAGE = (
    "yoke organizations domain set [DOMAIN] [--clear] [--org ORG] "
    "[--session-id S] [--json]"
)

ORGANIZATION_USAGE = {
    "organizations.get": ORGANIZATIONS_GET_USAGE,
    "organizations.settings.get": ORGANIZATIONS_SETTINGS_GET_USAGE,
    "organizations.settings.merge": ORGANIZATIONS_SETTINGS_MERGE_USAGE,
    "organizations.domain.set": ORGANIZATIONS_DOMAIN_SET_USAGE,
}


def _add_org_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--org", default=None,
        help="Organization slug or id (default: universe identity card).",
    )


def _dispatch(function_id: str, parsed, payload: Dict[str, Any]) -> int:
    def _human_writer(response, stdout, stderr) -> None:
        del stderr
        if response.success:
            print(json.dumps(response.result or {}, sort_keys=True), file=stdout)
        return None

    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


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


def organizations_settings_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke organizations settings get")
    parser.add_argument("--path", required=True, help="One scalar registry path.")
    _add_org_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ORGANIZATIONS_SETTINGS_GET_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {"path": parsed.path}
    if parsed.org:
        payload["org"] = parsed.org
    return _dispatch("organizations.settings.get", parsed, payload)


def _parse_assignments(values: List[str]) -> Dict[str, Any]:
    assignments: Dict[str, Any] = {}
    for assignment in values:
        key, separator, raw = assignment.partition("=")
        if not separator or not key.strip():
            raise ValueError("--set requires KEY.PATH=VALUE")
        try:
            value: Any = json.loads(raw)
        except json.JSONDecodeError:
            value = raw
        assignments[key.strip()] = value
    return assignments


def organizations_settings_merge(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke organizations settings merge")
    parser.add_argument("--set", dest="assignments", action="append", required=True)
    _add_org_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ORGANIZATIONS_SETTINGS_MERGE_USAGE)
    if parsed is None:
        return 2
    try:
        assignments = _parse_assignments(parsed.assignments)
    except ValueError as exc:
        return usage_error(str(exc))
    payload: Dict[str, Any] = {"assignments": assignments}
    if parsed.org:
        payload["org"] = parsed.org
    return _dispatch("organizations.settings.merge", parsed, payload)


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
