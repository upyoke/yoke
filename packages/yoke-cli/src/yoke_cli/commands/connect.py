"""Tool-shaped ``yoke connect URL`` command.

Client-local machine operation with NO dispatcher function id: it
verifies a Yoke API server and writes this machine's config to point at
it — there is no active connection to dispatch through while attaching.
Resolves via the tool-shaped table after SUBCOMMAND_REGISTRY misses.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error, usage_error
from yoke_cli.config import secrets as machine_secrets
from yoke_cli.config import server_connect

AdapterFn = Callable[[List[str]], int]

CONNECT_USAGE = (
    "yoke connect URL [--name ENV] (--token-file PATH | --token-stdin) "
    "[--no-activate] [--config PATH] [--json]"
)

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke connect": CONNECT_USAGE,
}


def connect(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke connect",
        description=(
            "Attach this machine to a Yoke API server: verify the server "
            "(GET /v1/health) and the token (GET /v1/auth/identity), then "
            "write an https connection entry plus an owner-only token "
            "secret file, and make it the active env. Nothing is persisted "
            "when verification fails. Scheme policy: https:// is the "
            "normal shape and is required for every network server. Plain "
            "http:// is accepted only for a numeric loopback endpoint "
            "(for example, http://127.0.0.1:8765). Other schemes and "
            "non-loopback plaintext endpoints are refused."
        ),
    )
    parser.add_argument("url", help="Server URL, e.g. https://yoke.internal")
    parser.add_argument(
        "--name",
        dest="env",
        default=server_connect.DEFAULT_ENV_NAME,
        help=(
            "Machine-config env label for the connection entry (default "
            f"{server_connect.DEFAULT_ENV_NAME!r})."
        ),
    )
    parser.add_argument(
        "--token-file",
        dest="token_file",
        default=None,
        help="Read the actor token from this file.",
    )
    parser.add_argument(
        "--token-stdin",
        dest="token_stdin",
        action="store_true",
        help="Read the actor token from stdin (keeps it out of shell history).",
    )
    parser.add_argument(
        "--no-activate",
        dest="no_activate",
        action="store_true",
        help="Write the connection entry without switching active_env to it.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Machine config path override.",
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, CONNECT_USAGE)
    if parsed is None:
        return 2
    if bool(parsed.token_file) == bool(parsed.token_stdin):
        return usage_error(
            "exactly one token source is required (--token-file PATH or "
            f"--token-stdin): {CONNECT_USAGE}"
        )
    try:
        token = (
            machine_secrets.read_secret_file(parsed.token_file, "token")
            if parsed.token_file
            else machine_secrets.read_stdin_secret("token")
        )
    except machine_secrets.MachineSecretError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    try:
        report = server_connect.connect_server(
            parsed.url,
            token=token,
            env=parsed.env,
            activate=not parsed.no_activate,
            config_path=parsed.config_path,
        )
    except server_connect.ServerConnectError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_summary(report)
    return 0


def _print_summary(report: Dict[str, object]) -> None:
    print(f"connected: {report.get('api_url')} (env {report.get('env')})")
    identity = report.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    actor = identity.get("actor")
    actor = actor if isinstance(actor, dict) else {}
    if actor.get("label") or actor.get("id") is not None:
        print(f"actor: {actor.get('label')} (id={actor.get('id')})")
    health = report.get("health")
    health = health if isinstance(health, dict) else {}
    if health.get("build"):
        print(f"server build: {health.get('build')}")
    if report.get("activated"):
        print(f"active env: {report.get('env')}")
    else:
        print(
            f"connection written without activation; switch later with "
            f"`yoke env use {report.get('env')}`"
        )
    print("verify anytime with `yoke status`")


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("connect",): connect,
}


__all__ = [
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "connect",
]
