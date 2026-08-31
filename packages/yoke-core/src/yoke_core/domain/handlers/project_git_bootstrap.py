"""``project.git.bootstrap`` handler: init a checkout and a private remote.

Runs on the caller's machine (CLIENT_LOCAL). A relayed call would init a
repository on the server filesystem, which is never the intended checkout.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class ProjectGitBootstrapRequest(BaseModel):
    checkout: str
    init_repo: bool = True
    create_remote: bool = True
    project: Optional[str] = None
    owner: Optional[str] = None
    name: Optional[str] = None
    default_branch: str = "main"
    apply: bool = False
    config_path: Optional[str] = None


class ProjectGitBootstrapResponse(BaseModel):
    checkout: str
    dry_run: bool
    initialized: bool
    gitignore_written: bool
    committed: bool
    remote_created: bool
    github_repo: Optional[str] = None
    bound: bool = False
    skipped: list[str]
    planned: list[str]
    text: str


def _error(code: str, message: str, *, jsonpath: Optional[str] = None) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message, jsonpath=jsonpath),
    )


def handle_project_git_bootstrap(request: FunctionCallRequest) -> HandlerOutcome:
    if request.target.kind != "global":
        return _error(
            "target_invalid",
            "project.git.bootstrap requires target.kind='global'",
            jsonpath="$.target.kind",
        )
    payload = request.payload or {}
    checkout = payload.get("checkout")
    if not isinstance(checkout, str) or not checkout.strip():
        return _error(
            "payload_invalid",
            "checkout must be a non-empty string",
            jsonpath="$.payload.checkout",
        )
    from yoke_cli.config.project_git_bootstrap import bootstrap_checkout
    from yoke_cli.config.project_git_prerequisite import MissingGitError
    from yoke_cli.config.project_github_adoption import ProjectGithubAdoptionError
    from yoke_cli.config.project_onboard_support import ProjectOnboardError
    from yoke_cli.config.github_publish import GitHubPublishError
    from yoke_cli.config.onboard_project_github_inputs import MachineGitHubInputError

    try:
        result = bootstrap_checkout(
            checkout.strip(),
            init_repo=bool(payload.get("init_repo", True)),
            create_remote=bool(payload.get("create_remote", True)),
            project_slug=_optional_str(payload.get("project")),
            owner=_optional_str(payload.get("owner")),
            name=_optional_str(payload.get("name")),
            default_branch=str(payload.get("default_branch") or "main"),
            apply=bool(payload.get("apply", False)),
            config_path=_optional_str(payload.get("config_path")),
        )
    except (
        ProjectOnboardError,
        GitHubPublishError,
        MachineGitHubInputError,
        MissingGitError,
        ProjectGithubAdoptionError,
    ) as exc:
        return _error("git_bootstrap_failed", str(exc))
    return HandlerOutcome(result_payload=result.as_dict(), primary_success=True)


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


__all__ = [
    "ProjectGitBootstrapRequest",
    "ProjectGitBootstrapResponse",
    "handle_project_git_bootstrap",
]
