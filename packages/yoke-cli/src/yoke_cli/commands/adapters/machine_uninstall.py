"""The client-local ``yoke uninstall`` entrypoint."""

from __future__ import annotations

import argparse
import sys

from yoke_cli.config.machine_uninstall import run
from yoke_cli.config.machine_uninstall_inventory import UninstallError

UNINSTALL_USAGE = (
    "yoke uninstall [--backup | --no-backup] [--projects all|none|PATH,...] [--yes]"
)


def uninstall(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke uninstall",
        description=(
            "Remove Yoke from this machine. Machines holding a local universe or "
            "self-host server first choose whether to export a backup. Then choose "
            "registered projects to remove Yoke from; every remaining step runs "
            "without more prompts. Source-checkout installs refuse."
        ),
    )
    backup = parser.add_mutually_exclusive_group()
    backup.add_argument("--backup", dest="backup", action="store_true")
    backup.add_argument("--no-backup", dest="backup", action="store_false")
    parser.set_defaults(backup=None)
    parser.add_argument(
        "--projects", help="all, none, or comma-separated registered checkout paths"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Run unattended with explicit project and data choices",
    )
    parsed = parser.parse_args(args)
    try:
        return run(
            backup=parsed.backup,
            projects=parsed.projects,
            non_interactive=parsed.yes or not sys.stdin.isatty(),
        )
    except (UninstallError, OSError, RuntimeError, ValueError) as exc:
        print(f"yoke uninstall: {exc}", file=sys.stderr)
        return 1
