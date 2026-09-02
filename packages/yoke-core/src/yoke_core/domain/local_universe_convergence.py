"""Bring the machine-local universe up to the engine that is about to serve it.

A hosted container converges its own database before it answers a request
(:func:`yoke_core.api.server_entrypoint.ensure_core_schema`). The machine-local
universe has no such boot: the process that serves it is whichever ``yoke``
command the operator just ran, dispatching in-process. Upgrading the engine
therefore used to leave the universe behind its own code — additive columns and
tables the new build reads simply never arrived, and every later command,
health check, and board rebuild failed on the gap.

This module is that missing boot step, and it reuses
:func:`yoke_core.domain.schema_init.converge_core_schema` exactly: there is one
convergence implementation, and both the container and the local universe run
it. Serving-build authority applies for the same reason it applies to the
container — this process *is* the build about to serve the database it changes.
Additive foreign keys onto ``environments.id`` match the live primary-key type
so a universe still on text keys can reach the ordered history that converts
them, rather than failing the boot on an integer FK the prior shape cannot
implement.

Two facts are separated on purpose. :func:`serves_own_universe` answers whether
a DSN names the embedded cluster this machine owns, which is what entitles a
workstation to converge it; a non-prod Postgres connection pointed at somebody
else's cluster (a shared rehearsal database, a teammate's server) is not this
machine's to converge and answers ``False``. Machine-local bookkeeping — which
build last converged which universe, and what to tell the operator afterwards —
belongs to the client and lives in
:mod:`yoke_cli.engine_upgrade_convergence`.
"""

from __future__ import annotations


def serves_own_universe(dsn: str) -> bool:
    """Whether *dsn* names the embedded universe this machine owns.

    Ownership is decided by address, never by transport or connection label: a
    local-Postgres connection may equally name a shared cluster this machine
    only administers, and converging that one would move a database out from
    under the builds actually serving it. The comparison covers the socket
    aliases the cluster spec can produce, so a universe whose socket directory
    relocated to a shorter path is still recognized as the same one.
    """
    candidate = (dsn or "").strip()
    if not candidate:
        return False
    from yoke_core.domain import local_universe

    try:
        spec = local_universe.cluster_spec()
        addresses = {
            local_universe.local_dsn(spec),
            *local_universe.socket_dsn_aliases(spec),
        }
    except Exception:  # noqa: BLE001 - an unresolvable spec owns nothing
        return False
    return candidate in addresses


def converge_serving_schema() -> None:
    """Converge the ambient universe's schema, the way a server boot does.

    Fail-hard by design, mirroring the container: a process that could not
    bring the database up to its own code must not go on to serve it, because
    the alternative is the silent drift this step exists to remove.
    """
    from yoke_contracts.schema_authority import serving_build_authority
    from yoke_core.domain import db_backend, db_helpers
    from yoke_core.domain.schema_init import converge_core_schema

    with db_helpers.connect() as conn, serving_build_authority():
        converge_core_schema(conn, backup_target_dsn=db_backend.resolve_pg_dsn())


__all__ = ["converge_serving_schema", "serves_own_universe"]
