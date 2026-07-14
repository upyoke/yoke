"""Single source of truth for applying the full canonical Yoke schema.

Runs the production schema-init functions against the connection passed in.
Consumers:

- ``runtime.api.fixtures.schema_ddl_items`` derives the fixture items-family
  DDL by applying this to a disposable Postgres scratch database and reading
  the shape back from the catalog.
- The migration-harness tests build their legacy SQLite validation files
  with it, mirroring a fully schema-inited install.

Keeping the apply *sequence* here (rather than duplicated in each consumer)
means a future schema-init step is added in one place and every consumer
picks it up.
"""

from __future__ import annotations

# items columns added by historical one-shot migrations that the fresh-init
# bootstrap path does not apply; the canonical DB carries them, so the test
# schema must too. Kept idempotent via _column_exists so re-apply is safe.
_ITEMS_LEGACY_COLUMNS = (
    ("resolution", "TEXT"),
    ("resolution_ref", "TEXT"),
    ("resolution_comment", "TEXT"),
)


def apply_canonical_schema(conn) -> None:
    """Create the full canonical Yoke schema on *conn* (any backend)."""
    from yoke_core.domain.schema_init_tables import (
        create_core_tables,
        create_governed_tables,
        create_path_integrity_tables,
        create_path_registry_tables,
    )
    from yoke_core.domain.schema_init_actor_path_claim_tables import (
        create_actor_identity_tables,
        create_actor_path_claim_tables,
    )
    from yoke_core.domain.schema_init_columns import (
        apply_harness_session_columns,
        apply_idempotent_migrations,
    )
    from yoke_core.domain.schema_common import _column_exists
    from yoke_core.domain.actor_permissions import seed_roles_and_permissions
    from yoke_core.domain.auth_schema import create_auth_tables
    from yoke_core.domain.events_schema import ensure_event_schema
    from yoke_core.domain.external_identity_schema import (
        create_external_identity_tables,
    )
    from yoke_core.domain.org_schema import seed_default_org
    from yoke_core.domain.project_seed_test_helpers import seed_project_identities
    from yoke_core.domain.shepherd import cmd_init as shepherd_cmd_init

    create_core_tables(conn)
    seed_project_identities(conn)
    create_actor_identity_tables(conn)
    ensure_event_schema(conn)
    apply_harness_session_columns(conn)
    create_governed_tables(conn)
    create_path_registry_tables(conn)
    create_path_integrity_tables(conn)
    create_actor_path_claim_tables(conn)
    create_auth_tables(conn)
    create_external_identity_tables(conn)
    seed_default_org(conn)
    seed_roles_and_permissions(conn)
    apply_idempotent_migrations(conn)
    shepherd_cmd_init(conn)
    for col, ctype in _ITEMS_LEGACY_COLUMNS:
        if not _column_exists(conn, "items", col):
            conn.execute(f"ALTER TABLE items ADD COLUMN {col} {ctype}")
    conn.commit()


__all__ = ["apply_canonical_schema"]
