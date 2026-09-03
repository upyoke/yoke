"""Whether a disposable database may be created where this process is pointed.

A scratch database is disposable by construction: a suite creates it, fills
it with fixture rows, and drops it. That is safe on a cluster the run owns,
and exactly wrong on one it does not. The cluster is rarely chosen — with no
DSN of its own a run inherits whichever connection happens to be selected,
and a prod-flagged connection names a database this machine administers but
does not own.

That inheritance leaked twice in one day. A session legitimately holding the
prod admin connection — for fleet-preflight evidence — ran a suite in the
same shell; the suite resolved its cluster from that selection, created its
scratch databases on prod, and was interrupted before its own cleanup ran.
The strays then survived as apparent fleet members: the next release's fleet
rehearsal converged them, met the ledger of a run that no longer existed, and
refused.

So the refusal rides the concrete target. The resolved DSN or live connection
is reduced to its host/port cluster endpoint and compared with every
prod-flagged local-Postgres connection registered on this machine. An explicit
DSN is not an exemption: a raw DSN aimed at an administered SSH forward is the
same target as selecting that connection. The migration-history birth guard
reads the same predicate, so fixture naming and schema stamping cannot disagree.
A caller that genuinely owns the cluster it creates on — a throwaway cluster
it started itself — says so with
:func:`owned_scratch_cluster`, at the call site, rather than through an
allowlist of module paths that rots as files move.

A ContextVar rather than a process global, for the reason
:mod:`yoke_contracts.control_plane_locality` uses one: a server relays many
requests through one interpreter, and a process-wide flag set for one of them
leaks into every concurrent one.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Iterator

from yoke_core.domain import administered_postgres


class ScratchDatabaseRefused(BaseException):
    """A scratch database was requested on a cluster this process only administers.

    Outside the ``Exception`` hierarchy on purpose, the way
    :class:`yoke_contracts.schema_authority.SchemaAuthorityRefused` is. The
    provisioning this guards sits under conftest imports and pytest fixtures,
    which render a raised ``Exception`` as one collection error among many and
    carry on; a refusal about a production cluster has to stop the run rather
    than become a red line nobody reads to the end of.
    """


#: Context-scoped declaration that the caller owns the cluster it creates on.
#: The default False means "undeclared", which is the right answer for every
#: ordinary suite: it takes whatever cluster its connection resolves to.
_owned_cluster: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "owned_scratch_cluster",
    default=False,
)


@contextmanager
def owned_scratch_cluster() -> Iterator[None]:
    """Declare that this block creates scratch databases on a cluster it owns.

    The claim is about the cluster, not the command: that these databases go
    somewhere nothing else serves from, so leaving one behind costs nobody
    anything. A tool that starts its own throwaway cluster is entitled to it;
    a suite that inherited its cluster from the ambient connection is not.
    """
    token = _owned_cluster.set(True)
    try:
        yield
    finally:
        _owned_cluster.reset(token)


def owned_scratch_cluster_declared() -> bool:
    """Return whether this context declared ownership of its cluster."""
    return _owned_cluster.get()


def administering_scratch_cluster(target_dsn: str | None = None) -> str:
    """Return the connection a scratch database would land on, when administered.

    The caller may provide the exact DSN it will write through. Otherwise the
    canonical backend resolver covers a context binding, ``YOKE_PG_DSN``, its
    file form, and the selected connection in their normal precedence order.
    If no concrete target can be resolved, the selected prod local-Postgres
    connection remains the fail-closed backstop; an HTTPS connection never
    names a cluster.
    """
    if target_dsn is None:
        from yoke_core.domain import db_backend

        try:
            target_dsn = db_backend.resolve_pg_dsn()
        except Exception:  # noqa: BLE001 - target setup errors retain backstop
            target_dsn = None
    return administered_postgres.administering_target(dsn=target_dsn)


def refuse_scratch_database_on_administered_cluster(
    name: str,
    *,
    target_dsn: str | None = None,
) -> None:
    """Raise when *name* would be created on a cluster this process only administers.

    A no-op wherever the cluster is the run's own, which is every local
    universe, every self-hosted universe, every container, every machine with
    no config at all, and every run pointed at an explicit DSN of its own.
    """
    if _owned_cluster.get():
        return
    env = administering_scratch_cluster(target_dsn)
    if not env:
        return
    raise ScratchDatabaseRefused(
        f"scratch database {name!r} refused: its target matches administered "
        f"Postgres connection {env!r}, so it would be created on a cluster "
        "this machine administers but does not own. Run tests through "
        "`yoke watch pytest`, which isolates the administering selection, or "
        "point the run at the local test cluster. A "
        "disposable test database belongs on the local test cluster or a "
        "declared validation surface. Start a cluster this run owns with "
        "`yoke dev run -- python3 -m yoke_core.tools.pg_testcluster start` "
        "and export the YOKE_PG_DSN it prints, or select a non-prod "
        f"connection with YOKE_ENV, then re-run. "
        "Strays already on that cluster are removed with `python3 -m "
        "runtime.api.tools.drop_leftover_test_databases`. A tool that creates "
        "scratch databases on a cluster it owns outright declares that with "
        "yoke_core.domain.scratch_database_authority.owned_scratch_cluster()."
    )


__all__ = [
    "ScratchDatabaseRefused",
    "administering_scratch_cluster",
    "owned_scratch_cluster",
    "owned_scratch_cluster_declared",
    "refuse_scratch_database_on_administered_cluster",
]
