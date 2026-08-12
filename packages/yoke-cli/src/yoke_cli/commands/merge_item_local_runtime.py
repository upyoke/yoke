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

from yoke_cli.config import github_local_user_access
from yoke_cli.config import github_merge_path_binding as merge_path_binding
from yoke_contracts.github_auth_transience import TransientGitHubAuthError
from yoke_contracts.github_origin import GitHubApiEndpoint


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

    selection = merge_path_binding.resolve_selection()

    def access_token() -> str:
        if not selection.resolved:
            raise LocalMergeGithubAuthorityError(
                merge_path_binding.RECONNECT_RECOVERY
            )
        try:
            token = github_local_user_access.access_token(
                service_api_url=selection.service_api_url,
                local_connection_selected=selection.local_connection_selected,
            ).access_token
        except github_local_user_access.TransientGitHubLocalUserAccessError as exc:
            raise TransientLocalMergeGithubAuthorityError(
                merge_path_binding.RETRY_RECOVERY
            ) from exc
        except github_local_user_access.GitHubLocalUserAccessError as exc:
            raise LocalMergeGithubAuthorityError(
                merge_path_binding.RECONNECT_RECOVERY
            ) from exc
        value = str(token or "").strip()
        if not value:
            raise LocalMergeGithubAuthorityError(
                merge_path_binding.RECONNECT_RECOVERY
            )
        return value

    return selection.endpoint, access_token


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
    "LocalMergeGithubAuthorityError",
    "TransientLocalMergeGithubAuthorityError",
    "machine_github_user_authority",
    "main",
    "run",
]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
