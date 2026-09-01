"""Tool-shaped self-host bundle lifecycle registry.

These client-local machine operations carry NO dispatcher function id.
Initialization writes a ``docker compose`` working directory on the caller's
machine; upgrade advances its CLI and pinned image as one pair; import securely
streams an archive into the stopped server image. There is no control plane to
dispatch through until the described server is running. These resolve after
``SUBCOMMAND_REGISTRY`` misses, like the other machine-setup families.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.self_host_import import (
    TOOL_SHAPED_SUBCOMMANDS as _IMPORT_SUBCOMMANDS,
    TOOL_SHAPED_USAGE as _IMPORT_USAGE,
)
from yoke_cli.commands._helpers import parse_or_usage_error, usage_error
from yoke_cli.self_host import bundle, first_boot_token, teardown
from yoke_cli.self_host import upgrade
from yoke_contracts.self_host_bootstrap_output import (
    connect_url_from_publish_spec,
)

AdapterFn = Callable[[List[str]], int]

INIT_USAGE = (
    "yoke self-host init [--dir D] [--port N] [--image REF] "
    "[--force | --protect-existing] [--github-app-private-key PATH] [--json]"
)
UPGRADE_USAGE = "yoke self-host upgrade [--dir D] [--channel C] [--yes] [--json]"

TEARDOWN_USAGE = (
    "yoke self-host teardown [--dir D] [--destroy-universe] [--remove-images] "
    "[--remove-bundle] [--keep-connection | --connection ENV] "
    "[--activate ENV] [--yes] [--json]"
)
_CONSENT_WORD = "destroy"

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke self-host init": INIT_USAGE,
    "yoke self-host upgrade": UPGRADE_USAGE,
    "yoke self-host teardown": TEARDOWN_USAGE,
    **_IMPORT_USAGE,
}

_INPUT = input


def self_host_init(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke self-host init",
        description=(
            "Write a runnable self-host bundle: docker-compose.yml (API "
            "server + Postgres), .env (image reference, API publish spec), "
            "and generated database credentials as owner-only secret files. "
            "The generated password is never printed. --protect-existing "
            "instead preserves an existing bundle and its DB credentials "
            "while repairing secret protection or rotating the GitHub App "
            "key. Then `docker compose up -d` from the bundle directory "
            "starts the server; first boot writes a one-time initial admin "
            "token to an owner-only file under the bundle's secrets/ "
            "directory, and prints its path — never the token — to the log."
        ),
    )
    parser.add_argument(
        "--dir",
        dest="directory",
        default=None,
        help=(
            "Bundle directory (default: ./"
            f"{bundle.DEFAULT_BUNDLE_DIR} under the current directory — the "
            "bundle is the operator-managed docker compose working dir)."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help=(
            "Host API port for the loopback publish spec written to .env "
            f"(default {bundle.DEFAULT_API_PORT}). Edit YOKE_API_PUBLISH in "
            ".env to serve beyond loopback."
        ),
    )
    parser.add_argument(
        "--image",
        default=None,
        help=(
            "Exact server image override written to .env (default: the "
            "immutable image matched to this installed CLI release)."
        ),
    )
    rewrite_mode = parser.add_mutually_exclusive_group()
    rewrite_mode.add_argument(
        "--force",
        action="store_true",
        help=(
            "Rewrite an existing bundle, regenerating database credentials. "
            "An already-initialized database volume keeps its original "
            "password, so pair with a fresh volume or keep existing secrets."
        ),
    )
    rewrite_mode.add_argument(
        "--protect-existing",
        action="store_true",
        help=(
            "Idempotently merge Yoke's marked .gitignore protection into an "
            "existing bundle. Preserves docker-compose.yml, .env, and database "
            "credential files; never regenerates database credentials."
        ),
    )
    parser.add_argument(
        "--github-app-private-key",
        default=None,
        metavar="PATH",
        help=(
            "With --protect-existing, validate and atomically install or "
            "rotate a current-owner GitHub App PEM source with no group/world "
            "access (use chmod 600), through a same-directory owner-only temp "
            "file."
        ),
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, INIT_USAGE)
    if parsed is None:
        return 2
    if parsed.github_app_private_key and not parsed.protect_existing:
        return usage_error(
            "--github-app-private-key requires --protect-existing so the "
            "existing bundle and database credentials are preserved"
        )
    if parsed.protect_existing and (
        parsed.port is not None or parsed.image is not None
    ):
        return usage_error(
            "--protect-existing preserves .env; do not combine it with "
            "--port or --image"
        )
    try:
        if parsed.protect_existing:
            report = bundle.protect_existing_bundle(
                directory=parsed.directory,
                github_app_private_key=parsed.github_app_private_key,
            )
        else:
            report = bundle.write_bundle(
                directory=parsed.directory,
                port=parsed.port,
                image=parsed.image,
                force=parsed.force,
            )
    except bundle.SelfHostBundleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_summary(report)
    return 0


def self_host_upgrade(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke self-host upgrade",
        description=(
            "Preview and deliberately advance one self-host installation as a "
            "pair: install the selected Yoke CLI release, replace the bundle's "
            "immutable server-image pin, pull it, and restart Compose."
        ),
    )
    parser.add_argument(
        "--dir",
        dest="directory",
        default=None,
        help=f"Existing bundle directory (default: ./{bundle.DEFAULT_BUNDLE_DIR}).",
    )
    parser.add_argument(
        "--channel",
        default=None,
        help="Published release channel (default: stable or YOKE_CHANNEL).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Accept the displayed plan without an interactive confirmation.",
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, UPGRADE_USAGE)
    if parsed is None:
        return 2
    if parsed.json_mode and not parsed.yes:
        return usage_error("--json requires --yes so stdout remains one JSON result")
    try:
        plan = upgrade.plan_upgrade(
            directory=parsed.directory,
            channel=parsed.channel,
        )
    except upgrade.SelfHostUpgradeError as exc:
        _print_upgrade_error(exc)
        return 1
    if not parsed.json_mode:
        _print_upgrade_preview(plan)
    if not parsed.yes:
        try:
            answer = _INPUT("Type 'upgrade' to continue: ").strip()
        except EOFError:
            answer = ""
        if answer != "upgrade":
            print("self-host upgrade cancelled; no changes were made")
            return 0
    try:
        report = upgrade.execute_upgrade(plan)
    except upgrade.SelfHostUpgradeError as exc:
        _print_upgrade_error(exc)
        return 1
    if parsed.json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_upgrade_summary(report)
    return 0


def _print_summary(report: Dict[str, object]) -> None:
    directory = report.get("directory")
    if report.get("mode") == "protect-existing":
        print(f"self-host bundle protected: {directory}")
        state = "updated" if report.get("gitignore_changed") else "already current"
        print(f"secret ignore rules: {state}")
        print("database credentials: preserved (not regenerated)")
        if report.get("github_app_private_key_installed"):
            print("GitHub App private key: installed atomically as mode 0600")
        return
    print(f"self-host bundle written: {directory}")
    print(f"server image: {report.get('image')}")
    print(f"api publish: {report.get('publish')}")
    token_file = first_boot_token.token_drop_path(str(directory))
    connect_url = connect_url_from_publish_spec(str(report.get("publish") or ""))
    print("next steps:")
    print(f"  1. cd {directory} && docker compose up -d")
    print("  2. first boot writes a one-time initial admin token to:")
    print(f"       {token_file}")
    print("  3. connect this machine's CLI, then remove that file:")
    print(f"       yoke connect {connect_url} --token-stdin < {token_file}")


def _print_upgrade_preview(plan: upgrade.UpgradePlan) -> None:
    print("self-host paired upgrade preview (no changes made):")
    print(f"  bundle: {plan.directory}")
    print(f"  current server image: {plan.previous_image}")
    print(f"  target release: {plan.target.version} ({plan.target.channel})")
    print(f"  target server image: {plan.target.image}")
    for index, step in enumerate(plan.steps, start=1):
        print(f"  {index}. {step}")


def _print_upgrade_summary(report: Dict[str, object]) -> None:
    print(f"self-host pair upgraded: {report.get('version')}")
    print(f"bundle: {report.get('directory')}")
    print(f"server image: {report.get('image')}")
    print("CLI, image pin, pull, and Compose restart all completed")


def _print_upgrade_error(error: upgrade.SelfHostUpgradeError) -> None:
    print(f"error [{error.code}]: {error}", file=sys.stderr)
    for line in error.detail_lines:
        print(f"  {line}", file=sys.stderr)
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
    ("self-host", "init"): self_host_init,
    ("self-host", "upgrade"): self_host_upgrade,
    ("self-host", "teardown"): self_host_teardown,
    **_IMPORT_SUBCOMMANDS,
}


__all__ = [
    "TEARDOWN_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "self_host_init",
    "self_host_upgrade",
    "self_host_teardown",
]
