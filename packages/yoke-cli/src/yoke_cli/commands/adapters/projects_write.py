"""``yoke projects ...`` registry-write adapters.

Sibling of :mod:`yoke_cli.commands.adapters.projects` (the read-side
adapters). ``create``/``update`` share one flag parser and differ only
in the dispatched function id (org-scoped register vs project-scoped
edit); ``site create`` / ``environment create`` are the idempotent
infrastructure-registry writes (``projects.site.create`` /
``projects.environment.create``).
"""

from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional

import argparse

from yoke_contracts.project_contract.github_sync_mode import (
    GITHUB_SYNC_DISABLED,
    GITHUB_SYNC_ENABLED,
)
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "projects_create",
    "projects_update",
    "projects_site_create",
    "projects_environment_create",
    "projects_environment_update",
    "PROJECTS_CREATE_USAGE",
    "PROJECTS_UPDATE_USAGE",
    "PROJECTS_SITE_CREATE_USAGE",
    "PROJECTS_ENVIRONMENT_CREATE_USAGE",
    "PROJECTS_ENVIRONMENT_UPDATE_USAGE",
]


PROJECTS_CREATE_USAGE = (
    "yoke projects create --slug SLUG --name NAME "
    "[--org ORG] [--project-id N] [--default-branch BRANCH] "
    "[--github-repo OWNER/REPO] [--public-item-prefix PREFIX] "
    "[--github-sync-mode enabled|disabled] [--allow-public-github-sync] "
    "[--emoji TEXT] [--session-id S] [--json]"
)

PROJECTS_UPDATE_USAGE = (
    "yoke projects update --slug SLUG --name NAME "
    "[--project-id N] [--default-branch BRANCH] "
    "[--github-repo OWNER/REPO] [--public-item-prefix PREFIX] "
    "[--github-sync-mode enabled|disabled] [--allow-public-github-sync] "
    "[--emoji TEXT] [--session-id S] [--json]"
)


def _projects_write(
    args: List[str],
    *,
    function_id: str,
    usage: str,
    prog: str,
    allow_org: bool = False,
) -> int:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    parser.add_argument("--slug", required=True)
    parser.add_argument("--name", required=True)
    if allow_org:
        parser.add_argument(
            "--org",
            dest="org",
            default=None,
            help="Owning organization slug or id for a newly created project.",
        )
    parser.add_argument("--project-id", dest="project_id", type=int, default=None)
    parser.add_argument("--default-branch", dest="default_branch", default=None)
    parser.add_argument("--github-repo", dest="github_repo", default=None)
    parser.add_argument("--public-item-prefix", dest="public_item_prefix", default=None)
    parser.add_argument(
        "--github-sync-mode",
        dest="github_sync_mode",
        default=None,
        choices=(GITHUB_SYNC_ENABLED, GITHUB_SYNC_DISABLED),
        help=(
            "Per-project GitHub sync switch: 'enabled' mirrors the backlog "
            "to GitHub issues; 'disabled' keeps the backlog DB-only "
            "(every issue-sync surface skips this project)."
        ),
    )
    parser.add_argument(
        "--allow-public-github-sync",
        action="store_true",
        help="Explicitly allow enabled issue sync for a verified public repository.",
    )
    parser.add_argument("--emoji", default=None)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    payload = {
        "slug": parsed.slug,
        "name": parsed.name,
    }
    for key in (
        "org",
        "project_id",
        "default_branch",
        "github_repo",
        "public_item_prefix",
        "emoji",
        "github_sync_mode",
        "allow_public_github_sync",
    ):
        value = getattr(parsed, key, None)
        if value is not None:
            payload[key] = value

    def _human_writer(response, stdout, stderr) -> None:
        if not response.success:
            return None
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


def projects_create(args: List[str]) -> int:
    return _projects_write(
        args,
        function_id="projects.create",
        usage=PROJECTS_CREATE_USAGE,
        prog="yoke projects create",
        allow_org=True,
    )


def projects_update(args: List[str]) -> int:
    return _projects_write(
        args,
        function_id="projects.update",
        usage=PROJECTS_UPDATE_USAGE,
        prog="yoke projects update",
    )


PROJECTS_SITE_CREATE_USAGE = (
    "yoke projects site create --project P --site NAME "
    "[--settings-json JSON] [--session-id S] [--json]"
)

PROJECTS_ENVIRONMENT_CREATE_USAGE = (
    "yoke projects environment create --project P --site NAME "
    "--environment NAME [--settings-json JSON] "
    "[--session-id S] [--json]"
)

PROJECTS_ENVIRONMENT_UPDATE_USAGE = (
    "yoke projects environment update --project P --environment NAME "
    "--name NAME [--session-id S] [--json]"
)


def _infrastructure_create(
    args: List[str],
    *,
    function_id: str,
    usage: str,
    prog: str,
    with_environment: bool = False,
) -> int:
    parser = argparse.ArgumentParser(prog=prog, description=usage)
    parser.add_argument("--project", required=True, help="Project slug or id.")
    parser.add_argument(
        "--site",
        dest="site",
        required=True,
        help="Registered site name.",
    )
    if with_environment:
        parser.add_argument(
            "--environment",
            dest="environment",
            required=True,
            help="Registered environment name.",
        )
    parser.add_argument(
        "--settings-json",
        dest="settings_json",
        default=None,
        help="Optional JSON object stored as row settings.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "project": parsed.project,
        "site": parsed.site,
    }
    if with_environment:
        payload["environment"] = parsed.environment
    settings, settings_error = _parse_settings_json(parsed.settings_json)
    if settings_error is not None:
        print(f"error: {settings_error}", file=sys.stderr)
        return 1
    if settings is not None:
        payload["settings"] = settings

    def _human_writer(response, stdout, stderr) -> None:
        if not response.success:
            return None
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


def _parse_settings_json(
    raw: Optional[str],
) -> tuple[Optional[Dict[str, Any]], Optional[str]]:
    if raw is None:
        return None, None
    try:
        value = json.loads(raw)
    except ValueError:
        return None, "--settings-json must be valid JSON"
    if not isinstance(value, dict):
        return None, "--settings-json must be a JSON object"
    return value, None


def projects_site_create(args: List[str]) -> int:
    return _infrastructure_create(
        args,
        function_id="projects.site.create",
        usage=PROJECTS_SITE_CREATE_USAGE,
        prog="yoke projects site create",
    )


def projects_environment_create(args: List[str]) -> int:
    return _infrastructure_create(
        args,
        function_id="projects.environment.create",
        usage=PROJECTS_ENVIRONMENT_CREATE_USAGE,
        prog="yoke projects environment create",
        with_environment=True,
    )


def projects_environment_update(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke projects environment update",
        description=PROJECTS_ENVIRONMENT_UPDATE_USAGE,
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--environment", dest="environment", required=True)
    parser.add_argument("--name", required=True)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, PROJECTS_ENVIRONMENT_UPDATE_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        if not response.success:
            return None
        print(json.dumps(response.result or {}, sort_keys=True), file=stdout)
        return None

    return dispatch_and_emit(
        function_id="projects.environment.update",
        target=TargetRef(kind="global"),
        payload={
            "project": parsed.project,
            "environment": parsed.environment,
            "name": parsed.name,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
