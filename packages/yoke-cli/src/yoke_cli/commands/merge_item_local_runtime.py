"""Machine-local runtime for standalone-item merge execution.

The public CLI starts a child process so the merge engine can own signals and
exit status without importing engine internals into the command registry. This
runtime binds the machine's refresh-only GitHub App user authorization, then
selects the same-universe local Postgres connection before loading the engine.
"""

from __future__ import annotations

from contextlib import contextmanager
import importlib
import os
import sys
from typing import Callable, Iterator, List, Optional

from yoke_cli.config import github_local_user_access
from yoke_cli.config import github_merge_path_binding as merge_path_binding
from yoke_cli.config import machine_config
from yoke_contracts.github_auth_transience import TransientGitHubAuthError
from yoke_contracts.github_origin import GitHubApiEndpoint
from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    ENV_OVERRIDE,
    POSTGRES_TRANSPORTS,
    TRANSPORT_HTTPS,
    MachineConfigContractError,
    same_universe_db_admin_env,
)


class LocalMergeAuthorityError(RuntimeError):
    """The local merge process cannot bind one of its required authorities."""


class LocalMergeGithubAuthorityError(LocalMergeAuthorityError):
    """The local merge process cannot bind sanctioned GitHub user authority."""


class TransientLocalMergeGithubAuthorityError(
    LocalMergeGithubAuthorityError, TransientGitHubAuthError
):
    """Machine user authority was unreadable transiently, not absent."""


class LocalMergeControlPlaneAuthorityError(LocalMergeAuthorityError):
    """The local merge process cannot reach its universe through Postgres."""


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


@contextmanager
def same_universe_control_plane_authority() -> Iterator[tuple[str, str]]:
    """Select local Postgres for the same universe before merge admission."""

    try:
        config = machine_config.load_config()
        selected = machine_config.active_env()
        connection = machine_config.active_connection()
    except (machine_config.MachineConfigError, MachineConfigContractError) as exc:
        raise LocalMergeControlPlaneAuthorityError(
            "local merge control-plane authority is not configured"
        ) from exc
    transport = str(connection.get("transport") or "").strip()
    if transport in POSTGRES_TRANSPORTS:
        yield selected, selected
        return
    if transport != TRANSPORT_HTTPS:
        raise LocalMergeControlPlaneAuthorityError(
            f"local merge requires local Postgres before QA admission; "
            f"connected env {selected!r} uses unsupported transport {transport!r}"
        )
    authority = same_universe_db_admin_env(config, selected)
    if not authority:
        raise LocalMergeControlPlaneAuthorityError(
            f"local merge requires same-universe local Postgres before QA "
            f"admission; connected env {selected!r} uses HTTPS but has no "
            f"configured {selected + DB_ADMIN_ENV_SUFFIX!r} sibling"
        )
    previous = os.environ.get(ENV_OVERRIDE)
    os.environ[ENV_OVERRIDE] = authority
    try:
        yield selected, authority
    finally:
        if previous is None:
            os.environ.pop(ENV_OVERRIDE, None)
        else:
            os.environ[ENV_OVERRIDE] = previous


def run(argv: List[str]) -> int:
    """Load the engine under its GitHub and control-plane authorities."""

    with machine_github_user_authority():
        with same_universe_control_plane_authority() as (selected, authority):
            if selected != authority:
                print(
                    f"[phase:authority] control plane: {selected} -> {authority}",
                    file=sys.stderr,
                    flush=True,
                )
            merge_cli = importlib.import_module(
                "yoke_core.domain.standalone_item_merge_cli"
            )
            return int(merge_cli.main(argv))


def main(argv: Optional[List[str]] = None) -> int:
    try:
        return run(list(sys.argv[1:] if argv is None else argv))
    except LocalMergeAuthorityError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


__all__ = [
    "LocalMergeAuthorityError",
    "LocalMergeControlPlaneAuthorityError",
    "LocalMergeGithubAuthorityError",
    "TransientLocalMergeGithubAuthorityError",
    "machine_github_user_authority",
    "main",
    "run",
    "same_universe_control_plane_authority",
]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
