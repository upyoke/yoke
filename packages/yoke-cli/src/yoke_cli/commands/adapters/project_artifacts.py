"""CLI adapter for generic managed-project rendered artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import (
    add_session_arg,
    parse_or_usage_error,
)
from yoke_cli.project_artifacts import ProjectArtifactError, refresh


PROJECT_ARTIFACTS_REFRESH_USAGE = (
    "yoke project artifacts refresh [REPO_ROOT] --project NAME "
    "[--apply | --verify] [--source-dev-admin] [--session-id S] [--json]"
)


def project_artifacts_refresh(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke project artifacts refresh",
        description=(
            "Preview or apply workflows, generated deployment references, "
            "ops programs, and static infrastructure rendered from packaged "
            "templates plus the project's DB-backed settings. Preview is "
            "the default; project-authored runbooks stay project-owned."
        ),
    )
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=None,
        help="Managed project checkout (default: cwd).",
    )
    parser.add_argument(
        "--project",
        required=True,
        help="Project slug or id.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply only after the complete conflict-free preflight.",
    )
    mode.add_argument(
        "--verify",
        action="store_true",
        help="External drift gate: exit nonzero unless tracked consumers match.",
    )
    parser.add_argument(
        "--source-dev-admin",
        action="store_true",
        help=(
            "Explicit org-admin source-dev override. Requires the server's "
            "YOKE_SERVER_TREE_ROOT and never bypasses checkout identity; "
            "product operation always uses packaged templates."
        ),
    )
    add_session_arg(parser)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, PROJECT_ARTIFACTS_REFRESH_USAGE)
    if parsed is None:
        return 2
    try:
        report = refresh(
            parsed.repo_root,
            project=parsed.project,
            apply=parsed.apply,
            verify=parsed.verify,
            source_dev_admin=parsed.source_dev_admin,
            session_id=parsed.session_id,
        )
    except ProjectArtifactError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            report,
            sort_keys=True if parsed.json_mode else False,
            indent=None if parsed.json_mode else 2,
        )
    )
    if report["refused"]:
        return 1
    if parsed.verify and report["drift"]:
        return 1
    return 0


__all__ = [
    "PROJECT_ARTIFACTS_REFRESH_USAGE",
    "project_artifacts_refresh",
]
