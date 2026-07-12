"""Apply-time GitHub token hydration for project onboarding inputs."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts import github_origin
from yoke_cli.config import github_local_user_access, github_machine, machine_config
from yoke_cli.config.project_clone_support import (
    CLONE_OUTCOME_FORK,
    CLONE_OUTCOME_MAKE_IT_MINE,
    ClonePlan,
)
from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_APP_BINDING
from yoke_cli.config.project_publish_support import PublishRequest


class MachineGitHubInputError(RuntimeError):
    """App-backed project inputs could not be hydrated for Apply."""


def hydrate_machine_github_inputs(
    inputs: dict[str, Any],
    config_path: Path,
    *,
    service_api_url: str | None = None,
    local_connection_selected: bool = False,
) -> dict[str, Any]:
    """Acquire one post-connect token for explicitly App-backed project work."""

    publish = inputs.get("publish")
    clone = inputs.get("clone")
    publish_needs = bool(
        isinstance(publish, PublishRequest)
        and publish.use_machine_github
        and not publish.token
    )
    clone_needs = bool(
        isinstance(clone, ClonePlan)
        and clone.use_machine_github
        and not clone.fallback_token
        and clone.outcome in (
            CLONE_OUTCOME_FORK,
            CLONE_OUTCOME_MAKE_IT_MINE,
        )
    )
    clone_publish = clone.publish if isinstance(clone, ClonePlan) else None
    manual_publish_requests = [
        candidate
        for candidate in (publish, clone_publish)
        if isinstance(candidate, PublishRequest)
        and candidate.use_machine_github
        and not candidate.create_repository
    ]
    binding_repo = str(inputs.get("github_repo") or "")
    binding_repository_id = inputs.get("github_repository_id")
    binding_installation_id = inputs.get("github_installation_id")
    binding_identity_selected = bool(
        str(inputs.get("github_adoption") or "") == GITHUB_ADOPTION_APP_BINDING
        and binding_repo
        and isinstance(binding_repository_id, int)
        and binding_repository_id > 0
        and isinstance(binding_installation_id, int)
        and binding_installation_id > 0
    )
    if not (
        publish_needs
        or clone_needs
        or manual_publish_requests
        or binding_identity_selected
    ):
        return inputs
    if manual_publish_requests or binding_identity_selected:
        report = github_machine.status(
            config_path=config_path,
            check=True,
            service_api_url=service_api_url,
            local_connection_selected=local_connection_selected,
        )
        identity = report.get("identity") if isinstance(report, Mapping) else None
        access = report.get("access") if isinstance(report, Mapping) else None
        if (
            not isinstance(identity, Mapping)
            or identity.get("checked") is not True
            or identity.get("ok") is not True
            or not isinstance(access, Mapping)
            or access.get("repo_listing_ok") is not True
        ):
            raise MachineGitHubInputError(
                "The manually selected GitHub repository could not be refreshed "
                "live. Check repositories again before Apply."
            )
    github = machine_config.github_config(config_path)
    for manual_publish in manual_publish_requests:
        if not _manual_repository_matches(github, manual_publish):
            raise MachineGitHubInputError(
                "The manually selected GitHub repository or App installation "
                "identity changed. Check repositories again before Apply."
            )
    if binding_identity_selected and not _repository_identity_matches(
        github,
        full_name=binding_repo,
        repository_id=binding_repository_id,
        installation_id=binding_installation_id,
    ):
        raise MachineGitHubInputError(
            "The selected GitHub repository or App installation identity changed. "
            "Check repository access again before Apply."
        )
    if not (publish_needs or clone_needs):
        return inputs
    try:
        token = github_local_user_access.access_token(
            config_path=config_path,
            service_api_url=service_api_url,
            local_connection_selected=local_connection_selected,
        ).access_token
    except github_local_user_access.GitHubLocalUserAccessError as exc:
        raise MachineGitHubInputError(
            "The connected GitHub App authorization could not be used for "
            "this project operation. Reconnect GitHub and retry."
        ) from exc
    hydrated = dict(inputs)
    api_url = str(
        github.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL
    )
    web_url = str(
        github.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL
    )
    if publish_needs:
        hydrated["publish"] = replace(
            publish,
            token=token,
            api_url=api_url,
            web_url=web_url,
            administration_allowed=_administration_allowed(
                github, publish.owner
            ),
        )
    if clone_needs:
        clone_publish = clone.publish
        if (
            isinstance(clone_publish, PublishRequest)
            and clone_publish.use_machine_github
            and not clone_publish.token
        ):
            clone_publish = replace(
                clone_publish,
                token=token,
                api_url=api_url,
                web_url=web_url,
                administration_allowed=_administration_allowed(
                    github, clone_publish.owner
                ),
            )
        hydrated["clone"] = replace(
            clone,
            fallback_token=token,
            publish=clone_publish,
            fork_api_url=api_url,
            fork_web_url=web_url,
        )
    return hydrated


def _administration_allowed(github: Mapping[str, Any], owner: str) -> bool:
    try:
        if github_origin.validate_github_endpoint_pair(
            str(github.get("api_url") or github_origin.DEFAULT_GITHUB_API_URL),
            str(github.get("web_url") or github_origin.DEFAULT_GITHUB_WEB_URL),
        ).deployment_kind != "github_cloud":
            return False
    except github_origin.GitHubApiOriginError:
        return False
    return any(
        isinstance(installation, Mapping)
        and isinstance(installation.get("permissions"), Mapping)
        and str(installation.get("account_login") or "").casefold()
        == owner.casefold()
        and not installation.get("suspended")
        and installation.get("repository_selection") == "all"
        and installation["permissions"].get("administration") == "write"
        for installation in github.get("installations") or []
    )


def _manual_repository_matches(
    github: Mapping[str, Any], publish: PublishRequest,
) -> bool:
    return _repository_identity_matches(
        github,
        full_name=publish.full_name,
        repository_id=publish.repository_id,
        installation_id=publish.installation_id,
        private=publish.private,
    )


def _repository_identity_matches(
    github: Mapping[str, Any],
    *,
    full_name: str,
    repository_id: Any,
    installation_id: Any,
    private: bool | None = None,
) -> bool:
    repository = next((
        row for row in github.get("repositories") or []
        if isinstance(row, Mapping)
        and str(row.get("full_name") or "").casefold()
        == full_name.casefold()
    ), None)
    if (
        repository is None
        or repository.get("repository_id") != repository_id
        or repository.get("installation_id") != installation_id
        or (private is not None and repository.get("private") is not private)
    ):
        return False
    installation = next((
        row for row in github.get("installations") or []
        if isinstance(row, Mapping)
        and row.get("installation_id") == installation_id
    ), None)
    return bool(
        installation
        and not installation.get("suspended")
        and isinstance(installation.get("permissions"), Mapping)
        and installation["permissions"].get("contents") == "write"
    )


__all__ = ["MachineGitHubInputError", "hydrate_machine_github_inputs"]
