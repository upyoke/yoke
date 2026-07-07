"""``yoke projects create`` / ``yoke projects update`` adapters.

Sibling of :mod:`yoke_cli.commands.adapters.projects` (the read-side
adapters). Both write commands share one flag parser and differ only in
the dispatched function id (org-scoped register vs project-scoped edit).
"""

from __future__ import annotations

import json
from typing import List

import argparse

from yoke_contracts.project_contract.github_sync_mode import (
    GITHUB_SYNC_BACKLOG_ONLY,
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
    "projects_create", "projects_update",
    "PROJECTS_CREATE_USAGE", "PROJECTS_UPDATE_USAGE",
]


PROJECTS_CREATE_USAGE = (
    "yoke projects create --slug SLUG --name NAME "
    "[--org ORG] [--project-id N] [--default-branch BRANCH] "
    "[--github-repo OWNER/REPO] [--public-item-prefix PREFIX] "
    "[--github-sync-mode enabled|backlog_only] "
    "[--emoji TEXT] [--session-id S] [--json]"
)

PROJECTS_UPDATE_USAGE = (
    "yoke projects update --slug SLUG --name NAME "
    "[--project-id N] [--default-branch BRANCH] "
    "[--github-repo OWNER/REPO] [--public-item-prefix PREFIX] "
    "[--github-sync-mode enabled|backlog_only] "
    "[--emoji TEXT] [--session-id S] [--json]"
)


def _projects_write(
    args: List[str], *, function_id: str, usage: str, prog: str,
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
        choices=(GITHUB_SYNC_ENABLED, GITHUB_SYNC_BACKLOG_ONLY),
        help=(
            "Per-project GitHub sync switch: 'enabled' mirrors the backlog "
            "to GitHub issues; 'backlog_only' keeps the backlog DB-only "
            "(every issue-sync surface skips this project)."
        ),
    )
    parser.add_argument("--emoji", default=None)
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    payload = {
        "slug": parsed.slug,
        "name": parsed.name,
    }
    for key in (
        "org", "project_id", "default_branch", "github_repo",
        "public_item_prefix", "emoji", "github_sync_mode",
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
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


def projects_create(args: List[str]) -> int:
    return _projects_write(
        args, function_id="projects.create",
        usage=PROJECTS_CREATE_USAGE, prog="yoke projects create",
        allow_org=True,
    )


def projects_update(args: List[str]) -> int:
    return _projects_write(
        args, function_id="projects.update",
        usage=PROJECTS_UPDATE_USAGE, prog="yoke projects update",
    )
