"""``yoke github`` family adapters (repo-level GitHub surfaces).

Sibling of :mod:`yoke_cli.commands.adapters.github_actions` for the
repo-level ``github.*`` function family. Each adapter dispatches its
function id, which calls into
:mod:`yoke_core.domain.gh_rest_transport` using the project's stored
PAT — no host GitHub CLI binary required:

- ``pr create`` -> ``github.pr.create`` (open a pull request on the
  project's GitHub repo; owner/repo resolve from the project
  capability, never from a CLI argument).
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, Dict, List

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
    "GITHUB_PR_CREATE_USAGE",
    "GITHUB_STATUS_USAGE",
    "github_connect",
    "github_pr_create",
    "github_status",
]


GITHUB_CONNECT_USAGE = (
    "yoke github connect [TOKEN | --token-file PATH | --token-stdin] "
    "[--github-repo OWNER/REPO] [--api-url URL] [--config PATH] [--json]"
)


GITHUB_STATUS_USAGE = (
    "yoke github status [--github-repo OWNER/REPO] [--config PATH] "
    "[--api-url URL] [--offline] [--json]"
)


GITHUB_PR_CREATE_USAGE = (
    "yoke github pr create --title TITLE --head BRANCH [--base BRANCH] "
    "[--body TEXT | --body-stdin] [--draft] [--project P] "
    "[--session-id S] [--json]"
)


def github_connect(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github connect",
        description=(
            "Validate and store a machine-level GitHub token in Yoke "
            "machine secrets. "
            "This never writes project runtime auth or promotes the token into "
            "a project GitHub capability."
        ),
    )
    parser.add_argument("token", nargs="?", help="GitHub PAT to import.")
    parser.add_argument("--token-file", default=None)
    parser.add_argument(
        "--token-stdin",
        action="store_true",
        help="Read the GitHub PAT from stdin.",
    )
    parser.add_argument(
        "--api-url",
        default=None,
        help="GitHub API root (default: https://api.github.com).",
    )
    parser.add_argument(
        "--github-repo",
        dest="github_repo",
        default=None,
        help="Verify access to OWNER/REPO before storing the token.",
    )
    parser.add_argument("--config", dest="config_path", default=None)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_CONNECT_USAGE)
    if parsed is None:
        return 2
    token_sources = [
        bool(parsed.token),
        bool(parsed.token_file),
        bool(parsed.token_stdin),
    ]
    if sum(1 for given in token_sources if given) != 1:
        return usage_error(
            "exactly one GitHub token source is required: "
            f"{GITHUB_CONNECT_USAGE}"
        )
    token = parsed.token
    token_source_kind = "argument"
    if parsed.token_stdin:
        token = sys.stdin.read().strip()
        token_source_kind = "stdin"
        if not token:
            return usage_error(
                "GitHub token on stdin is empty; pipe it in: "
                f"{GITHUB_CONNECT_USAGE}"
            )
    try:
        report = github_machine.connect(
            config_path=parsed.config_path,
            token=token,
            token_file=parsed.token_file,
            token_source_kind=token_source_kind,
            api_url=parsed.api_url,
            github_repo=parsed.github_repo,
        )
    except github_machine.GitHubMachineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(github_machine.dumps_json(report), end="")
    else:
        print(github_machine.render_human(report), end="")
    return 0


def github_status(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke github status")
    parser.add_argument("--config", dest="config_path", default=None)
    parser.add_argument("--api-url", default=None)
    parser.add_argument(
        "--github-repo",
        dest="github_repo",
        default=None,
        help="Verify access to OWNER/REPO with the stored machine token.",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Read config and token-file presence without calling GitHub.",
    )
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_STATUS_USAGE)
    if parsed is None:
        return 2
    try:
        report = github_machine.status(
            config_path=parsed.config_path,
            api_url=parsed.api_url,
            check=not parsed.offline,
            github_repo=parsed.github_repo,
        )
    except github_machine.GitHubMachineError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(github_machine.dumps_json(report), end="")
    else:
        print(github_machine.render_human(report), end="")
    return 0 if report.get("ok") else 1


def github_pr_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github pr create",
        description=(
            "Open a pull request --head -> --base on the project's "
            "GitHub repo via PAT-backed REST (no host gh binary). The "
            "repo is resolved from --project's GitHub capability "
            "(projects.github_repo), never passed as an argument. "
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
        "--project", default="yoke",
        help="Project capability owning the GitHub repo + PAT (default: yoke).",
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
