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
from yoke_cli.config import hosted_machine_authorization
from yoke_cli.config import server_connect
from yoke_contracts.api_urls import HOSTED_PLATFORM_URL, HOSTED_STAGE_PLATFORM_URL

AdapterFn = Callable[[List[str]], int]

CONNECT_USAGE = (
    "yoke connect [URL] [--name ENV] [--token-file PATH | --token-stdin] "
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
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        help=(
            "Hosted platform URL for browser sign-in, or a self-hosted server "
            "URL when using an explicit token. Omit it for ordinary production "
            "hosted browser sign-in."
        ),
    )
    parser.add_argument(
        "--name",
        dest="env",
        default=None,
        help=(
            "Machine-config env label. Hosted sign-in defaults to the selected "
            "organization slug; explicit server sign-in defaults to "
            f"{server_connect.DEFAULT_ENV_NAME!r}."
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
    if parsed.token_file and parsed.token_stdin:
        return usage_error(
            "use at most one token source (--token-file PATH or "
            f"--token-stdin): {CONNECT_USAGE}"
        )
    explicit_token = bool(parsed.token_file or parsed.token_stdin)
    if explicit_token and not parsed.url:
        return usage_error(
            f"a server URL is required with an explicit token: {CONNECT_USAGE}"
        )
    hosted_platform_urls = {
        HOSTED_PLATFORM_URL.rstrip("/"),
        HOSTED_STAGE_PLATFORM_URL.rstrip("/"),
    }
    if (
        not explicit_token
        and parsed.url
        and parsed.url.rstrip("/") not in hosted_platform_urls
    ):
        return usage_error(
            "use an official hosted platform URL for browser sign-in, or "
            "provide --token-file/--token-stdin for a self-hosted server: "
            f"{CONNECT_USAGE}"
        )
    if not explicit_token:
        return _connect_hosted(parsed)
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
            env=parsed.env or server_connect.DEFAULT_ENV_NAME,
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


def _connect_hosted(parsed: argparse.Namespace) -> int:
    platform_url = parsed.url or HOSTED_PLATFORM_URL

    def _notify(
        pending: hosted_machine_authorization.PendingMachineAuthorization,
        opened: bool,
    ) -> None:
        stream = sys.stderr if parsed.json_mode else sys.stdout
        print(f"Open {pending.verification_uri}", file=stream)
        print(f"Enter code: {pending.user_code}", file=stream)
        if not opened:
            print(f"Browser URL: {pending.verification_uri_complete}", file=stream)
        print("Waiting for browser approval…", file=stream)

    try:
        credential = hosted_machine_authorization.authorize(
            platform_url,
            notify=_notify,
        )
        report = server_connect.connect_server(
            credential.api_url,
            token=credential.token,
            env=parsed.env or credential.org,
            activate=not parsed.no_activate,
            config_path=parsed.config_path,
        )
    except (
        hosted_machine_authorization.HostedMachineAuthorizationError,
        server_connect.ServerConnectError,
    ) as exc:
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
