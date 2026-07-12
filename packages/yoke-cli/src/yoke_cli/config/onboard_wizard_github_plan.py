"""GitHub-backed project request assembly for wizard state."""

from __future__ import annotations

from typing import Any

from yoke_contracts import github_origin
from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_wizard_github_state as github_state
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_MAKE_IT_MINE,
)


def publish_request_from_owner(result: Any) -> Any:
    """Build a deferred machine-GitHub publish request for the chosen owner."""

    from yoke_cli.config.onboard_project import PublishRequest

    if not (result.project_publish_owner and github_state.connected(result)):
        return None
    return PublishRequest(
        owner=result.project_publish_owner,
        name=(result.project_publish_repo_name or result.project_slug or "project"),
        user_login=(result.project_publish_owner_login or ""),
        token=None,
        api_url=(
            result.machine_github_api_url
            or github_origin.DEFAULT_GITHUB_API_URL
        ),
        web_url=github_state.clone_web_url(result),
        private=result.project_publish_private,
        administration_allowed=github_state.administration_allowed(result),
        use_machine_github=True,
        create_repository=result.project_publish_create_repository,
        repository_id=result.project_publish_repository_id,
        installation_id=result.project_publish_installation_id,
    )


def build_publish_request(result: Any) -> Any:
    if result.project_mode in onboard_project.PROJECT_REMOTE_MODES:
        return None
    if not result.project_publish_to_github:
        return None
    return publish_request_from_owner(result)


def build_clone_plan(result: Any) -> Any:
    """Build a tokenless plan whose machine token is acquired only at Apply."""

    from yoke_cli.config.onboard_project import ClonePlan

    if result.project_mode not in onboard_project.PROJECT_REMOTE_MODES:
        return None
    if not result.project_clone_outcome:
        needs_private_access = bool(
            result.project_clone_requires_machine_github
            or (result.existing_project_id and result.project_github_repo)
        )
        if not needs_private_access:
            return None
        if not github_state.connected(result):
            raise RuntimeError(
                "This saved/private repository needs a verified GitHub App "
                "connection. Reconnect GitHub before continuing."
            )
        return ClonePlan(
            use_machine_github=True,
            fork_api_url=(
                result.machine_github_api_url
                or github_origin.DEFAULT_GITHUB_API_URL
            ),
            fork_web_url=github_state.clone_web_url(result),
        )
    publish = None
    if result.project_clone_outcome == CLONE_OUTCOME_MAKE_IT_MINE:
        publish = publish_request_from_owner(result)
    return ClonePlan(
        outcome=result.project_clone_outcome,
        keep_upstream=result.project_clone_keep_upstream,
        publish=publish,
        fallback_token=None,
        use_machine_github=(
            github_state.connected(result)
            and (
                result.project_clone_requires_machine_github
                or result.project_clone_outcome
                in (CLONE_OUTCOME_FORK, CLONE_OUTCOME_MAKE_IT_MINE)
            )
        ),
        fork_api_url=(
            result.machine_github_api_url
            or github_origin.DEFAULT_GITHUB_API_URL
        ),
        fork_web_url=github_state.clone_web_url(result),
        fork_allowed=github_state.fork_ready(
            result, result.project_remote_url,
        ),
    )


__all__ = [
    "build_clone_plan",
    "build_publish_request",
    "publish_request_from_owner",
]
