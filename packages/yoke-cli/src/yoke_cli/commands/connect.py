"""Attach this machine through the tool-shaped command, without a dispatcher."""

from __future__ import annotations

import argparse
import urllib.parse
import json
import platform
import sys
from typing import Callable, Dict, List, Tuple

from yoke_contracts.private_network_http import PRIVATE_HTTP_WARNING

from yoke_cli.commands._helpers import parse_or_usage_error, usage_error
from yoke_cli.config import secrets as machine_secrets
from yoke_cli.config import hosted_machine_authorization
from yoke_cli.config import server_connect, team_server_authorization, setup_browser
from yoke_cli.transport.dispatcher import _resolve_session_id
from yoke_cli.config import teammate_invite_redemption
from yoke_cli.config.local_reachability import (
    active_connection_is_local,
    LOCAL_REACHABILITY_NOTICE,
)
from yoke_contracts.api_urls import HOSTED_PLATFORM_URL, HOSTED_STAGE_PLATFORM_URL
from yoke_contracts.designed_wait import announce_designed_wait, poll_every
from yoke_contracts.machine_authorization import (
    MATCH_CODE_LABEL,
    retired_identity_notice,
)
from yoke_contracts.harness_sandbox_recovery import running_harness_family

AdapterFn = Callable[[List[str]], int]

CONNECT_USAGE = (
    "yoke connect [URL] [--name ENV] [--token-file PATH | --token-stdin | --invite-code-stdin] "
    "[--no-activate] [--config PATH] [--json]"
)

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke connect": CONNECT_USAGE,
}


def connect(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke connect",
        usage=CONNECT_USAGE,
        description=(
            "Check the server's health and identity, then save the connection "
            "and a credential file only you can read. If the check fails, "
            "nothing is saved. Sign in by browser approval, a teammate invite "
            "code, or an explicit token. Plain HTTP works only for loopback, "
            "private IPs and *.ts.net, and warns that a network address sends "
            "the token unencrypted; public HTTP is refused, so use HTTPS. In a "
            "person's terminal the approval link opens after a notice; agent, "
            "non-terminal and --json runs only print it. With --json, the link, "
            "code and instructions arrive as JSON lines on stderr before "
            "waiting; show them to the person."
        ),
    )
    parser.add_argument(
        "url",
        nargs="?",
        default=None,
        metavar="URL",
        help=(
            "Hosted platform URL for browser sign-in, or a self-hosted server "
            "URL: approve the printed code by company sign-in (when configured) "
            "or from your own machine already connected to it, or pass an "
            "explicit API token. Omit it for ordinary production hosted browser "
            "sign-in."
        ),
    )
    parser.add_argument(
        "--name",
        dest="env",
        default=None,
        metavar="ENV",
        help=(
            "Name for this connection in the machine config. Hosted sign-in defaults to the selected "
            "organization slug; explicit server sign-in defaults to "
            f"{server_connect.DEFAULT_ENV_NAME!r}."
        ),
    )
    parser.add_argument(
        "--token-file",
        dest="token_file",
        default=None,
        metavar="PATH",
        help="Read the API token from this file.",
    )
    parser.add_argument(
        "--token-stdin",
        dest="token_stdin",
        action="store_true",
        help="Read the API token from stdin (keeps it out of shell history).",
    )
    parser.add_argument(
        "--no-activate",
        dest="no_activate",
        action="store_true",
        help="Save the connection without making it the active one.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        metavar="PATH",
        help="Machine config file to use instead of the default.",
    )
    parser.add_argument(
        "--json", dest="json_mode", action="store_true", help="Print JSON."
    )
    parser.add_argument(
        "--invite-code-stdin",
        action="store_true",
        help="Read a teammate invite code privately from stdin.",
    )
    parsed = parse_or_usage_error(parser, args, CONNECT_USAGE)
    if parsed is None:
        return 2
    if (
        sum(
            bool(value)
            for value in (
                parsed.token_file,
                parsed.token_stdin,
                parsed.invite_code_stdin,
            )
        )
        > 1
    ):
        return usage_error(
            f"use at most one token or invite-code source: {CONNECT_USAGE}"
        )
    explicit_token = bool(parsed.token_file or parsed.token_stdin)
    if (explicit_token or parsed.invite_code_stdin) and not parsed.url:
        return usage_error(
            f"a server URL is required with an explicit token or invite code: {CONNECT_USAGE}"
        )
    hosted_platform_urls = {
        HOSTED_PLATFORM_URL.rstrip("/"),
        HOSTED_STAGE_PLATFORM_URL.rstrip("/"),
    }
    parsed.self_host = bool(
        parsed.url and parsed.url.rstrip("/") not in hosted_platform_urls
    )
    if parsed.url:
        try:
            parsed.url = server_connect._normalized_api_url(parsed.url)
        except server_connect.ServerConnectError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if urllib.parse.urlsplit(
            parsed.url
        ).scheme == "http" and not server_connect._is_loopback(parsed.url):
            print(PRIVATE_HTTP_WARNING, file=sys.stderr)
    if active_connection_is_local(parsed.config_path):
        print(LOCAL_REACHABILITY_NOTICE, file=sys.stderr)
    offer_invite = False
    if not explicit_token and parsed.self_host:
        try:
            methods = team_server_authorization.sign_in_methods(parsed.url)
        except hosted_machine_authorization.HostedMachineAuthorizationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        if not methods.device_code:
            return usage_error(
                "machine_approval_unavailable: this server predates machine "
                "approval without company sign-in; upgrade it, or connect with "
                "--token-file PATH or --token-stdin: " + CONNECT_USAGE
            )
        offer_invite = not methods.company_sign_in
    try:
        parsed.invite_code = teammate_invite_redemption.choose_code(
            from_stdin=parsed.invite_code_stdin,
            offer_choice=offer_invite,
        )
    except hosted_machine_authorization.HostedMachineAuthorizationCancelled:
        return 0
    except hosted_machine_authorization.HostedMachineAuthorizationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
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
        browser: hosted_machine_authorization.BrowserOpenResult,
    ) -> None:
        stream = sys.stderr if parsed.json_mode else sys.stdout
        if pending.retired_machine_id and not parsed.json_mode:
            print(retired_identity_notice(pending.retired_machine_id), file=stream)
        if parsed.json_mode:
            setup_browser.render_progress(
                {
                    "phase": "machine_authorization",
                    **(
                        {"retired_machine_id": pending.retired_machine_id}
                        if pending.retired_machine_id
                        else {}
                    ),
                    "browser_attempted": browser.attempted,
                    "browser_action": setup_browser.action(
                        pending.verification_uri_complete,
                        "Sign in, approve this machine, then return to the agent.",
                        user_code=pending.user_code,
                    ),
                    "expires_in": pending.expires_in,
                    "interval": pending.interval,
                },
                json_mode=True,
            )
            return
        print(f"Open {pending.verification_uri_complete}", file=stream)
        print(f"{MATCH_CODE_LABEL} {pending.user_code}", file=stream)
        print(
            "Approve it from a machine already connected to this server: "
            f"`yoke machines approve {pending.user_code}`, or Approve under "
            "Machines → Waiting for approval.",
            file=stream,
        )
        if browser.attempted and not browser.opened:
            print(
                f"The browser did not open ({browser.reason}); open the URL above "
                "yourself.",
                file=stream,
            )
        announce_designed_wait(
            f"browser approval of code {pending.user_code}",
            max_wait_seconds=pending.expires_in,
            cadence=poll_every(pending.interval),
            write=lambda line: print(line, file=stream, flush=True),
        )

    def _open_browser(url: str) -> hosted_machine_authorization.BrowserOpenResult:
        print(setup_browser.OPENING_NOTICE, flush=True)
        print(f"Open {url}", flush=True)
        return setup_browser.open_url(url)

    human_terminal = (
        not parsed.json_mode
        and sys.stdin.isatty()
        and sys.stdout.isatty()
        and not _resolve_session_id()
        and running_harness_family() is None
    )
    try:
        if getattr(parsed, "invite_code", None):
            credential = teammate_invite_redemption.redeem(
                platform_url,
                parsed.invite_code,
                machine={
                    **hosted_machine_authorization._machine_identity(),
                    "platform": platform.system(),
                },
            )
        else:
            credential = hosted_machine_authorization.authorize(
                platform_url,
                notify=_notify,
                browser_open=_open_browser if human_terminal else None,
                self_host=parsed.self_host,
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
        if getattr(parsed, "invite_code", None):
            print(teammate_invite_redemption.LOST_DELIVERY, file=sys.stderr)
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
