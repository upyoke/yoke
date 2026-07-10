"""Schema initialization orchestrator."""

from yoke_core.domain.actor_permissions import seed_roles_and_permissions
from yoke_core.domain.actors import seed_canonical_actors
from yoke_core.domain.auth_schema import create_auth_tables
from yoke_core.domain.events_schema import ensure_event_schema
from yoke_core.domain.external_identity_schema import create_external_identity_tables
from yoke_core.domain.github_app_schema import create_github_app_tables
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.schema_common import _connect_raw
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_identity_tables,
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_columns import (
    apply_additive_schema,
    apply_harness_session_columns,
    apply_legacy_data_migrations,
)
from yoke_core.domain.schema_init_tables import (
    create_core_tables,
    create_governed_tables,
    create_path_integrity_tables,
    create_path_registry_tables,
)
from yoke_core.domain.schema_init_work_claim_indexes import (
    create_work_claim_active_uniques,
)
from yoke_core.domain.strategy_docs import STRATEGY_DOCS_CREATE_TABLE_SQL


def converge_core_schema(conn) -> None:
    """Idempotently bring an existing DB's schema up to the current code.

    Runs every schema-CREATION step — tables, indexes, and strictly additive
    columns — in FK-dependency order, and nothing else: no seeds, no destructive
    drops, no data backfills. Safe to run on every server boot of an already-born
    universe, which is what propagates newly-deployed tables/columns to existing
    prod / self-host universes on the boot after a deploy (see
    :func:`yoke_core.api.server_entrypoint.ensure_core_schema`).

    This is the single source of the schema-creation sequence: :func:`cmd_init`
    runs it, then layers seeds and the birth-only data-shape migrations on top.
    Order matters — ``create_external_identity_tables`` FKs into actors,
    organizations (created by ``create_auth_tables``), and roles, so those
    creation steps precede it.
    """
    create_core_tables(conn)
    create_actor_identity_tables(conn)
    ensure_event_schema(conn)
    create_work_claim_active_uniques(conn)
    apply_harness_session_columns(conn)
    create_governed_tables(conn)
    create_path_registry_tables(conn)
    create_path_integrity_tables(conn)
    create_actor_path_claim_tables(conn)
    create_auth_tables(conn)
    create_external_identity_tables(conn)
    create_github_app_tables(conn)
    # Strategy authority landed on prod via a since-retired governed
    # migration; fresh envs get the table from the same DDL constant
    # the strategy domain owns.
    conn.execute(STRATEGY_DOCS_CREATE_TABLE_SQL)
    apply_additive_schema(conn)


def cmd_init() -> None:
    """Create DB and shared tables (idempotent)."""
    conn = _connect_raw("")
    try:
        converge_core_schema(conn)
        seed_roles_and_permissions(conn)
        seed_default_org(conn)
        apply_legacy_data_migrations(conn)
        # Seed the canonical actors after every other table and column
        # exists. Idempotent on re-run; the human label resolves from the
        # LOCAL_HUMAN_LABEL_ENV injection (pinned by the local-universe
        # birth path to the OS login) and falls back to the label the
        # migrated authoritative DB already maps, so re-init never
        # creates a duplicate human row.
        seed_canonical_actors(conn)
    finally:
        conn.close()
