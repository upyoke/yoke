"""Machine-local runtime for standalone-item merge execution.

The public CLI starts a child process so the merge engine can own signals and
exit status without importing engine internals into the command registry. A
context variable cannot cross that process boundary, so this runtime binds the
machine's refresh-only GitHub App user authorization inside the child before
loading the engine entrypoint.
"""

from __future__ import annotations

from contextlib import contextmanager
import importlib
import sys
from typing import Callable, Iterator, List, Optional

from yoke_cli.config import github_app_public_profile
from yoke_cli.config import github_local_user_access
from yoke_cli.config import machine_config
from yoke_contracts.github_auth_transience import (
    GITHUB_AUTH_RETRY_RECIPE,
    TransientGitHubAuthError,
)
from yoke_contracts.github_origin import (
    GitHubApiEndpoint,
    GitHubApiOriginError,
    validate_github_api_endpoint,
)


LOCAL_AUTH_RECOVERY = (
    "machine GitHub App user authorization is unavailable for the active "
    "Yoke connection; run `yoke github status`, then reconnect GitHub with "
    "`yoke github connect`"
)
LOCAL_AUTH_RETRY_RECOVERY = (
    "machine GitHub App user authorization could not be read right now "
    "(another local operation holds it, or GitHub could not be reached); the "
    f"stored authorization still stands, so {GITHUB_AUTH_RETRY_RECIPE}"
)


class LocalMergeGithubAuthorityError(RuntimeError):
    """The local merge process cannot bind sanctioned GitHub user authority."""


class TransientLocalMergeGithubAuthorityError(
    LocalMergeGithubAuthorityError, TransientGitHubAuthError
):
    """Machine user authority was unreadable transiently, not absent."""


def _machine_authority() -> tuple[GitHubApiEndpoint, Callable[[], str]]:
    """Return an exact-origin, lazy machine user-token provider.

    Configuration failures stay lazy so non-GitHub setup in the child can run,
    but the provider always fails closed with reconnect guidance before core
    can fall through to service-side App credentials.
    """

    selection_invalid = False
    try:
        github = machine_config.github_config()
        if not github:
            selection_invalid = True
        endpoint = validate_github_api_endpoint(
            str(github.get("api_url") or "") if github else None
        )
    except (GitHubApiOriginError, machine_config.MachineConfigError):
        endpoint = validate_github_api_endpoint(None)
        selection_invalid = True

    try:
        service_api_url = github_app_public_profile.selected_https_service_api_url()
        local_connection_selected = service_api_url is None
    except github_app_public_profile.GitHubAppPublicProfileError:
        service_api_url = None
        local_connection_selected = False
        selection_invalid = True

    def access_token() -> str:
        if selection_invalid:
            raise LocalMergeGithubAuthorityError(LOCAL_AUTH_RECOVERY)
        try:
            token = github_local_user_access.access_token(
                service_api_url=service_api_url,
                local_connection_selected=local_connection_selected,
            ).access_token
        except github_local_user_access.TransientGitHubLocalUserAccessError as exc:
            raise TransientLocalMergeGithubAuthorityError(
                LOCAL_AUTH_RETRY_RECOVERY
            ) from exc
        except github_local_user_access.GitHubLocalUserAccessError as exc:
            raise LocalMergeGithubAuthorityError(LOCAL_AUTH_RECOVERY) from exc
        value = str(token or "").strip()
        if not value:
            raise LocalMergeGithubAuthorityError(LOCAL_AUTH_RECOVERY)
        return value

    return endpoint, access_token


@contextmanager
def machine_github_user_authority() -> Iterator[None]:
    """Bind machine user authority for the entire local merge child."""

    endpoint, provider = _machine_authority()
    try:
        auth_module = importlib.import_module("yoke_core.domain.project_github_auth")
        bind = getattr(auth_module, "bind_local_github_user_token_provider")
    except (ImportError, AttributeError) as exc:
        raise LocalMergeGithubAuthorityError(
            "local merge requires matching yoke-cli and yoke-core releases; "
            "repair the Yoke installation, then retry"
        ) from exc
    with bind(provider, api_url=endpoint):
        yield


def run(argv: List[str]) -> int:
    """Load and execute the engine entrypoint under local user authority."""

    with machine_github_user_authority():
        merge_cli = importlib.import_module(
            "yoke_core.domain.standalone_item_merge_cli"
        )
        return int(merge_cli.main(argv))


def main(argv: Optional[List[str]] = None) -> int:
    try:
        return run(list(sys.argv[1:] if argv is None else argv))
    except LocalMergeGithubAuthorityError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


__all__ = [
    "LOCAL_AUTH_RECOVERY",
    "LOCAL_AUTH_RETRY_RECOVERY",
    "LocalMergeGithubAuthorityError",
    "TransientLocalMergeGithubAuthorityError",
    "machine_github_user_authority",
    "main",
    "run",
]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
