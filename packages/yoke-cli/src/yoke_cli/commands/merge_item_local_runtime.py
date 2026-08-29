"""Machine-local runtime for standalone-item merge execution.

The public CLI starts a child process so the merge engine can own signals and
exit status without importing engine internals into the command registry. This
runtime binds the machine's GitHub App user authorization, then
selects the same-universe local Postgres connection before loading the engine.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import importlib
import os
import sys
from typing import Any, Callable, Iterator, List, Optional

from yoke_cli.config import github_local_user_access
from yoke_cli.config import github_merge_path_binding as merge_path_binding
from yoke_cli.config import machine_config
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef
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


def _work_claim_lookup(argv: List[str]) -> Optional[dict[str, Any]]:
    """Read the item holder before an HTTPS connection yields to DB admin."""
    if not argv or "--help" in argv or "-h" in argv:
        return None
    parser = argparse.ArgumentParser(add_help=False, exit_on_error=False)
    parser.add_argument("item")
    parser.add_argument("--project", default=None)
    parser.add_argument("--session-id", default=None)
    try:
        parsed, _unknown = parser.parse_known_args(argv)
    except (argparse.ArgumentError, SystemExit):
        return None
    actor = build_actor(session_id=parsed.session_id)
    response = call_dispatcher(
        function_id="claims.work.holder_get",
        target=TargetRef(
            kind="item",
            item_ref=str(parsed.item),
            project_id=parsed.project,
        ),
        actor=actor,
    )
    return {
        "caller_session_id": str(actor.session_id or ""),
        "connection": str(machine_config.active_env() or "unknown"),
        "function_id": "claims.work.holder_get",
        "response": response,
    }


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


def _confirm_selected_control_plane(authority: str) -> None:
    """Refuse before the merge starts when the selected control plane is down.

    Selecting the connection is not the same as reaching it. A local Postgres
    sibling normally sits behind an SSH forward, and a forward that has died —
    a changed network, a slept machine — answers the *first* dispatched call
    of the merge rather than this one, which is how a merge came to fail
    halfway through with a tunnel error after its control plane had silently
    moved underneath it. Probing here restarts a recoverable forward and turns
    an unrecoverable one into a refusal that costs nothing.
    """
    try:
        readiness = importlib.import_module(
            "yoke_core.domain.connected_env_readiness"
        )
    except ImportError as exc:
        raise LocalMergeControlPlaneAuthorityError(
            "local merge requires matching yoke-cli and yoke-core releases; "
            "repair the Yoke installation, then retry"
        ) from exc
    try:
        result = readiness.ensure_ready(force=True)
    except Exception as exc:  # noqa: BLE001 - every failure is the same refusal
        raise LocalMergeControlPlaneAuthorityError(
            f"local merge selected control plane {authority!r}, which is not "
            f"reachable: {exc}. Restore the connection, then re-run the merge; "
            "nothing has been merged."
        ) from exc
    if not result.ok:
        raise LocalMergeControlPlaneAuthorityError(
            f"local merge selected control plane {authority!r}, which is not "
            f"reachable: {result.message}. Restore the connection, then re-run "
            "the merge; nothing has been merged."
        )


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
        _confirm_selected_control_plane(authority)
        yield selected, authority
    finally:
        if previous is None:
            os.environ.pop(ENV_OVERRIDE, None)
        else:
            os.environ[ENV_OVERRIDE] = previous


def run(argv: List[str]) -> int:
    """Load the engine under its GitHub and control-plane authorities."""

    with machine_github_user_authority():
        claim_lookup = _work_claim_lookup(argv)
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
            if claim_lookup is None:
                return int(merge_cli.main(argv))
            recovery = importlib.import_module(
                "yoke_core.domain.standalone_item_merge_recovery"
            )
            with recovery.bind_work_claim_lookup(claim_lookup):
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
