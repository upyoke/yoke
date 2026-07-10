"""Types and diagnostics for project GitHub App authorization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

from yoke_contracts.github_app_tokens import GITHUB_CAPABILITY_TYPE
from yoke_core.domain.github_app_token_models import InstallationToken


class ProjectGithubAuthError(Exception):
    code: str = "project_github_auth_error"

    def __init__(self, project: str, message: str) -> None:
        super().__init__(message)
        self.project = project


class MissingCapability(ProjectGithubAuthError):
    code = "missing_capability"


class MissingRepoMetadata(ProjectGithubAuthError):
    code = "missing_repo_metadata"


class MissingRepoBinding(ProjectGithubAuthError):
    code = "missing_repo_binding"


class MissingInstallation(ProjectGithubAuthError):
    code = "missing_installation"


class BindingUnavailable(ProjectGithubAuthError):
    code = "binding_unavailable"


class InstallationUnavailable(ProjectGithubAuthError):
    code = "installation_unavailable"


class MissingPermission(ProjectGithubAuthError):
    code = "missing_permission"


class MissingAppCredentials(ProjectGithubAuthError):
    code = "missing_app_credentials"


class TokenMintFailed(ProjectGithubAuthError):
    code = "token_mint_failed"


class UserAuthorizationUnavailable(ProjectGithubAuthError):
    code = "user_authorization_unavailable"


class InvalidToken(ProjectGithubAuthError):
    code = "invalid_token"


class TransportFailure(ProjectGithubAuthError):
    code = "transport_failure"


@dataclass(frozen=True)
class ProjectGithubAuth:
    project: str
    repo: str
    token: str = field(repr=False)
    installation_id: str = ""
    token_expires_at: str = ""
    token_source: str = "github_app_installation"
    permissions: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectGithubState:
    project_slug: str
    project_id: int | None
    has_capability: bool
    binding: Mapping[str, object] | None
    installation: Mapping[str, object] | None


@dataclass(frozen=True)
class AppCredentials:
    issuer: str
    private_key_pem: str = field(repr=False)
    api_url: str
    private_key_file: str


TokenMinter = Callable[..., InstallationToken]


__all__ = [
    "AppCredentials",
    "BindingUnavailable",
    "GITHUB_CAPABILITY_TYPE",
    "InstallationUnavailable",
    "InvalidToken",
    "MissingAppCredentials",
    "MissingCapability",
    "MissingInstallation",
    "MissingPermission",
    "MissingRepoBinding",
    "MissingRepoMetadata",
    "ProjectGithubAuth",
    "ProjectGithubAuthError",
    "ProjectGithubState",
    "TokenMintFailed",
    "TokenMinter",
    "TransportFailure",
    "UserAuthorizationUnavailable",
]
