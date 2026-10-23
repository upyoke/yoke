"""Adapters for project create/import/onboard flows."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_contracts import github_origin
from yoke_cli.commands._helpers import (
    add_json_arg,
    parse_or_usage_error,
)
from yoke_cli.transport.human_values import write_local
from yoke_cli.config import machine_config, onboard_github_copy
from yoke_cli.config import project_onboard
from yoke_cli.config.onboard_error_friendly import friendly_permission_error
from yoke_cli.config.project_clone_support import ClonePlan
from yoke_cli.config.project_installed_layer import (
    LAYER_DECISIONS,
    LAYER_DECISION_HELP,
)
from yoke_cli.config.project_github_adoption import (
    GITHUB_ADOPTION_INPUT_CHOICES,
    ProjectGithubAdoptionError,
)
from yoke_cli.project_install.files import ProjectInstallError

GITHUB_ADOPTION_FLAGS = "[--github-adoption app-binding|disabled]"
PROJECT_CREATE_USAGE = (
    "yoke project create CHECKOUT --slug SLUG --name NAME "
    "[--org ORG] [--github-repo OWNER/REPO] --default-branch BRANCH "
    f"--public-item-prefix PREFIX {GITHUB_ADOPTION_FLAGS} [--config PATH] "
    "[--yes | --dry-run] [--json]"
)
PROJECT_IMPORT_USAGE = (
    "yoke project import REMOTE_URL CHECKOUT --slug SLUG --name NAME "
    "[--org ORG] [--github-repo OWNER/REPO] --default-branch BRANCH "
    f"--public-item-prefix PREFIX {GITHUB_ADOPTION_FLAGS} "
    "[--existing-yoke-layer keep|remove] [--config PATH] "
    "[--yes | --dry-run] [--json]"
)
ONBOARD_PROJECT_USAGE = (
    "yoke onboard project CHECKOUT --slug SLUG --name NAME "
    "[--org ORG] [--github-repo OWNER/REPO] --default-branch BRANCH "
    f"--public-item-prefix PREFIX {GITHUB_ADOPTION_FLAGS} [--config PATH] "
    "[--yes | --dry-run] [--json]"
)


def project_create(args: List[str]) -> int:
    parser = _project_parser("yoke project create", PROJECT_CREATE_USAGE)
    parser.add_argument("checkout", help="Path to the project checkout.")
    # Consume one obsolete positional value so argparse never reflects a
    # possibly-secret value into stderr. It is rejected generically below and
    # is never passed to onboarding.
    parser.add_argument("_unexpected_positional", nargs="?", help=argparse.SUPPRESS)
    _add_github_adoption_args(parser)
    parsed = parse_or_usage_error(parser, args, PROJECT_CREATE_USAGE)
    if parsed is None:
        return 2
    if parsed._unexpected_positional is not None:
        print(
            "error: unexpected positional argument after CHECKOUT; use the "
            "GitHub App connection and --github-adoption instead",
            file=sys.stderr,
        )
        return 2
    try:
        _require_config_for_apply(parsed)
        report = project_onboard.create_project(
            checkout=parsed.checkout,
            slug=parsed.slug,
            name=parsed.name,
            org=parsed.org,
            github_repo=parsed.github_repo,
            default_branch=parsed.default_branch,
            public_item_prefix=parsed.public_item_prefix,
            github_adoption_choice=parsed.github_adoption,
            config_path=parsed.config_path,
            apply=parsed.apply,
        )
    except _errors() as exc:
        print(f"error: {friendly_permission_error(str(exc))}", file=sys.stderr)
        return 1
    _emit(report, parsed.json_mode)
    return 0


def project_import(args: List[str]) -> int:
    parser = _project_parser("yoke project import", PROJECT_IMPORT_USAGE)
    parser.add_argument("remote_url", help="Git URL of the repository to import.")
    parser.add_argument("checkout", help="Path to clone the repository into.")
    parser.add_argument(
        "--existing-yoke-layer",
        choices=LAYER_DECISIONS,
        default=None,
        help=LAYER_DECISION_HELP,
    )
    _add_github_adoption_args(parser)
    parsed = parse_or_usage_error(parser, args, PROJECT_IMPORT_USAGE)
    if parsed is None:
        return 2
    try:
        _require_config_for_apply(parsed)
        report = project_onboard.import_project(
            remote_url=parsed.remote_url,
            checkout=parsed.checkout,
            clone=_import_clone_plan(parsed),
            slug=parsed.slug,
            name=parsed.name,
            org=parsed.org,
            github_repo=parsed.github_repo,
            default_branch=parsed.default_branch,
            public_item_prefix=parsed.public_item_prefix,
            github_adoption_choice=parsed.github_adoption,
            config_path=parsed.config_path,
            apply=parsed.apply,
        )
    except _errors() as exc:
        print(f"error: {friendly_permission_error(str(exc))}", file=sys.stderr)
        return 1
    _emit(report, parsed.json_mode)
    return 0


def _import_clone_plan(parsed: argparse.Namespace) -> ClonePlan:
    """Read the source through this machine's connected GitHub App, if any.

    ``yoke github connect`` stores the ``github`` block that
    ``yoke github disconnect`` clears, so its presence is the connection.
    """
    github_config = machine_config.github_config(parsed.config_path)
    return ClonePlan(
        use_machine_github=bool(github_config),
        fork_web_url=str(
            github_config.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL
        ),
        existing_layer_decision=parsed.existing_yoke_layer or "",
    )


def onboard_project(args: List[str]) -> int:
    parser = _project_parser("yoke onboard project", ONBOARD_PROJECT_USAGE)
    parser.add_argument("checkout", help="Path to the project checkout.")
    _add_github_adoption_args(parser)
    parsed = parse_or_usage_error(parser, args, ONBOARD_PROJECT_USAGE)
    if parsed is None:
        return 2
    try:
        _require_config_for_apply(parsed)
        report = project_onboard.onboard_existing(
            checkout=parsed.checkout,
            slug=parsed.slug,
            name=parsed.name,
            org=parsed.org,
            github_repo=parsed.github_repo,
            default_branch=parsed.default_branch,
            public_item_prefix=parsed.public_item_prefix,
            github_adoption_choice=parsed.github_adoption,
            config_path=parsed.config_path,
            apply=parsed.apply,
        )
    except _errors() as exc:
        print(f"error: {friendly_permission_error(str(exc))}", file=sys.stderr)
        return 1
    _emit(report, parsed.json_mode)
    return 0


def _require_config_for_apply(parsed: argparse.Namespace) -> None:
    if parsed.apply:
        selected = machine_config.config_path(parsed.config_path)
        if not selected.is_file():
            raise project_onboard.ProjectOnboardError(
                f"machine_config_missing: no machine config at {selected}; "
                "run `yoke setup` first, or pass --config PATH for an existing config."
            )


def _project_parser(prog: str, usage: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog=prog,
        usage=usage,
    )
    parser.add_argument("--slug", required=True, help="Short id for the project.")
    parser.add_argument("--name", required=True, help="Display name for the project.")
    parser.add_argument(
        "--org",
        dest="org",
        default=None,
        help="Owning organization slug or id for a newly created project.",
    )
    parser.add_argument(
        "--github-repo",
        dest="github_repo",
        default=None,
        help="GitHub repository, as OWNER/REPO.",
    )
    parser.add_argument(
        "--default-branch",
        dest="default_branch",
        required=True,
        help="Main branch of the repository.",
    )
    parser.add_argument(
        "--public-item-prefix",
        dest="public_item_prefix",
        required=True,
        help="Prefix for the project's item refs, as in PREFIX-N.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Machine config override; defaults to the machine config resolver.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--yes", dest="apply", action="store_true", help="Apply the plan."
    )
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Print the plan without applying it (the default).",
    )
    parser.set_defaults(apply=False, dry_run=False)
    add_json_arg(parser)
    return parser


def _add_github_adoption_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--github-adoption",
        choices=GITHUB_ADOPTION_INPUT_CHOICES,
        default=None,
        help=onboard_github_copy.PROJECT_GITHUB_SETUP_HELP,
    )


def _emit(report: dict, json_mode: bool) -> None:
    if json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        write_local(report, sys.stdout)


def _errors():
    return (
        ProjectInstallError,
        ProjectGithubAdoptionError,
        project_onboard.ProjectOnboardError,
        machine_config.MachineConfigError,
        machine_secret_error(),
    )


def machine_secret_error():
    from yoke_cli.config.secrets import MachineSecretError

    return MachineSecretError


__all__ = [
    "ONBOARD_PROJECT_USAGE",
    "PROJECT_CREATE_USAGE",
    "PROJECT_IMPORT_USAGE",
    "onboard_project",
    "project_create",
    "project_import",
]
