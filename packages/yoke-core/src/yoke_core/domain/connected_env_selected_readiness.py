"""Environment-explicit readiness for one configured Postgres authority.

Migration administration names a connection instead of inheriting the active
control plane.  This module validates that exact machine-config entry, resolves
only its declared credential source, and evaluates the existing tunnel
readiness path with the resolved DSN context-bound ahead of ambient overrides.
"""

from __future__ import annotations

import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator

from yoke_contracts.machine_config import schema as contract
from yoke_core.domain import connected_env_readiness_tunnel as _tunnel
from yoke_core.domain import db_backend, yoke_connected_env
from yoke_core.domain.connected_env_readiness_connector import ReadinessResult


class SelectedPostgresError(yoke_connected_env.ConnectedEnvError):
    """The explicitly named connection is absent or is not Postgres."""


@dataclass(frozen=True)
class SelectedPostgresAuthority:
    """Secret-safe handle to the exact authority prepared for a caller."""

    environment: str
    dsn: str = field(repr=False)
    readiness: ReadinessResult


_SELECTION_LOCK = threading.RLock()
_MISSING = object()


@contextmanager
def _environment_override(environment: str) -> Iterator[None]:
    """Select one env for legacy ambient resolvers, then restore the caller."""

    previous = os.environ.get(contract.ENV_OVERRIDE, _MISSING)
    os.environ[contract.ENV_OVERRIDE] = environment
    try:
        yield
    finally:
        if previous is _MISSING:
            os.environ.pop(contract.ENV_OVERRIDE, None)
        else:
            os.environ[contract.ENV_OVERRIDE] = str(previous)


def activate_selected_postgres(environment: str) -> SelectedPostgresAuthority:
    """Prepare exactly one named, configured Postgres connection.

    The temporary env selection exists only because the established connected-
    env resolver is ambient.  The declared DSN is resolved directly through
    that resolver, then context-bound while tunnel evaluation runs.  Therefore
    an unrelated ``YOKE_PG_DSN`` cannot replace the selected authority, and the
    caller's preexisting ``YOKE_ENV`` is unchanged when this function returns.
    """

    selected = environment.strip()
    if not selected:
        raise SelectedPostgresError("name a configured Postgres connection")

    with _SELECTION_LOCK, _environment_override(selected):
        try:
            active = yoke_connected_env.load_active()
            if active is None or active.environment != selected:
                raise SelectedPostgresError(
                    f"connection {selected!r} is not configured"
                )
            if active.backend != db_backend.POSTGRES:
                raise SelectedPostgresError(
                    f"connection {selected!r} uses transport {active.backend!r}; "
                    "this operation requires local-postgres"
                )
            resolved = yoke_connected_env.resolve_postgres_dsn(
                dsn_env=db_backend.PG_DSN_ENV,
                dsn_file_env=db_backend.PG_DSN_FILE_ENV,
            )
        except yoke_connected_env.ConnectedEnvError as exc:
            if isinstance(exc, SelectedPostgresError):
                raise
            raise SelectedPostgresError(
                f"connection {selected!r} could not be resolved: {exc}"
            ) from exc

        with db_backend.bound_pg_dsn(resolved.dsn):
            readiness = _tunnel.evaluate(allow_restart=True)

    if readiness.environment != selected:
        raise SelectedPostgresError(
            f"readiness evaluated {readiness.environment!r}, not {selected!r}"
        )
    return SelectedPostgresAuthority(
        environment=selected,
        dsn=resolved.dsn,
        readiness=readiness,
    )


__all__ = [
    "SelectedPostgresAuthority",
    "SelectedPostgresError",
    "activate_selected_postgres",
]
