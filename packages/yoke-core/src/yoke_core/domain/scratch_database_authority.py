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

So the refusal rides the connection, the way
:mod:`yoke_contracts.schema_authority` does for convergence, and reads the
same prod flag — it is the same fact, that administering a database is not
owning it. Three things have to hold together before that flag means a
scratch database would land on the administered cluster, and
:func:`administering_scratch_cluster` requires all three, because a refusal
that fires when the databases were never going in that direction would stop
every ordinary local run. A caller that genuinely owns the cluster it creates
on — a throwaway cluster it started itself — says so with
:func:`owned_scratch_cluster`, at the call site, rather than through an
allowlist of module paths that rots as files move.

A ContextVar rather than a process global, for the reason
:mod:`yoke_contracts.control_plane_locality` uses one: a server relays many
requests through one interpreter, and a process-wide flag set for one of them
leaks into every concurrent one.
"""

from __future__ import annotations

import contextvars
import os
from contextlib import contextmanager
from typing import Iterator

from yoke_contracts.control_plane_locality import PG_DSN_ENV, PG_DSN_FILE_ENV
from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.schema_transport import POSTGRES_TRANSPORTS
from yoke_contracts.schema_authority import prod_flagged_connection


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


def administering_scratch_cluster() -> str:
    """Return the connection a scratch database would land on, when administered.

    Empty unless all three facts hold. The selected connection is flagged
    prod, so this machine administers the database it names without serving
    it. It carries a Postgres transport, so it resolves to a cluster at all —
    an https connection relays and hands out no cluster to create on. And
    nothing else named a target, so the cluster IS inherited from it: an
    explicit ``YOKE_PG_DSN``, a DSN file, or a context-bound authority each
    name their own cluster, which is how the sanctioned test runners point a
    suite at the local test cluster while an administering connection is
    still selected.
    """
    # The named-target checks come first because they are two dict lookups
    # and answer for every ordinary local run, which is pointed at its own
    # cluster; reading machine config to reach the same answer would put a
    # file read on the path of every database a suite creates.
    if os.environ.get(PG_DSN_ENV) or os.environ.get(PG_DSN_FILE_ENV):
        return ""
    # Local import: this module is read by the naming factory that db_backend
    # itself has no knowledge of, and keeping the edge one-way leaves the
    # import graph honest about which of the two is the lower layer.
    from yoke_core.domain import db_backend

    if db_backend.pg_dsn_is_bound():
        return ""
    env = prod_flagged_connection()
    if not env:
        return ""
    try:
        connection = machine_config_runtime.active_connection()
    except Exception:  # noqa: BLE001 - config problems surface where they are
        return ""
    if str(connection.get("transport") or "").strip() not in POSTGRES_TRANSPORTS:
        return ""
    return env


def refuse_scratch_database_on_administered_cluster(name: str) -> None:
    """Raise when *name* would be created on a cluster this process only administers.

    A no-op wherever the cluster is the run's own, which is every local
    universe, every self-hosted universe, every container, every machine with
    no config at all, and every run pointed at an explicit DSN of its own.
    """
    if _owned_cluster.get():
        return
    env = administering_scratch_cluster()
    if not env:
        return
    raise ScratchDatabaseRefused(
        f"scratch database {name!r} refused: connection {env!r} is flagged "
        "prod and nothing else names a cluster, so this database would be "
        "created on one this machine administers but does not own. A "
        "disposable test database belongs on the local test cluster or a "
        "declared validation surface. Start a cluster this run owns with "
        "`yoke dev run -- python3 -m yoke_core.tools.pg_testcluster start` "
        "and export the YOKE_PG_DSN it prints, or select a non-prod "
        f"connection with YOKE_ENV, then re-run; `yoke watch pytest` and the "
        "generic runner already drop the administering selection for you. "
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
