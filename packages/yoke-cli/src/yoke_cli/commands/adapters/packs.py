"""CLI adapters for Pack discovery, installation, and optional updates."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import add_session_arg, parse_or_usage_error
from yoke_cli.config.project_onboard_support import machine_config_path
from yoke_cli.packs import PackClientError, list_packs, run_pack_operation


PACKS_LIST_USAGE = "yoke packs list --project NAME [--config PATH] [--json]"
PACKS_GET_USAGE = (
    "yoke packs get PACK [REPO_ROOT] --project NAME [--version VERSION] "
    "[--config PATH] [--apply] [--json]"
)
PACKS_UPDATE_USAGE = (
    "yoke packs update PACK [REPO_ROOT] --project NAME [--version VERSION] "
    "[--accept-current PATH ...] [--config PATH] [--apply] [--json]"
)


def packs_list(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke packs list",
        description="Show available, installed, and stale Packs for one project.",
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    parser.add_argument("--config", dest="config_path", default=None)
    add_session_arg(parser)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, PACKS_LIST_USAGE)
    if parsed is None:
        return 2
    try:
        with machine_config_path(parsed.config_path):
            report = list_packs(project=parsed.project, session_id=parsed.session_id)
    except PackClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps(report, sort_keys=True))
        return 0
    for row in report["packs"]:
        installed = row.get("installed_version") or "—"
        print(
            f"{row['slug']}\t{row['status']}\tinstalled={installed}\t"
            f"latest={row['latest_version']}\t{row['description']}"
        )
    return 0


def packs_get(args: List[str]) -> int:
    return _pack_write("get", args, PACKS_GET_USAGE)


def packs_update(args: List[str]) -> int:
    return _pack_write("update", args, PACKS_UPDATE_USAGE)


def _pack_write(operation: str, args: List[str], usage: str) -> int:
    parser = argparse.ArgumentParser(
        prog=f"yoke packs {operation}",
        description=(
            f"Preview or apply one Pack {operation}. Project files remain "
            "project-owned; updates three-way-merge normal customizations."
        ),
    )
    parser.add_argument("pack", help="Pack slug from `yoke packs list`.")
    parser.add_argument("repo_root", nargs="?", default=None)
    parser.add_argument("--project", required=True, help="Project slug or id.")
    parser.add_argument("--version", default=None, help="Exact Pack version.")
    parser.add_argument("--config", dest="config_path", default=None)
    if operation == "update":
        parser.add_argument(
            "--accept-current",
            dest="accepted_current_paths",
            action="append",
            default=[],
            metavar="PATH",
            help=(
                "After resolving this exact conflict in the project, keep the "
                "current file and advance its Pack baseline; repeat per path."
            ),
        )
    parser.add_argument(
        "--apply", action="store_true", help="Apply a conflict-free preview."
    )
    add_session_arg(parser)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, usage)
    if parsed is None:
        return 2
    try:
        with machine_config_path(parsed.config_path):
            report = run_pack_operation(
                parsed.repo_root,
                project=parsed.project,
                pack=parsed.pack,
                operation=operation,
                apply=parsed.apply,
                version=parsed.version,
                session_id=parsed.session_id,
                accepted_current_paths=getattr(parsed, "accepted_current_paths", None),
            )
    except PackClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            report, sort_keys=parsed.json_mode, indent=None if parsed.json_mode else 2
        )
    )
    return 1 if report.get("refused") else 0


__all__ = [
    "PACKS_GET_USAGE",
    "PACKS_LIST_USAGE",
    "PACKS_UPDATE_USAGE",
    "packs_get",
    "packs_list",
    "packs_update",
]
