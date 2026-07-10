"""``yoke projects github-binding ...`` adapters."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from yoke_cli.config import github_user_tokens, machine_config
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.github_origin import (
    GitHubApiOriginError,
    validate_github_api_endpoint,
)
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)


PROJECTS_GITHUB_BINDING_BIND_USAGE = (
    "yoke projects github-binding bind --project NAME --installation-id ID "
    "--repository-id ID --github-repo OWNER/REPO [--json]"
)
PROJECTS_GITHUB_BINDING_UNBIND_USAGE = (
    "yoke projects github-binding unbind --project NAME [--json]"
)
PROJECTS_GITHUB_BINDING_STATUS_USAGE = (
    "yoke projects github-binding status --project NAME "
    "[--field github_repo] [--json]"
)


def projects_github_binding_bind(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects github-binding bind",
        description=PROJECTS_GITHUB_BINDING_BIND_USAGE,
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--installation-id", required=True)
    parser.add_argument("--repository-id", required=True)
    parser.add_argument("--github-repo", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(
        parser, args, PROJECTS_GITHUB_BINDING_BIND_USAGE,
    )
    if parsed is None:
        return 2
    try:
        github = machine_config.github_config()
        expected_api_url = validate_github_api_endpoint(
            str(github.get("api_url") or "")
        ).base_url
        user_token = github_user_tokens.access_token_from_machine_config()
    except (GitHubApiOriginError, github_user_tokens.GitHubUserTokenError):
        message = (
            "GitHub App user authorization is unavailable. Run "
            "`yoke github connect` and retry."
        )
        if parsed.json_mode:
            print(json.dumps({
                "success": False,
                "code": "github_user_authorization_unavailable",
                "message": message,
            }), file=sys.stderr)
        else:
            print(f"error: {message}", file=sys.stderr)
        return 1
    payload: Dict[str, Any] = {
        "project": parsed.project,
        "installation_id": parsed.installation_id,
        "repository_id": parsed.repository_id,
        "github_repo": parsed.github_repo,
        "expected_api_url": expected_api_url,
        "github_user_access_token": user_token.access_token,
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
    parser.add_argument("--field", choices=("github_repo",), default=None)
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
        field=parsed.field,
    )


def _dispatch(
    function_id: str,
    payload: Dict[str, Any],
    session_id: str | None,
    json_mode: bool,
    *,
    field: str | None = None,
) -> int:
    def _human_writer(response, stdout, stderr) -> None:
        if response.success:
            result = response.result or {}
            if field == "github_repo":
                binding = result.get("binding") or {}
                print(str(binding.get("github_repo") or ""), file=stdout)
            else:
                print(json.dumps(result, sort_keys=True), file=stdout)
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
