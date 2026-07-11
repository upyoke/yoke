"""Prove an installation belongs to the configured server GitHub App."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable, Mapping
import urllib.error
import urllib.request

from yoke_contracts import github_app_tokens as token_contract
from yoke_contracts.github_origin import GitHubApiEndpoint, GitHubApiOriginError

from yoke_core.domain import gh_rest_transport
from yoke_core.domain.github_api_transport import open_same_origin
from yoke_core.domain.github_app_control_plane import (
    GitHubAppControlPlaneConfig,
    GitHubAppControlPlaneConfigError,
    load_github_app_control_plane_config,
)
from yoke_core.domain.github_app_dispatch_context import LOCAL_API_ENDPOINT
from yoke_core.domain.github_app_jwt import generate_app_jwt
from yoke_core.domain.github_app_verification_response import (
    GitHubAppVerificationResponseError,
    read_bounded_verification_response,
    require_unredirected_verification_response,
)


class GitHubServerInstallationVerificationError(ValueError):
    """The configured server App could not prove installation ownership."""


@dataclass(frozen=True)
class ServerVerifiedInstallation:
    installation_id: str
    account_id: str
    account_login: str
    account_type: str
    repository_selection: str
    permissions: Mapping[str, str]
    status: str


ServerInstallationFetcher = Callable[..., ServerVerifiedInstallation]


def resolve_binding_verification_authority(
    *,
    endpoint: GitHubApiEndpoint | None = None,
    config: GitHubAppControlPlaneConfig | None = None,
) -> tuple[GitHubApiEndpoint, GitHubAppControlPlaneConfig | None]:
    """Select local user-only or server-App-backed verification authority."""
    contextual = LOCAL_API_ENDPOINT.get()
    if config is not None:
        candidate = endpoint or contextual
        if candidate is not None and candidate.base_url != config.endpoint.base_url:
            raise GitHubServerInstallationVerificationError(
                "GitHub verification authority origins do not match"
            )
        return config.endpoint, config
    if endpoint is not None:
        return endpoint, None
    if contextual is not None:
        return contextual, None
    try:
        selected = load_github_app_control_plane_config()
    except GitHubAppControlPlaneConfigError as exc:
        raise GitHubServerInstallationVerificationError(str(exc)) from exc
    return selected.endpoint, selected


def require_matching_user_installation(
    server: ServerVerifiedInstallation,
    *,
    installation_id: int,
    account_id: int,
    account_login: str,
    account_type: str,
    repository_selection: str,
    permissions: Mapping[str, str],
    status: str,
) -> None:
    """Reject user-token metadata that is not the configured App's view."""
    matches = (
        server.installation_id == str(installation_id)
        and server.account_id == str(account_id)
        and server.account_login.casefold() == account_login.casefold()
        and server.account_type.casefold() == account_type.casefold()
        and server.repository_selection == repository_selection
        and dict(server.permissions) == dict(permissions)
        and server.status == status
    )
    if not matches:
        raise GitHubServerInstallationVerificationError(
            "user authorization installation metadata does not match the "
            "configured server GitHub App"
        )


def verify_user_installation_against_server(
    *,
    config: GitHubAppControlPlaneConfig,
    installation_id: int,
    account_id: int,
    account_login: str,
    account_type: str,
    repository_selection: str,
    permissions: Mapping[str, str],
    status: str,
    opener: Callable[..., Any] | None,
    fetcher: ServerInstallationFetcher | None,
    timeout_seconds: float,
) -> None:
    """Fetch the server view and require exact user/server agreement."""
    server = (fetcher or fetch_server_app_installation)(
        config=config,
        installation_id=installation_id,
        opener=opener,
        timeout_seconds=timeout_seconds,
    )
    require_matching_user_installation(
        server,
        installation_id=installation_id,
        account_id=account_id,
        account_login=account_login,
        account_type=account_type,
        repository_selection=repository_selection,
        permissions=permissions,
        status=status,
    )


def fetch_server_app_installation(
    *,
    config: GitHubAppControlPlaneConfig,
    installation_id: str | int,
    opener: Callable[..., Any] | None = None,
    jwt_factory: Callable[..., str] | None = None,
    timeout_seconds: float = 30.0,
) -> ServerVerifiedInstallation:
    """Fetch canonical installation metadata using the server App JWT."""
    selected_id = _positive_id(installation_id, "installation_id")
    signer = jwt_factory or generate_app_jwt
    app_jwt = signer(
        issuer=config.issuer,
        private_key_pem=config.private_key_pem,
    )
    request = urllib.request.Request(
        config.endpoint.url(f"/app/installations/{selected_id}"),
        headers={
            "Authorization": f"Bearer {app_jwt}",
            "Accept": token_contract.GITHUB_APP_ACCEPT,
            "X-GitHub-Api-Version": gh_rest_transport.GITHUB_API_VERSION,
            "User-Agent": token_contract.GITHUB_APP_USER_AGENT,
        },
        method="GET",
    )
    try:
        with open_same_origin(
            request,
            endpoint=config.endpoint,
            timeout_seconds=timeout_seconds,
            opener=opener,
            reject_redirects=True,
        ) as response:
            require_unredirected_verification_response(
                response, expected_url=request.full_url
            )
            raw = read_bounded_verification_response(response)
    except urllib.error.HTTPError as exc:
        raise GitHubServerInstallationVerificationError(
            "the configured GitHub App cannot access the selected installation"
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise GitHubServerInstallationVerificationError(
            "server GitHub App installation verification was unavailable"
        ) from exc
    except GitHubApiOriginError as exc:
        raise GitHubServerInstallationVerificationError(str(exc)) from exc
    except GitHubAppVerificationResponseError as exc:
        raise GitHubServerInstallationVerificationError(str(exc)) from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise GitHubServerInstallationVerificationError(
            "server GitHub App installation response was not valid JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise GitHubServerInstallationVerificationError(
            "server GitHub App installation response must be an object"
        )
    response_id = _positive_id(payload.get("id"), "installation response id")
    if response_id != selected_id:
        raise GitHubServerInstallationVerificationError(
            "server GitHub App installation identity did not match the request"
        )
    account = payload.get("account")
    if not isinstance(account, Mapping):
        raise GitHubServerInstallationVerificationError(
            "server GitHub App installation account metadata is missing"
        )
    permissions = payload.get("permissions")
    if not isinstance(permissions, Mapping) or not permissions:
        raise GitHubServerInstallationVerificationError(
            "server GitHub App installation permission metadata is missing"
        )
    repository_selection = _required_text(
        payload.get("repository_selection"),
        "repository_selection",
    )
    if repository_selection not in {"all", "selected"}:
        raise GitHubServerInstallationVerificationError(
            "server GitHub App repository selection is invalid"
        )
    return ServerVerifiedInstallation(
        installation_id=str(response_id),
        account_id=str(_positive_id(account.get("id"), "account id")),
        account_login=_required_text(account.get("login"), "account login"),
        account_type=_required_text(account.get("type"), "account type"),
        repository_selection=repository_selection,
        permissions={
            str(key): str(value)
            for key, value in permissions.items()
            if str(key).strip() and str(value).strip()
        },
        status="suspended" if payload.get("suspended_at") else "active",
    )


def _positive_id(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise GitHubServerInstallationVerificationError(
            f"{label} must be a positive integer"
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise GitHubServerInstallationVerificationError(
            f"{label} must be a positive integer"
        ) from exc
    if parsed <= 0:
        raise GitHubServerInstallationVerificationError(
            f"{label} must be a positive integer"
        )
    return parsed


def _required_text(value: Any, label: str) -> str:
    selected = str(value or "").strip()
    if not selected:
        raise GitHubServerInstallationVerificationError(f"{label} is missing")
    return selected


__all__ = [
    "GitHubServerInstallationVerificationError",
    "ServerInstallationFetcher",
    "ServerVerifiedInstallation",
    "fetch_server_app_installation",
    "require_matching_user_installation",
    "resolve_binding_verification_authority",
    "verify_user_installation_against_server",
]
