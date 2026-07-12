"""Tool-shaped self-host bundle initialization and import registry.

These client-local machine operations carry NO dispatcher function id.
Initialization writes a ``docker compose`` working directory on the caller's
machine; import securely streams an archive into that bundle's stopped server
image. There is no control plane to dispatch through until the described
server is running. Both resolve through the tool-shaped table after
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
from yoke_cli.self_host import bundle

AdapterFn = Callable[[List[str]], int]

INIT_USAGE = (
    "yoke self-host init [--dir D] [--port N] [--image REF] "
    "[--force | --protect-existing] [--github-app-private-key PATH] [--json]"
)

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke self-host init": INIT_USAGE,
    **_IMPORT_USAGE,
}


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
            "starts the server; first boot prints a one-time initial admin "
            "token to the core service log."
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
            "Server image reference written to .env (default: the published "
            "server image)."
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
    print("next steps:")
    print(f"  1. cd {directory} && docker compose up -d")
    print("  2. first boot prints a one-time initial admin token:")
    print("       docker compose logs core")
    print("  3. connect this machine's CLI (paste the token on stdin):")
    print(f"       yoke connect http://{report.get('publish')} --token-stdin")


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("self-host", "init"): self_host_init,
    **_IMPORT_SUBCOMMANDS,
}


__all__ = [
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "self_host_init",
]
