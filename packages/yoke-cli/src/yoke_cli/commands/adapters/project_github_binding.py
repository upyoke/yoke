"""``yoke projects github-binding ...`` adapters."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_contracts.api.function_call import TargetRef
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)


PROJECTS_GITHUB_BINDING_BIND_USAGE = (
    "yoke projects github-binding bind --project NAME --installation-id ID "
    "--account-id ID --account-login LOGIN --account-type TYPE "
    "--github-repo OWNER/REPO [--permissions-json JSON] [--json]"
)
PROJECTS_GITHUB_BINDING_UNBIND_USAGE = (
    "yoke projects github-binding unbind --project NAME [--json]"
)
PROJECTS_GITHUB_BINDING_STATUS_USAGE = (
    "yoke projects github-binding status --project NAME [--json]"
)


def projects_github_binding_bind(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects github-binding bind",
        description=PROJECTS_GITHUB_BINDING_BIND_USAGE,
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--account-id", required=True)
    parser.add_argument("--account-login", required=True)
    parser.add_argument("--account-type", required=True)
    parser.add_argument("--github-repo", required=True)
    parser.add_argument("--repository-id", default=None)
    parser.add_argument("--default-branch", default=None)
    parser.add_argument("--repository-selection", default="selected")
    parser.add_argument("--permissions-json", default="{}")
    parser.add_argument("--installation-status", default="active")
    parser.add_argument("--binding-status", default="active")
    parser.add_argument("--last-verified-at", default=None)
    parser.add_argument("--last-error", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, PROJECTS_GITHUB_BINDING_BIND_USAGE,
    )
    if parsed is None:
        return 2
    try:
        permissions = json.loads(parsed.permissions_json or "{}")
    except json.JSONDecodeError as exc:
        return usage_error(f"--permissions-json invalid: {exc}")
    if not isinstance(permissions, dict):
        return usage_error("--permissions-json must be a JSON object")
    payload: Dict[str, Any] = {
        "project": parsed.project,
        "installation_id": parsed.installation_id,
        "account_id": parsed.account_id,
        "account_login": parsed.account_login,
        "account_type": parsed.account_type,
        "github_repo": parsed.github_repo,
        "repository_id": parsed.repository_id,
        "default_branch": parsed.default_branch,
        "repository_selection": parsed.repository_selection,
        "permissions": permissions,
        "installation_status": parsed.installation_status,
        "binding_status": parsed.binding_status,
        "last_verified_at": parsed.last_verified_at,
        "last_error": parsed.last_error,
    }
    return _dispatch(
        "projects.github_binding.bind",
        payload,
        parsed.session_id,
        parsed.json_mode,
    )


def projects_github_binding_unbind(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects github-binding unbind",
        description=PROJECTS_GITHUB_BINDING_UNBIND_USAGE,
    )
    parser.add_argument("--project", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, PROJECTS_GITHUB_BINDING_UNBIND_USAGE,
    )
    if parsed is None:
        return 2
    return _dispatch(
        "projects.github_binding.unbind",
        {"project": parsed.project},
        parsed.session_id,
        parsed.json_mode,
    )


def projects_github_binding_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects github-binding status",
        description=PROJECTS_GITHUB_BINDING_STATUS_USAGE,
    )
    parser.add_argument("--project", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, PROJECTS_GITHUB_BINDING_STATUS_USAGE,
    )
    if parsed is None:
        return 2
    return _dispatch(
        "projects.github_binding.status",
        {"project": parsed.project},
        parsed.session_id,
        parsed.json_mode,
    )


def _dispatch(
    function_id: str,
    payload: Dict[str, Any],
    session_id: str | None,
    json_mode: bool,
) -> int:
    def _human_writer(response, stdout, stderr) -> None:
        if response.success:
            print(json.dumps(response.result or {}, sort_keys=True), file=stdout)
        return None

    return dispatch_and_emit(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=session_id,
        json_mode=json_mode,
        human_writer=_human_writer,
    )


__all__ = [
    "PROJECTS_GITHUB_BINDING_BIND_USAGE",
    "PROJECTS_GITHUB_BINDING_STATUS_USAGE",
    "PROJECTS_GITHUB_BINDING_UNBIND_USAGE",
    "projects_github_binding_bind",
    "projects_github_binding_status",
    "projects_github_binding_unbind",
]
