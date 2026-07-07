"""Project-mode arguments for ``yoke onboard``."""

from __future__ import annotations

import argparse

from yoke_cli.config import onboard as onboard_config
from yoke_cli.config import onboard_github_copy
from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_CHOICES


def add_project_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--project-mode",
        default=None,
        metavar="MODE",
    )
    parser.add_argument("--checkout", dest="project_checkout", default=None)
    parser.add_argument("--remote-url", dest="project_remote_url", default=None)
    parser.add_argument("--project-slug", dest="project_slug", default=None)
    parser.add_argument("--project-name", dest="project_name", default=None)
    parser.add_argument("--project-org", dest="project_org", default=None)
    parser.add_argument("--github-repo", dest="project_github_repo", default=None)
    parser.add_argument(
        "--default-branch", dest="project_default_branch", default=None,
    )
    parser.add_argument(
        "--public-item-prefix", dest="project_public_item_prefix", default=None,
    )
    parser.add_argument(
        "--github-adoption",
        choices=GITHUB_ADOPTION_CHOICES,
        default=None,
        help=onboard_github_copy.PROJECT_TOKEN_ADOPTION_HELP,
    )
    parser.add_argument("--github-token", dest="github_token", default=None)
    parser.add_argument("--github-token-file", dest="github_token_file", default=None)
    parser.add_argument("--github-token-stdin", action="store_true")


def project_prompt_missing(parsed: argparse.Namespace) -> bool:
    if parsed.project_mode == onboard_config.PROJECT_MODE_MACHINE_ONLY:
        return False
    required = [
        parsed.project_checkout,
        parsed.project_slug,
        parsed.project_name,
        parsed.project_default_branch,
        parsed.project_public_item_prefix,
    ]
    if parsed.project_mode in (
        onboard_config.PROJECT_MODE_CLONE_REMOTE,
        onboard_config.PROJECT_MODE_IMPORT_REMOTE,
    ):
        required.append(parsed.project_remote_url)
    if parsed.project_mode == onboard_config.PROJECT_MODE_CREATE_REPO:
        required.append(parsed.project_github_repo)
    return any(not value for value in required)


__all__ = ["add_project_args", "project_prompt_missing"]
