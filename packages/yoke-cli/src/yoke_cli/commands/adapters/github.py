"""``yoke github`` family adapters (repo-level GitHub surfaces).

Sibling of :mod:`yoke_cli.commands.adapters.github_actions` for the
repo-level ``github.*`` function family. Each adapter dispatches its
function id, which calls into
:mod:`yoke_core.domain.gh_rest_transport` using the project's resolved
GitHub authorization material -- no host GitHub CLI binary required:

- ``pr create`` -> ``github.pr.create`` (open a pull request on the
  project's GitHub repo; owner/repo resolve from the project
  capability, never from a CLI argument).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List, Mapping

from yoke_cli.config import github_machine
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "GITHUB_CONNECT_USAGE",
    "GITHUB_DISCONNECT_USAGE",
    "GITHUB_PR_CREATE_USAGE",
    "GITHUB_STATUS_USAGE",
    "github_connect",
    "github_disconnect",
    "github_pr_create",
    "github_status",
]


GITHUB_CONNECT_USAGE = (
    "yoke github connect [--client-id ID] [--app-slug SLUG] "
    "[--app-id ID] [--api-url URL] [--web-url URL] [--add-installation] "
    "[--config PATH] [--json]"
)


GITHUB_DISCONNECT_USAGE = "yoke github disconnect [--config PATH] [--json]"


GITHUB_STATUS_USAGE = (
    "yoke github status [--config PATH] [--offline] [--json]"
)


GITHUB_PR_CREATE_USAGE = (
    "yoke github pr create --title TITLE --head BRANCH [--base BRANCH] "
    "[--body TEXT | --body-stdin] [--draft] --project P "
    "[--session-id S] [--json]"
)


def github_connect(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github connect",
        description=(
            "Start the machine-level Yoke GitHub App authorization flow. "
            "This never accepts or stores manual GitHub credentials and never writes "
            "project runtime auth."
        ),
    )
    parser.add_argument(
        "--client-id",
        default=None,
        help="Public GitHub App client id (or YOKE_GITHUB_APP_CLIENT_ID).",
    )
    parser.add_argument(
        "--app-slug",
        default=None,
        help="Public GitHub App slug (or YOKE_GITHUB_APP_SLUG).",
    )
    parser.add_argument("--app-id", type=int, default=None)
    parser.add_argument(
        "--add-installation",
        action="store_true",
        help="Open the App installation page to add an account or repositories.",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="GitHub API root (default: https://api.github.com).",
    )
    parser.add_argument(
        "--web-url",
        default=None,
        help="GitHub browser origin (default: https://github.com).",
    )
    parser.add_argument("--config", dest="config_path", default=None)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_CONNECT_USAGE)
    if parsed is None:
        return 2
    try:
        report = github_machine.connect(
            config_path=parsed.config_path,
            client_id=parsed.client_id,
            app_slug=parsed.app_slug,
            app_id=parsed.app_id,
            api_url=parsed.api_url,
            web_url=parsed.web_url,
            add_installation=parsed.add_installation,
            notify=_render_connect_progress,
        )
    except github_machine.GitHubMachineError as exc:
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
    parser.add_argument("--config", dest="config_path", default=None)
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
    parser = argparse.ArgumentParser(prog="yoke github status")
    parser.add_argument("--config", dest="config_path", default=None)
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
        )
    except github_machine.GitHubMachineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(github_machine.dumps_json(report), end="")
    else:
        print(github_machine.render_human(report), end="")
    return 0 if report.get("ok") else 1


def _render_connect_progress(event: Mapping[str, Any]) -> None:
    phase = event.get("phase")
    if phase == "device_authorization":
        print(
            f"Open {event.get('verification_uri')} and enter code "
            f"{event.get('user_code')}",
            file=sys.stderr,
            flush=True,
        )
    elif phase == "device_browser" and not event.get("browser_opened"):
        print(
            f"Browser did not open; use {event.get('verification_uri')} with "
            f"code {event.get('user_code')}",
            file=sys.stderr,
            flush=True,
        )
    elif phase == "github_access_propagation_retry":
        print(
            "GitHub is finishing authorization; retrying the access check in "
            f"{event.get('retry_in_seconds'):g}s...",
            file=sys.stderr,
            flush=True,
        )
    elif phase == "app_installation":
        prefix = "Opened" if event.get("browser_opened") else "Open"
        print(
            f"{prefix} {event.get('install_url')} to install the App and choose repositories.",
            file=sys.stderr,
            flush=True,
        )


def github_pr_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github pr create",
        description=(
            "Open a pull request --head -> --base on the project's "
            "GitHub repo via resolved REST auth (no host gh binary). The "
            "repo is resolved from --project's verified GitHub App binding, "
            "never passed as an argument. "
            "Prints the created PR number + URL."
        ),
    )
    parser.add_argument(
        "--title", required=True, help="Pull-request title.",
    )
    parser.add_argument(
        "--head", required=True,
        help="Branch the changes live on (the PR source branch).",
    )
    parser.add_argument(
        "--base", default="main",
        help="Branch the PR merges into (default: main).",
    )
    body_group = parser.add_mutually_exclusive_group()
    body_group.add_argument(
        "--body", default=None,
        help="Pull-request description (markdown).",
    )
    body_group.add_argument(
        "--body-stdin", dest="body_stdin", action="store_true",
        help=(
            "Read the pull-request description from stdin (for "
            "multi-line bodies): printf '%%s' \"$BODY\" | yoke github "
            "pr create ... --body-stdin."
        ),
    )
    parser.add_argument(
        "--draft", action="store_true", help="Open the PR as a draft.",
    )
    parser.add_argument(
        "--project", required=True,
        help="Project capability owning the GitHub repo.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_PR_CREATE_USAGE)
    if parsed is None:
        return 2

    body = parsed.body
    if parsed.body_stdin:
        body = sys.stdin.read()
        if not body.strip():
            return usage_error(
                "PR body on stdin is empty; pipe it in: "
                f"{GITHUB_PR_CREATE_USAGE}"
            )

    payload: Dict[str, Any] = {
        "title": parsed.title,
        "head": parsed.head,
        "base": parsed.base,
        "draft": parsed.draft,
        "project": parsed.project,
    }
    if body is not None:
        payload["body"] = body
    return dispatch_and_emit(
        function_id="github.pr.create",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
