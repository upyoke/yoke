"""CLI adapter for removing one installed Pack's record from a project."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import add_session_arg, parse_or_usage_error
from yoke_cli.commands.adapters.packs import _add_catalog_args
from yoke_cli.config.project_onboard_support import machine_config_path
from yoke_cli.packs import PackClientError, run_pack_remove
from yoke_cli.packs.catalog_source import resolve_catalog
from yoke_cli.transport.human_values import write_local


PACKS_REMOVE_USAGE = (
    "yoke packs remove PACK [REPO_ROOT] --project NAME "
    "[--catalog served|lane|commit:SHA] [--yoke-checkout PATH] [--config PATH] "
    "[--apply] [--session-id S] [--json]"
)


def packs_remove(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke packs remove",
        description=(
            "Preview or drop one installed Pack's record from .yoke/packs.json "
            "and the server. Every file the Pack installed stays in the project; "
            "delete those yourself if you no longer want them. Refuses while "
            "another installed Pack depends on it."
        ),
    )
    parser.add_argument("pack", help="Installed Pack slug.")
    parser.add_argument(
        "repo_root",
        nargs="?",
        default=None,
        help="Project checkout path; default: the current checkout.",
    )
    parser.add_argument("--project", required=True, help="Project slug or id.")
    _add_catalog_args(parser)
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Machine config file to use; default: the usual config file.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Drop the records; without it, only preview.",
    )
    add_session_arg(parser)
    parser.add_argument(
        "--json",
        dest="json_mode",
        action="store_true",
        help="Print the report as JSON.",
    )
    parsed = parse_or_usage_error(parser, args, PACKS_REMOVE_USAGE)
    if parsed is None:
        return 2
    try:
        with machine_config_path(parsed.config_path):
            report = run_pack_remove(
                parsed.repo_root,
                project=parsed.project,
                pack=parsed.pack,
                apply=parsed.apply,
                session_id=parsed.session_id,
                catalog=resolve_catalog(
                    parsed.catalog, yoke_checkout=parsed.yoke_checkout
                ),
            )
    except PackClientError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps(report, sort_keys=True))
    else:
        write_local(report, sys.stdout)
    return 0


__all__ = ["PACKS_REMOVE_USAGE", "packs_remove"]
