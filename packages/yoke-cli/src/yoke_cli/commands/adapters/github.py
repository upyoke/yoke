"""``yoke github`` family adapters (repo-level GitHub surfaces).

Sibling of :mod:`yoke_cli.commands.adapters.github_actions` for the
repo-level ``github.*`` function family. Each adapter dispatches its
function id, which calls into
:mod:`yoke_core.domain.gh_rest_transport` using the project's resolved
GitHub authorization material -- no host GitHub CLI binary required:

Machine authorization commands connect, disconnect and inspect access.
"""

from __future__ import annotations

import argparse
import sys
from typing import List

from yoke_cli.config import (
    github_app_public_profile,
    github_machine,
    github_merge_path_binding,
    setup_browser,
)
from yoke_cli.commands._helpers import (
    add_json_arg,
    parse_or_usage_error,
)


__all__ = [
    "GITHUB_CONNECT_USAGE",
    "GITHUB_DISCONNECT_USAGE",
    "GITHUB_STATUS_USAGE",
    "github_connect",
    "github_disconnect",
    "github_status",
]


GITHUB_CONNECT_USAGE = (
    "yoke github connect [--replace] [--add-installation] [--config PATH] [--json] "
    "[local/self-host bring-your-own App: --client-id ID --app-slug SLUG "
    "--app-id ID --api-url URL --web-url URL]"
)


GITHUB_DISCONNECT_USAGE = "yoke github disconnect [--config PATH] [--json]"


GITHUB_STATUS_USAGE = "yoke github status [--config PATH] [--offline] [--json]"


def github_connect(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github connect",
        description=(
            "Start the for the selected Yoke connection (--env) Yoke GitHub App authorization flow. "
            "An HTTPS Yoke service advertises its App identity; the local Yoke "
            "product offers an optional bundled upyoke-owned profile. Installing "
            "that App grants its owner access within the repositories selected "
            "on GitHub. Local and self-host operators may instead bring their "
            "own App with one complete five-field profile. "
            "This never accepts or stores manual GitHub credentials. "
            "No browser is opened; present the link and code to the person. "
            "--json emits authorization progress as JSON lines on stderr before polling."
        ),
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help=(
            "Local/self-host App profile; provide together with app slug, "
            "app id, API URL, and web URL."
        ),
    )
    parser.add_argument(
        "--app-slug",
        default=None,
        help="Local/self-host App profile; requires the other four App fields.",
    )
    parser.add_argument(
        "--app-id",
        type=int,
        default=None,
        help="Local/self-host App profile; requires the other four App fields.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help=(
            "Explicitly replace an existing authorization, including one for "
            "a different App profile, only after the new access is verified."
        ),
    )
    parser.add_argument(
        "--add-installation",
        action="store_true",
        help="Open the App installation page to add an account or repositories.",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="Local/self-host App profile; requires the other four App fields.",
    )
    parser.add_argument(
        "--web-url",
        default=None,
        help="Local/self-host App profile; requires the other four App fields.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Machine config file to use; default: the standard one.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_CONNECT_USAGE)
    if parsed is None:
        return 2
    try:
        explicit_profile = any(
            (
                parsed.client_id,
                parsed.app_slug,
                parsed.app_id,
                parsed.api_url,
                parsed.web_url,
            )
        )
        report = github_machine.connect(
            config_path=parsed.config_path,
            client_id=parsed.client_id,
            app_slug=parsed.app_slug,
            app_id=parsed.app_id,
            api_url=parsed.api_url,
            web_url=parsed.web_url,
            service_api_url=(
                None
                if explicit_profile
                else github_app_public_profile.selected_https_service_api_url(
                    parsed.config_path
                )
            ),
            replace_profile=parsed.replace,
            add_installation=parsed.add_installation,
            notify=lambda event: setup_browser.render_progress(
                event, json_mode=parsed.json_mode
            ),
        )
    except (
        github_machine.GitHubMachineError,
        github_app_public_profile.GitHubAppPublicProfileError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(github_machine.dumps_json(report), end="")
    else:
        print(github_machine.render_human(report), end="")
    return 0 if report.get("ok") else 1


def github_disconnect(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github disconnect",
        description=(
            "Remove this machine's GitHub App user authorization. This does "
            "not uninstall the App or change repository access on GitHub."
        ),
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Machine config file to use; default: the standard one.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_DISCONNECT_USAGE)
    if parsed is None:
        return 2
    try:
        report = github_machine.disconnect(config_path=parsed.config_path)
    except github_machine.GitHubMachineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(github_machine.dumps_json(report), end="")
    else:
        print("GitHub App authorization removed from this machine.\n")
        for issue in report.get("issues") or []:
            print(
                f"warning: {issue.get('message') or issue.get('code')}",
                file=sys.stderr,
            )
    return 0 if report.get("ok") else 1


def github_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github status",
        description=(
            "Report this machine's GitHub App bindings. The live check pins "
            "the same Yoke connection a local merge authorizes through and "
            "reads a user token the same way, then reports one verdict per "
            "binding: user authorization for the merge path (ok/busy/broken) "
            "and App installation access (ok/broken). `ready` is true only "
            "when both are proven ok, so --offline never reports ready. A "
            "third binding reports the stored access token git commands "
            "actually present and when it next renews; it is read locally, "
            "rotates nothing, and so never breaks a push in flight."
        ),
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Machine config file to use; default: the standard one.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Read local config without attempting live GitHub checks.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_STATUS_USAGE)
    if parsed is None:
        return 2
    try:
        report = github_machine.status(
            config_path=parsed.config_path,
            check=not parsed.offline,
            **github_merge_path_binding.status_connection_scope(parsed.config_path),
        )
    except github_machine.GitHubMachineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(github_machine.dumps_json(report), end="")
    else:
        print(github_machine.render_human(report), end="")
    return 0 if report.get("ok") else 1
