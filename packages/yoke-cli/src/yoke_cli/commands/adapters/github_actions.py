"""``yoke github-actions`` family adapters.

Atlas-unified bearer-token GitHub Actions surfaces. Each adapter
dispatches its function id, which calls into
:mod:`yoke_core.domain.gh_rest_transport` using the project's stored
GitHub App auth — no host GitHub CLI binary required:

- ``check-ci`` -> ``github_actions.check_ci`` (main-branch advisory;
  ``--wait`` / ``--timeout`` poll CLIENT-side until the run completes —
  each poll is one single-shot dispatch, so the wait works identically
  in-process and over the https relay).
- ``secret set`` -> ``github_actions.secret.set`` (sealed-box repo
  secret create-or-update; direct value by default, file/stdin optional).
- ``secret delete`` -> ``github_actions.secret.delete`` (audited retirement).
- ``variable get`` -> ``github_actions.variable.get`` (read-only
  arming-gate probe)
- ``variable set`` -> ``github_actions.variable.set`` (repo variable
  upsert; plaintext value flag).
- ``variable delete`` -> ``github_actions.variable.delete`` (audited retirement).
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any, Dict, List

from yoke_cli.config import secrets as machine_secrets
from yoke_cli.commands.adapters.github_actions_wait import (
    wait_for_ci_completion,
)
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "github_actions_check_ci",
    "github_actions_secret_set",
    "github_actions_variable_get",
    "github_actions_variable_set",
    "GITHUB_ACTIONS_CHECK_CI_USAGE",
    "GITHUB_ACTIONS_SECRET_SET_USAGE",
    "GITHUB_ACTIONS_VARIABLE_SET_USAGE",
]


GITHUB_ACTIONS_CHECK_CI_USAGE = (
    "yoke github-actions check-ci <repo-slug> <workflow-file> "
    "[--branch BRANCH] [--wait] [--timeout SEC] --project P "
    "[--session-id S] [--json]"
)


def github_actions_check_ci(args: List[str]) -> int:
    default_timeout = _default_timeout_seconds()
    parser = argparse.ArgumentParser(
        prog="yoke github-actions check-ci",
        description=(
            "Latest workflow-run advisory for <repo-slug> <workflow-file> "
            "on --branch (default main). Point-in-time by default; "
            "--wait polls client-side until the run completes or "
            "--timeout elapses (state 'timeout') — each poll is one "
            "single-shot dispatch, so waiting works over the https "
            "relay too. bearer-token REST; no host gh binary required."
        ),
    )
    parser.add_argument("repo", help="GitHub repo slug, e.g. upyoke/yoke.")
    parser.add_argument("workflow", help="Workflow filename, e.g. ci.yml.")
    parser.add_argument(
        "--branch", default="main",
        help="Branch to inspect (default: main).",
    )
    parser.add_argument(
        "--wait", action="store_true",
        help=(
            "Poll until the latest run completes instead of returning "
            "the point-in-time state."
        ),
    )
    parser.add_argument(
        "--timeout", type=int, default=default_timeout,
        dest="timeout_sec", metavar="SEC",
        help=(
            "Wait budget in seconds when --wait is set "
            f"(default: {default_timeout})."
        ),
    )
    parser.add_argument(
        "--project", required=True,
        help="Project capability owning the GitHub App repo binding.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_CHECK_CI_USAGE)
    if parsed is None:
        return 2

    if "/" not in parsed.repo:
        return usage_error(
            f"repo must be owner/name, got {parsed.repo!r}"
        )

    payload: Dict[str, Any] = {
        "repo": parsed.repo,
        "workflow": parsed.workflow,
        "branch": parsed.branch,
        "project": parsed.project,
    }
    if not parsed.wait:
        return dispatch_and_emit(
            function_id="github_actions.check_ci",
            target=TargetRef(kind="global"),
            payload=payload,
            session_id=parsed.session_id,
            json_mode=parsed.json_mode,
        )
    return wait_for_ci_completion(
        payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        timeout_sec=parsed.timeout_sec,
    )


def _default_timeout_seconds() -> int:
    module = importlib.import_module("yoke_core.domain.github_actions_run_monitoring")
    return int(module.CHECK_CI_DEFAULT_TIMEOUT_SEC)


GITHUB_ACTIONS_SECRET_SET_USAGE = (
    "yoke github-actions secret set <repo-slug> <secret-name> "
    "[VALUE | --value-file PATH | --value-stdin] "
    "--project P [--session-id S] [--json]"
)


def _add_repo_name_project(
    parser: argparse.ArgumentParser, *, noun: str, example: str,
) -> None:
    parser.add_argument("repo", help="GitHub repo slug, e.g. upyoke/yoke.")
    parser.add_argument("name", help=f"Actions {noun} name, e.g. {example}.")
    parser.add_argument(
        "--project", required=True,
        help="Project capability owning the GitHub App repo binding.",
    )


def github_actions_secret_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions secret set",
        description=(
            "Create or update a repo Actions secret via bearer-token REST "
            "(libsodium sealed-box encryption against the repo public "
            "key; no host GitHub CLI). VALUE is the default input. "
            "--value-file and --value-stdin are available for scripts; "
            "the value is sent to GitHub's Actions secret store and is "
            "never written to Yoke config or project files."
        ),
    )
    _add_repo_name_project(
        parser, noun="secret", example="YOKE_CI_API_TOKEN",
    )
    parser.add_argument("value", nargs="?")
    parser.add_argument("--value-file", dest="value_file", default=None)
    parser.add_argument(
        "--value-stdin", dest="value_stdin", action="store_true",
        help=(
            "Read the secret value from stdin. Trailing newlines are stripped."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_SECRET_SET_USAGE)
    if parsed is None:
        return 2

    if "/" not in parsed.repo:
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")

    value_rc, value = _github_actions_secret_value(parsed)
    if value_rc != 0 or value is None:
        return value_rc

    payload: Dict[str, Any] = {
        "repo": parsed.repo,
        "name": parsed.name,
        "value": value,
        "project": parsed.project,
    }
    return dispatch_and_emit(
        function_id="github_actions.secret.set",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def _github_actions_secret_value(
    parsed: argparse.Namespace,
) -> tuple[int, str | None]:
    sources = [parsed.value is not None, parsed.value_file is not None,
               parsed.value_stdin]
    if sum(1 for source in sources if source) != 1:
        return usage_error(
            "exactly one secret value source is required: "
            f"{GITHUB_ACTIONS_SECRET_SET_USAGE}"
        ), None
    try:
        if parsed.value is not None:
            value = str(parsed.value)
        elif parsed.value_file is not None:
            value = _read_actions_secret_file(parsed.value_file)
        else:
            value = sys.stdin.read().rstrip("\r\n")
    except machine_secrets.MachineSecretError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1, None
    if not value:
        return usage_error(
            "secret value is empty: "
            f"{GITHUB_ACTIONS_SECRET_SET_USAGE}"
        ), None
    return 0, value


def _read_actions_secret_file(path: str) -> str:
    selected = Path(path).expanduser()
    try:
        return machine_secrets.read_secret_file(selected, "secret")
    except machine_secrets.MachineSecretError:
        raise


GITHUB_ACTIONS_VARIABLE_SET_USAGE = (
    "yoke github-actions variable set <repo-slug> <variable-name> "
    "--value VALUE --project P [--session-id S] [--json]"
)


def github_actions_variable_set(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions variable set",
        description=(
            "Create or update a repo Actions variable via bearer-token "
            "REST (no host GitHub CLI). Variables are non-secret "
            "plaintext config (e.g. a CI master gate), so the value is "
            "a plain flag. For secret material use `yoke "
            "github-actions secret set` with VALUE, --value-file, or "
            "--value-stdin instead."
        ),
    )
    _add_repo_name_project(
        parser, noun="variable", example="YOKE_PULUMI_CI_ENABLED",
    )
    parser.add_argument(
        "--value", required=True,
        help="Variable value (non-secret plaintext).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_VARIABLE_SET_USAGE)
    if parsed is None:
        return 2

    if "/" not in parsed.repo:
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")

    payload: Dict[str, Any] = {
        "repo": parsed.repo,
        "name": parsed.name,
        "value": parsed.value,
        "project": parsed.project,
    }
    return dispatch_and_emit(
        function_id="github_actions.variable.set",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


GITHUB_ACTIONS_VARIABLE_GET_USAGE = (
    "yoke github-actions variable get <repo-slug> <variable-name> "
    "--project P [--session-id S] [--json]"
)


def github_actions_variable_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke github-actions variable get",
        description=(
            "Read a repo Actions variable via bearer-token REST (no host "
            "GitHub CLI). Read-only sibling of `variable set` for "
            "confirming arming-gate state (e.g. why a workflow job "
            "self-skipped on its `vars` condition) without mutating "
            "repo config. Reports exists=false when the variable is "
            "absent."
        ),
    )
    _add_repo_name_project(
        parser, noun="variable", example="YOKE_PULUMI_CI_ENABLED",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, GITHUB_ACTIONS_VARIABLE_GET_USAGE)
    if parsed is None:
        return 2

    if "/" not in parsed.repo:
        return usage_error(f"repo must be owner/name, got {parsed.repo!r}")

    payload: Dict[str, Any] = {
        "repo": parsed.repo,
        "name": parsed.name,
        "project": parsed.project,
    }
    return dispatch_and_emit(
        function_id="github_actions.variable.get",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
