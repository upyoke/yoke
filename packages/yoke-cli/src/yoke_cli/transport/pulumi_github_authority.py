"""Transport-safe GitHub App authority for local Pulumi execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from typing import Any, Callable

from yoke_cli.config import github_local_user_access
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_cli.transport.https import resolve_https_connection
from yoke_contracts.api.function_call import TargetRef
from yoke_contracts.github_app_installation_permissions import (
    permission_level_satisfies,
)


class PulumiGithubAuthorityError(RuntimeError):
    """A repository-bound machine App authorization is unavailable."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        # Every message constructed in this module is deliberately redacted.
        # The execution layer can surface this explanation while continuing
        # to hide arbitrary exception text from token and transport providers.
        self.pulumi_safe_message = message


@dataclass(frozen=True)
class PulumiGithubAuth:
    repo: str
    token: str = field(repr=False)


def build_pulumi_github_auth_loader(
    *,
    session_id: str | None,
    dispatch: Callable[..., Any] = call_dispatcher,
    token_loader: Callable[..., Any] = github_local_user_access.access_token,
) -> Callable[..., PulumiGithubAuth]:
    """Return a loader bound to the selected Yoke transport and actor."""

    def load(
        project: str,
        *,
        required_permissions: Mapping[str, str] | None = None,
    ) -> PulumiGithubAuth:
        selected_project = str(project or "").strip()
        response = dispatch(
            function_id="projects.github_binding.status",
            target=TargetRef(kind="global"),
            payload={"project": selected_project},
            actor=build_actor(session_id=session_id),
        )
        if not response.success or not isinstance(response.result, Mapping):
            raise PulumiGithubAuthorityError(
                "project GitHub binding status is unavailable"
            )
        binding = response.result.get("binding")
        installation = response.result.get("installation")
        if not isinstance(binding, Mapping) or not isinstance(
            installation, Mapping
        ):
            raise PulumiGithubAuthorityError(
                "project GitHub App binding is incomplete"
            )
        if (
            str(binding.get("status") or "") != "active"
            or str(installation.get("status") or "") != "active"
        ):
            raise PulumiGithubAuthorityError(
                "project GitHub App binding is not active"
            )
        repo = str(binding.get("github_repo") or "").strip()
        if not repo:
            raise PulumiGithubAuthorityError(
                "project GitHub App repository binding is absent"
            )
        granted = installation.get("permissions")
        if not isinstance(granted, Mapping):
            raise PulumiGithubAuthorityError(
                "project GitHub App permission metadata is absent"
            )
        missing = sorted(
            str(name)
            for name, required in (required_permissions or {}).items()
            if not permission_level_satisfies(
                str(granted.get(name) or ""), str(required or "")
            )
        )
        if missing:
            raise PulumiGithubAuthorityError(
                "project GitHub App binding lacks required permissions: "
                + ", ".join(missing)
            )
        if os.environ.get("GITHUB_ACTIONS", "").strip().lower() == "true":
            token = os.environ.get("GITHUB_TOKEN", "").strip()
            runner_token = os.environ.get(
                "RUNNER_FLEET_GITHUB_TOKEN", ""
            ).strip()
            if not token or (runner_token and runner_token != token):
                raise PulumiGithubAuthorityError(
                    "GitHub Actions repository token authority is absent or "
                    "inconsistent; provide one repository-bound GITHUB_TOKEN"
                )
            return PulumiGithubAuth(repo=repo, token=token)
        connection = resolve_https_connection()
        try:
            token = token_loader(
                service_api_url=(connection.api_url if connection else None),
                local_connection_selected=connection is None,
            ).access_token
        except Exception as exc:
            raise PulumiGithubAuthorityError(
                "machine GitHub App authorization is unavailable; run "
                "`yoke github status`, then reconnect GitHub"
            ) from exc
        if not str(token or "").strip():
            raise PulumiGithubAuthorityError(
                "machine GitHub App authorization returned an empty token"
            )
        return PulumiGithubAuth(repo=repo, token=str(token).strip())

    return load


__all__ = [
    "PulumiGithubAuth",
    "PulumiGithubAuthorityError",
    "build_pulumi_github_auth_loader",
]
