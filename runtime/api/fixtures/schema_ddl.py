"""Test-fixture schema DDL assembler and apply helpers.

Composes ``SCHEMA_DDL`` by concatenating the table-family DDL strings in
fixed order: items, epic/QA, runtime, strategy, auth, onboarding, then merge
locks.
The items family is derived from canonical schema initialization in
``schema_ddl_items``; the other families are fixture-owned native
Postgres DDL.

``SCHEMA_DDL`` is a lazy module attribute: the items-family derivation
reads a disposable Postgres scratch database, so composition is deferred
to first access instead of import time. Importing this module never
requires a live test cluster.

Disposable Postgres fixture databases apply this DDL through
``apply_fixture_schema`` / ``apply_fixture_ddl``, which execute one
native statement at a time through the canonical schema-script executor.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures.schema_ddl_auth import _AUTH_DDL
from runtime.api.fixtures.schema_ddl_epic_qa import _EPIC_QA_DDL
from runtime.api.fixtures.schema_ddl_merge_locks import _MERGE_LOCKS_DDL
from runtime.api.fixtures.schema_ddl_runtime import _RUNTIME_DDL
from runtime.api.fixtures.schema_ddl_strategy import _STRATEGY_DDL


def _schema_ddl() -> str:
    composed = globals().get("SCHEMA_DDL")
    if composed is None:
        from runtime.api.fixtures.schema_ddl_items import _ITEMS_DDL
        from yoke_core.domain.project_onboarding_runs import (
            PROJECT_ONBOARDING_CHECKLIST_ROWS_CREATE_SQL,
            PROJECT_ONBOARDING_RUN_FOREIGN_KEY_SQL,
            PROJECT_ONBOARDING_RUNS_CREATE_SQL,
        )
        from yoke_core.domain.pack_projection import (
            PACK_CATALOG_TABLE_SQL,
            PROJECT_PACK_REPORT_ENTRIES_TABLE_SQL,
            PROJECT_PACK_REPORTS_TABLE_SQL,
        )
        from yoke_core.domain.ui_preferences_schema import (
            ACTOR_UI_PREFERENCES_CREATE_SQL,
            OVERVIEW_ACTIVATION_FACTS_CREATE_SQL,
        )
        from yoke_core.domain.workflow_schema import WORKFLOW_TABLES_SQL
        from yoke_core.domain.item_worktree_schema import (
            ITEM_WORKTREES_INDEX_SQL,
            ITEM_WORKTREES_TABLE_SQL,
        )

        onboarding_rows_without_fk = (
            PROJECT_ONBOARDING_CHECKLIST_ROWS_CREATE_SQL.replace(
                f",\n    {PROJECT_ONBOARDING_RUN_FOREIGN_KEY_SQL}",
                "",
            )
        )
        pack_reports_without_fk = PROJECT_PACK_REPORTS_TABLE_SQL.replace(
            " REFERENCES projects(id) ON DELETE CASCADE",
            "",
        )
        pack_entries_without_fk = PROJECT_PACK_REPORT_ENTRIES_TABLE_SQL.replace(
            " REFERENCES projects(id) ON DELETE CASCADE",
            "",
        )
        ui_preferences_without_fk = ACTOR_UI_PREFERENCES_CREATE_SQL.replace(
            " REFERENCES actors(id)",
            "",
        )
        workflow_tables_without_fk = WORKFLOW_TABLES_SQL.replace(
            " REFERENCES workflows(id)",
            "",
        )
        composed = (
            workflow_tables_without_fk
            + ";"
            + _ITEMS_DDL
            + ITEM_WORKTREES_TABLE_SQL
            + ITEM_WORKTREES_INDEX_SQL
            + _EPIC_QA_DDL
            + _RUNTIME_DDL
            + _STRATEGY_DDL
            + _AUTH_DDL
            + PACK_CATALOG_TABLE_SQL
            + ";"
            + pack_reports_without_fk
            + ";"
            + pack_entries_without_fk
            + ";"
            + PROJECT_ONBOARDING_RUNS_CREATE_SQL
            + ";"
            + onboarding_rows_without_fk
            + ";"
            + ui_preferences_without_fk
            + ";"
            + OVERVIEW_ACTIVATION_FACTS_CREATE_SQL
            + ";"
            + _MERGE_LOCKS_DDL
        )
        globals()["SCHEMA_DDL"] = composed
    return composed


def __getattr__(name: str) -> str:
    if name == "SCHEMA_DDL":
        return _schema_ddl()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def apply_fixture_ddl(conn: Any, ddl: str) -> None:
    """Apply fixture DDL to *conn* one native statement at a time."""
    from yoke_core.domain.schema_init_apply import execute_schema_script

    execute_schema_script(conn, ddl)
    conn.commit()


def apply_fixture_schema(conn: Any) -> None:
    """Apply the composed fixture schema to *conn*."""
    apply_fixture_ddl(conn, _schema_ddl())
    from yoke_core.domain.workflow_registry import converge_builtin_workflows
    from yoke_core.domain.workflow_schema import ensure_workflow_schema

    ensure_workflow_schema(conn)
    converge_builtin_workflows(conn)


__all__ = ("SCHEMA_DDL", "apply_fixture_ddl", "apply_fixture_schema")  # noqa: F822
