"""Tool-shaped ``yoke self-host init`` command.

Client-local machine operation with NO dispatcher function id: it writes
a ``docker compose`` working directory on the caller's own machine, so
there is no control plane to dispatch through until the server it
describes is running. Resolves via the tool-shaped table after
SUBCOMMAND_REGISTRY misses, like the other machine-setup families.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.self_host import bundle

AdapterFn = Callable[[List[str]], int]

INIT_USAGE = (
    "yoke self-host init [--dir D] [--port N] [--image REF] [--force] [--json]"
)

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke self-host init": INIT_USAGE,
}


def self_host_init(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke self-host init",
        description=(
            "Write a runnable self-host bundle: docker-compose.yml (API "
            "server + Postgres), .env (image reference, API publish spec), "
            "and generated database credentials as owner-only secret files. "
            "The generated password is never printed. Then `docker compose "
            "up -d` from the bundle directory starts the server; first boot "
            "prints a one-time initial admin token to the core service log."
        ),
    )
    parser.add_argument(
        "--dir", dest="directory", default=None,
        help=(
            "Bundle directory (default: ./"
            f"{bundle.DEFAULT_BUNDLE_DIR} under the current directory — the "
            "bundle is the operator-managed docker compose working dir)."
        ),
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help=(
            "Host API port for the loopback publish spec written to .env "
            f"(default {bundle.DEFAULT_API_PORT}). Edit YOKE_API_PUBLISH in "
            ".env to serve beyond loopback."
        ),
    )
    parser.add_argument(
        "--image", default=None,
        help=(
            "Server image reference written to .env (default: the published "
            "server image)."
        ),
    )
    parser.add_argument(
        "--force", action="store_true",
        help=(
            "Rewrite an existing bundle, regenerating database credentials. "
            "An already-initialized database volume keeps its original "
            "password, so pair with a fresh volume or keep existing secrets."
        ),
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, INIT_USAGE)
    if parsed is None:
        return 2
    try:
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
}


__all__ = [
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "self_host_init",
]
