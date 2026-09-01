"""Tool-shaped adapter for taking a self-host bundle off a machine.

A sibling of the init and import adapters rather than another block inside
them: teardown carries its own destructive-consent gate and its own report,
and the three commands only share a subcommand table.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.self_host import teardown

AdapterFn = Callable[[List[str]], int]

TEARDOWN_USAGE = (
    "yoke self-host teardown [--dir D] [--destroy-universe] [--remove-images] "
    "[--remove-bundle] [--keep-connection | --connection ENV] "
    "[--activate ENV] [--yes] [--json]"
)
_CONSENT_WORD = "destroy"

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke self-host teardown": TEARDOWN_USAGE,
}

_INPUT = input


def self_host_teardown(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke self-host teardown",
        description=(
            "Take a self-host bundle off this machine. Always stops and "
            "removes the stack; everything further is opt-in and named for "
            "what it destroys. Without --destroy-universe the database "
            "volume survives, so `docker compose up -d` from the bundle "
            "brings the same universe back. The machine connection pointing "
            "at this bundle's server is retired unless --keep-connection, so "
            "no dead authority is left behind in ~/.yoke/config.json."
        ),
    )
    parser.add_argument("--dir", dest="directory", default=None)
    parser.add_argument(
        "--destroy-universe", action="store_true",
        help=(
            "Also delete the database volume. This destroys the universe the "
            "server held: every item, event, and credential. Requires consent."
        ),
    )
    parser.add_argument(
        "--remove-images", action="store_true",
        help=(
            "Remove the images this bundle uses. An image another container "
            "still needs is reported and left in place."
        ),
    )
    parser.add_argument(
        "--remove-bundle", action="store_true",
        help=(
            "Delete the bundle's own files, including secrets/ and the "
            "first-boot admin token. Files Yoke did not write are reported "
            "and kept."
        ),
    )
    connection_choice = parser.add_mutually_exclusive_group()
    connection_choice.add_argument(
        "--keep-connection", action="store_true",
        help="Leave this machine's connection entry in place.",
    )
    connection_choice.add_argument(
        "--connection", default=None, metavar="ENV",
        help="Retire this connection instead of matching one by server URL.",
    )
    parser.add_argument(
        "--activate", default=None, metavar="ENV",
        help="Connection to make active when retiring the active authority.",
    )
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--yes", dest="assume_yes", action="store_true")
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, TEARDOWN_USAGE)
    if parsed is None:
        return 2
    try:
        _confirm_destroy_universe(parsed)
        report = teardown.tear_down(
            directory=parsed.directory,
            destroy_universe=parsed.destroy_universe,
            remove_images=parsed.remove_images,
            remove_bundle=parsed.remove_bundle,
            keep_connection=parsed.keep_connection,
            connection=parsed.connection,
            activate=parsed.activate,
            config_path=parsed.config_path,
        )
    except teardown.SelfHostTeardownError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_teardown_summary(report)
    return 0


def _confirm_destroy_universe(parsed) -> None:
    """The one thing teardown cannot undo gets the one consent gate."""
    if not parsed.destroy_universe or parsed.assume_yes:
        return
    if not sys.stdin.isatty():
        raise teardown.SelfHostTeardownError(
            "--destroy-universe deletes the database volume and everything "
            "in it; pass --yes to consent when running non-interactively"
        )
    print("This deletes the database volume and every universe it holds.")
    try:
        response = input(f"Type '{_CONSENT_WORD}' to continue: ")
    except EOFError:
        response = ""
    if response.strip().lower() != _CONSENT_WORD:
        raise teardown.SelfHostTeardownError(
            "teardown cancelled: the database volume was not confirmed"
        )


def _print_teardown_summary(report: Dict[str, object]) -> None:
    print(f"self-host stack removed: {report.get('directory')}")
    universe = report.get("universe_destroyed")
    print(
        "database volume: destroyed"
        if universe
        else "database volume: kept (docker compose up -d restores the universe)"
    )
    for label, key in (
        ("images removed", "images_removed"),
        ("images kept (still in use)", "images_retained"),
        ("bundle files removed", "bundle_files_removed"),
        ("bundle files kept (not written by Yoke)", "bundle_files_retained"),
    ):
        values = report.get(key) or []
        if values:
            print(f"{label}: {len(values)}")
            for value in values:
                print(f"  {value}")
    connection = report.get("connection")
    if isinstance(connection, dict):
        active = connection.get("active_env") or "<none>"
        print(f"connection retired: {connection.get('removed_env')}")
        print(f"active connection now: {active}")
    else:
        print("connection: unchanged")


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("self-host", "teardown"): self_host_teardown,
}


__all__ = [
    "TEARDOWN_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "self_host_teardown",
]
