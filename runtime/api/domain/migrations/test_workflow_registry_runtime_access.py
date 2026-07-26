from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

from psycopg import sql

from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migrations.workflow_registry_runtime_access import (
    MIGRATION_NAME,
    apply,
    invariants,
)
from runtime.api.domain.migrations import (
    workflow_registry_runtime_access as source_wrapper,
)

_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name("workflow_registry_runtime_access.migration.json")


def test_governed_manifest_is_valid_and_digest_bound():
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"]["workflow_registry_runtime_access"]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


def test_source_checkout_wrapper_exposes_packaged_migration():
    assert source_wrapper.MIGRATION_NAME == MIGRATION_NAME
    assert source_wrapper.apply is apply
    assert source_wrapper.invariants is invariants


def test_apply_is_idempotent_when_registry_already_matches_database_owner(test_db):
    apply(test_db)
    invariants(test_db)
    apply(test_db)
    invariants(test_db)


def test_apply_grants_database_owner_access_to_admin_owned_registry(
    test_db,
    cluster_role_authority,
):
    suffix = uuid.uuid4().hex[:12]
    admin_role = f"workflow_registry_admin_{suffix}"
    owner_role = f"workflow_registry_owner_{suffix}"
    database = str(test_db.execute("SELECT current_database()").fetchone()[0])
    session_role = str(test_db.execute("SELECT session_user").fetchone()[0])
    test_db.commit()
    test_db.autocommit = True
    try:
        test_db.execute(
            sql.SQL("CREATE ROLE {} CREATEROLE").format(sql.Identifier(admin_role))
        )
        test_db.execute(sql.SQL("CREATE ROLE {}").format(sql.Identifier(owner_role)))
        test_db.execute(
            sql.SQL("GRANT {} TO {}").format(
                sql.Identifier(admin_role),
                sql.Identifier(session_role),
            )
        )
        for table in ("workflows", "workflow_versions"):
            test_db.execute(
                sql.SQL("ALTER TABLE {} OWNER TO {}").format(
                    sql.Identifier(table),
                    sql.Identifier(admin_role),
                )
            )
        test_db.execute(
            sql.SQL(
                "ALTER FUNCTION workflow_versions_immutable_fn() OWNER TO {}"
            ).format(sql.Identifier(admin_role))
        )
        test_db.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(database),
                sql.Identifier(owner_role),
            )
        )
        test_db.execute(
            sql.SQL("ALTER TABLE items OWNER TO {}").format(sql.Identifier(owner_role))
        )
        test_db.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(admin_role)))
        test_db.autocommit = False

        apply(test_db)
        invariants(test_db)

        rows = test_db.execute(
            "SELECT c.relname, pg_get_userbyid(c.relowner) "
            "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' "
            "AND c.relname IN ('workflows', 'workflow_versions') "
            "ORDER BY c.relname"
        ).fetchall()
        assert rows == [
            ("workflow_versions", admin_role),
            ("workflows", admin_role),
        ]
        test_db.commit()
        test_db.autocommit = True
        test_db.execute("RESET ROLE")
        test_db.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(owner_role)))
        test_db.autocommit = False
        from yoke_core.domain.workflow_registry import converge_builtin_workflows
        from yoke_core.domain.workflow_schema import ensure_workflow_schema

        ensure_workflow_schema(test_db)
        converge_builtin_workflows(test_db)
    finally:
        test_db.rollback()
        test_db.autocommit = True
        test_db.execute("RESET ROLE")
        test_db.execute(
            sql.SQL("ALTER DATABASE {} OWNER TO {}").format(
                sql.Identifier(database),
                sql.Identifier(session_role),
            )
        )
        for table in ("workflows", "workflow_versions"):
            test_db.execute(
                sql.SQL("ALTER TABLE {} OWNER TO {}").format(
                    sql.Identifier(table),
                    sql.Identifier(session_role),
                )
            )
        test_db.execute(
            sql.SQL("ALTER TABLE items OWNER TO {}").format(
                sql.Identifier(session_role)
            )
        )
        test_db.execute(
            sql.SQL(
                "ALTER FUNCTION workflow_versions_immutable_fn() OWNER TO {}"
            ).format(sql.Identifier(session_role))
        )
        test_db.execute(
            sql.SQL("REVOKE {} FROM {}").format(
                sql.Identifier(admin_role),
                sql.Identifier(session_role),
            )
        )
        test_db.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(admin_role)))
        test_db.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(owner_role)))
        test_db.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(owner_role)))
        test_db.autocommit = False
