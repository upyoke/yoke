"""Empty-environment Yoke DB bootstrap — the one complete init entrypoint.

Owns the policy for initializing an EMPTY Postgres database into a complete
Yoke control-plane DB: schema tables and catalog seeds (roles/permissions,
default org, canonical actors, capability templates), the projects family
tables (no project rows — projects enter through onboarding), QA and
deployment-run tables, and event-registry population. Stage, ephemeral, and self-host
environment databases bootstrap through this module. The governed migration
path applies only to a project's declared authoritative DB (prod); stage and
ephemeral data is throwaway by definition, so refreshing a non-authoritative
env schema is "re-run this bootstrap" (idempotent) or destroy-and-recreate —
never a governed migration.

``INIT_MODULE_CHAIN`` is the canonical init order. ``db_router init``
consumes the same chain opportunistically (swallowing per-module errors for
ambient auto-init); :func:`run_bootstrap` is the loud production form — any
module failure aborts the bootstrap naming the module.

Direct form against an explicit authority (self-host / disposable local):

    YOKE_PG_DSN='host=... user=... dbname=...' \\
        python3 -m yoke_core.domain.environment_bootstrap

Deploy-environment form (resolves the env DSN from Pulumi stack outputs +
the RDS-managed master secret):

    python3 -m yoke_core.domain.deploy_environment_bootstrap <project> <env>
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Callable, Dict, Optional

#: Canonical schema/domain init order — schema first, then domains that
#: depend on the ``items``/``projects`` tables. One source of truth shared
#: with ``db_router init`` (which imports it as ``_AUTO_INIT_MODULES``).
_FLOW_INIT_MODULE = "yoke_core.domain.flow"

INIT_MODULE_CHAIN: tuple = (
    "yoke_core.domain.schema",
    "yoke_core.domain.shepherd",
    "yoke_core.domain.designs",
    "yoke_core.domain.projects",
    "yoke_core.domain.project_structure",
    _FLOW_INIT_MODULE,
    "yoke_core.domain.events_crud",
    "yoke_core.domain.qa",
    "yoke_core.domain.deployment_runs",
    # Finalize the progress view after QA/deployment tables exist. The first
    # flow pass creates the tables needed by later modules; this idempotent
    # second pass replaces its bootstrap fallback with the full canonical view.
    _FLOW_INIT_MODULE,
)

#: Sentinel tables a complete control-plane DB must carry, paired with the
#: minimum seed-row count each must hold after a successful bootstrap.
#: Zero means "table exists" without a seed expectation.
#: A fresh universe seeds NO project rows (projects enter through
#: onboarding), so ``projects`` and ``deployment_flows`` are
#: existence-only sentinels; ``capability_templates`` carries the
#: generic vocabulary every complete control plane ships.
_VERIFY_SENTINELS: Dict[str, int] = {
    "items": 0,
    "designs": 0,
    "projects": 0,
    "sites": 0,
    "environments": 0,
    "capability_templates": 1,
    "project_capabilities": 0,
    "deployment_flows": 0,
    "deployment_runs": 0,
    "event_registry": 1,
    "events": 0,
    "api_tokens": 0,
    "roles": 4,
    "permissions": 10,
    "organizations": 1,
    "actors": 1,
}


class BootstrapError(RuntimeError):
    """Environment bootstrap failed; message names the failing step."""


def _emit(line: str) -> None:
    print(line, flush=True)


def run_init_chain(emit: Callable[[str], None] = _emit) -> None:
    """Run every init module loudly against the ambient DB authority.

    Unlike ``db_router init``'s opportunistic auto-init, a module that
    raises or exits nonzero aborts the bootstrap with the module named.
    """
    for modname in INIT_MODULE_CHAIN:
        emit(f"  [env-bootstrap] init {modname}")
        try:
            module = importlib.import_module(modname)
            rc = module.main(["init"])
        except SystemExit as exc:  # argparse / cmd-level exits
            rc = exc.code
        except BootstrapError:
            raise
        except Exception as exc:
            raise BootstrapError(
                f"[env-bootstrap] init module {modname} raised: {exc}"
            ) from exc
        if rc not in (None, 0):
            raise BootstrapError(f"[env-bootstrap] init module {modname} exited {rc}")


def populate_event_registry(
    repo_root: Optional[Path] = None,
    emit: Callable[[str], None] = _emit,
) -> str:
    """Populate the event registry (DB rows only, no catalog doc render)."""
    from yoke_core.domain.populate_registry import populate

    root = repo_root or _event_scan_root()
    emit("  [env-bootstrap] populate event registry")
    summary = populate(repo_root=str(root))
    emit(f"  [env-bootstrap] event registry: {summary}")
    return summary


def _event_scan_root() -> Path:
    """The event-discovery scan root: the repo, else the server source tree.

    Source checkouts resolve to the repo root. Containers and product wheels
    use the install-bundle source-tree resolver, which handles declared
    server roots, source-runtime layouts, and the packaged bundle tree.
    """
    from yoke_core.api.repo_root import find_repo_root

    try:
        return find_repo_root(Path(__file__))
    except RuntimeError:
        from yoke_core.domain.install_bundle import server_tree_root

        return server_tree_root()


def universe_is_born(dsn: str) -> bool:
    """True when the database at ``dsn`` already carries a bootstrapped org card.

    The single born-ness probe shared by every "is this DB a live universe?"
    caller (the embedded local universe and the API server's first-boot
    check). The org identity card is the birth sentinel: a completed
    bootstrap seeds exactly one ``organizations`` row, so its presence
    separates a born universe from an empty database. An unreachable
    database or a missing table reads as "not born" — callers that need a
    completeness guarantee follow up with :func:`verify_bootstrap`.
    """
    import psycopg

    from yoke_core.domain import db_backend

    try:
        conn = db_backend.connect_psycopg(dsn)
    except psycopg.OperationalError:
        return False
    try:
        with conn:
            row = conn.execute("SELECT COUNT(*) FROM organizations").fetchone()
            return bool(row and int(row[0]) >= 1)
    except psycopg.errors.UndefinedTable:
        return False
    finally:
        conn.close()


def verify_bootstrap(emit: Callable[[str], None] = _emit) -> Dict[str, int]:
    """Assert the sentinel tables exist with their minimum seed counts."""
    from yoke_core.domain.db_helpers import connect, query_scalar

    counts: Dict[str, int] = {}
    conn = connect()
    try:
        for table, minimum in _VERIFY_SENTINELS.items():
            try:
                count = int(query_scalar(conn, f"SELECT COUNT(*) FROM {table}") or 0)
            except Exception as exc:
                raise BootstrapError(
                    f"[env-bootstrap] verification failed: sentinel table "
                    f"'{table}' is unreadable after init: {exc}"
                ) from exc
            if count < minimum:
                raise BootstrapError(
                    f"[env-bootstrap] verification failed: table '{table}' "
                    f"has {count} rows, expected >= {minimum}"
                )
            counts[table] = count
    finally:
        conn.close()
    emit(
        "  [env-bootstrap] verified: "
        + ", ".join(f"{t}={c}" for t, c in sorted(counts.items()))
    )
    return counts


def run_bootstrap(
    repo_root: Optional[Path] = None,
    emit: Callable[[str], None] = _emit,
) -> Dict[str, int]:
    """Full bootstrap: init chain, event registry, verification."""
    run_init_chain(emit)
    populate_event_registry(repo_root, emit)
    return verify_bootstrap(emit)


def run_init_chain_at_dsn(
    dsn: str,
    emit: Callable[[str], None] = _emit,
) -> None:
    """Materialize the complete schema chain at a context-bound authority.

    The binding is context-local rather than process-global, so hosted import
    requests can materialize trusted staging schemas concurrently without
    rebinding the platform database or another import. This schema-only entry
    point deliberately skips event-registry source scanning; callers that need
    the full seeded environment continue to use :func:`run_bootstrap`.
    """
    from yoke_core.domain.db_backend import bound_pg_dsn

    with bound_pg_dsn(dsn):
        run_init_chain(emit=emit)


def main(argv: Optional[list] = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if args:
        print(
            "Usage: python3 -m yoke_core.domain.environment_bootstrap\n"
            "Bootstraps the ambient Postgres authority (YOKE_PG_DSN or the\n"
            "connected machine-config authority) to the complete Yoke\n"
            "control-plane shape. Takes no arguments.",
            file=sys.stderr,
        )
        return 2
    try:
        run_bootstrap()
    except BootstrapError as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    print("[env-bootstrap] bootstrap complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
