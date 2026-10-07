"""Types and diagnostics for project GitHub App authorization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Mapping

from yoke_contracts.github_app_tokens import GITHUB_CAPABILITY_TYPE
from yoke_core.domain.github_app_token_models import InstallationToken


# The two authorities a project GitHub operation can act under. A resolved
# bundle reports which one produced its bearer token, and a caller names the
# weakest one that can perform its operation.
GITHUB_AUTHORITY_USER = "github_app_user"
GITHUB_AUTHORITY_INSTALLATION = "github_app_installation"


class ProjectGithubAuthError(Exception):
    code: str = "project_github_auth_error"

    def __init__(
        self,
        project: str,
        message: str,
        *,
        http_status: int | None = None,
        repair_hint: str = "",
    ) -> None:
        super().__init__(message)
        self.project = project
        # The GitHub HTTP status behind the refusal, when GitHub answered.
        self.http_status = http_status
        # A repair template ({project}) narrower than the code's own, set
        # when the failure itself names which repair applies.
        self.repair_hint = repair_hint


class UnnamedProject(ProjectGithubAuthError):
    """No project was named, so there is no binding to resolve.

    Distinct from a project whose binding is missing: nothing was asked
    about. It exists as its own refusal because the alternative -- one
    compiled-in slug standing in -- relays another project's work through
    this installation's credentials, which no later reader can detect.
    """

    code = "unnamed_project"


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


class GitHubUnavailable(ProjectGithubAuthError):
    """GitHub itself failed the request; the binding and credentials stand.

    A 5xx, a rate limit, or a network failure or timeout. The work is
    retryable as-is once GitHub recovers; nothing on the Yoke side is
    broken, so no credential or installation repair applies.
    """

    code = "github_unavailable"


class UserAuthorizationUnavailable(ProjectGithubAuthError):
    code = "user_authorization_unavailable"


class UserAuthorizationTransient(ProjectGithubAuthError):
    """The stored authorization stands; reading it kept failing transiently."""

    code = "user_authorization_transient"


class InvalidToken(ProjectGithubAuthError):
    code = "invalid_token"


class TransportFailure(ProjectGithubAuthError):
    code = "transport_failure"


# The function-call error code for every project GitHub auth refusal except
# a GitHub outage, which reports its own retryable code.
PROJECT_AUTH_ERROR_CODE = "project_auth_error"


def auth_refusal_function_code(error: ProjectGithubAuthError) -> str:
    """The function-call error code a handler reports for an auth refusal."""
    if isinstance(error, GitHubUnavailable):
        return error.code
    return PROJECT_AUTH_ERROR_CODE


@dataclass(frozen=True)
class ProjectGithubAuth:
    project: str
    repo: str
    token: str = field(repr=False)
    installation_id: str = ""
    token_issued_at: str = ""
    token_expires_at: str = ""
    token_source: str = GITHUB_AUTHORITY_INSTALLATION
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
    "PROJECT_AUTH_ERROR_CODE",
    "auth_refusal_function_code",
    "GITHUB_AUTHORITY_INSTALLATION",
    "GITHUB_AUTHORITY_USER",
    "AppCredentials",
    "BindingUnavailable",
    "GITHUB_CAPABILITY_TYPE",
    "GitHubUnavailable",
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
    "UserAuthorizationTransient",
    "UserAuthorizationUnavailable",
]
