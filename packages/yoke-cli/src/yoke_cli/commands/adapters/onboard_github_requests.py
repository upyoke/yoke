"""Noninteractive GitHub project-request assembly for onboarding."""

from __future__ import annotations

import argparse

from yoke_contracts import github_origin
from yoke_cli.config import github_local_user_access, github_user_tokens, machine_config
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_MAKE_IT_MINE,
    ClonePlan,
)
from yoke_cli.config.project_publish_support import PublishRequest


def github_user_access_token(
    parsed: argparse.Namespace,
    *,
    required: bool,
) -> str | None:
    if not required:
        return None
    refreshed = github_local_user_access.access_token(
        config_path=getattr(parsed, "config_path", None),
    )
    return refreshed.access_token


def project_publish(
    parsed: argparse.Namespace,
    github_user_access_token: str | None,
    *,
    use_machine_github: bool = False,
) -> PublishRequest | None:
    owner = str(getattr(parsed, "project_publish_owner", "") or "").strip()
    name = str(getattr(parsed, "project_publish_repo_name", "") or "").strip()
    if not (owner and name):
        return None
    if not github_user_access_token and not use_machine_github:
        raise github_user_tokens.GitHubUserTokenError(
            "GitHub App user authorization is required to create a GitHub repo. "
            "Run `yoke github connect` when browser authorization is available, "
            "or continue backlog-only."
        )
    return PublishRequest(
        owner=owner,
        name=name,
        user_login=str(getattr(parsed, "project_publish_owner_login", "") or ""),
        token=github_user_access_token,
        api_url=str(
            getattr(parsed, "project_publish_api_url", "")
            or getattr(parsed, "machine_github_api_url", "")
            or github_origin.DEFAULT_GITHUB_API_URL
        ),
        private=bool(getattr(parsed, "project_publish_private", True)),
        administration_allowed=_administration_allowed(
            getattr(parsed, "config_path", None), owner,
        ),
        web_url=_web_url(getattr(parsed, "config_path", None)),
        use_machine_github=use_machine_github,
        create_repository=bool(
            getattr(parsed, "project_publish_create_repository", True)
        ),
        repository_id=getattr(parsed, "project_publish_repository_id", None),
        installation_id=getattr(parsed, "project_publish_installation_id", None),
    )


def project_clone(
    parsed: argparse.Namespace,
    github_user_access_token: str | None,
    project_publish: PublishRequest | None,
    *,
    use_machine_github: bool = False,
) -> ClonePlan | None:
    outcome = str(getattr(parsed, "project_clone_outcome", "") or "").strip()
    if not outcome:
        if (github_user_access_token or use_machine_github) and str(
            getattr(parsed, "project_mode", "") or ""
        ) in ("clone-remote", "import-remote"):
            return ClonePlan(
                fallback_token=github_user_access_token,
                use_machine_github=use_machine_github,
                fork_web_url=_web_url(getattr(parsed, "config_path", None)),
            )
        return None
    if outcome in (CLONE_OUTCOME_FORK, CLONE_OUTCOME_MAKE_IT_MINE):
        if not github_user_access_token and not use_machine_github:
            raise github_user_tokens.GitHubUserTokenError(
                "GitHub App user authorization is required for the saved clone "
                "outcome. Run `yoke github connect` when browser authorization "
                "is available, or choose a plain clone/backlog-only flow."
            )
    return ClonePlan(
        outcome=outcome,
        keep_upstream=bool(getattr(parsed, "project_clone_keep_upstream", True)),
        publish=(
            project_publish
            if outcome == CLONE_OUTCOME_MAKE_IT_MINE else None
        ),
        fallback_token=github_user_access_token,
        use_machine_github=use_machine_github,
        fork_api_url=str(
            getattr(parsed, "project_clone_fork_api_url", "")
            or getattr(parsed, "machine_github_api_url", "")
            or github_origin.DEFAULT_GITHUB_API_URL
        ),
        fork_web_url=_web_url(getattr(parsed, "config_path", None)),
    )


def project_needs_github_user_access_token(parsed: argparse.Namespace) -> bool:
    outcome = str(getattr(parsed, "project_clone_outcome", "") or "").strip()
    if outcome in (CLONE_OUTCOME_FORK, CLONE_OUTCOME_MAKE_IT_MINE):
        return True
    return bool(
        str(getattr(parsed, "project_publish_owner", "") or "").strip()
        and str(getattr(parsed, "project_publish_repo_name", "") or "").strip()
    )


def _administration_allowed(config_path: str | None, owner: str) -> bool:
    github = machine_config.github_config(config_path)
    try:
        if github_origin.validate_github_endpoint_pair(
            str(github.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL),
            str(github.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL),
        ).deployment_kind != "github_cloud":
            return False
    except github_origin.GitHubApiOriginError:
        return False
    return any(
        isinstance(installation, dict)
        and isinstance(installation.get("permissions"), dict)
        and str(installation.get("account_login") or "").casefold()
        == owner.casefold()
        and not installation.get("suspended")
        and installation.get("repository_selection") == "all"
        and installation["permissions"].get("administration") == "write"
        for installation in github.get("installations") or []
    )


def _web_url(config_path: str | None) -> str:
    github = machine_config.github_config(config_path)
    return github_origin.validate_github_web_endpoint(
        str(github.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL)
    ).base_url


__all__ = [
    "github_user_access_token",
    "project_clone",
    "project_needs_github_user_access_token",
    "project_publish",
]
