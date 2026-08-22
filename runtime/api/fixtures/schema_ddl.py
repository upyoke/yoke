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

import re
from typing import Any

from runtime.api.fixtures.schema_ddl_auth import _AUTH_DDL
from runtime.api.fixtures.schema_ddl_epic_qa import _EPIC_QA_DDL
from runtime.api.fixtures.schema_ddl_merge_locks import _MERGE_LOCKS_DDL
from runtime.api.fixtures.schema_ddl_momentum_feeds import _MOMENTUM_FEEDS_DDL
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
        from yoke_core.domain.qa_catalog_schema import QA_CATALOG_TABLES_SQL
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
        item_worktrees_without_fk = ITEM_WORKTREES_TABLE_SQL.replace(
            " REFERENCES items(id) ON DELETE CASCADE",
            "",
        )
        qa_catalog_without_fk = re.sub(
            r" REFERENCES [A-Za-z_][A-Za-z0-9_]*\([^)]*\)"
            r"(?: ON DELETE CASCADE)?",
            "",
            QA_CATALOG_TABLES_SQL,
        )
        composed = (
            workflow_tables_without_fk
            + ";"
            + _ITEMS_DDL
            + item_worktrees_without_fk
            + ITEM_WORKTREES_INDEX_SQL
            + _EPIC_QA_DDL
            + _RUNTIME_DDL
            + _MOMENTUM_FEEDS_DDL
            + qa_catalog_without_fk
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
    from yoke_core.domain.session_control_schema import (
        create_session_control_tables,
    )

    create_session_control_tables(conn)
    from yoke_core.domain.workflow_registry import converge_builtin_workflows
    from yoke_core.domain.workflow_schema import ensure_workflow_schema
    from yoke_core.domain.decision_request_schema import (
        create_decision_request_tables,
    )
    from yoke_core.domain.qa_catalog_schema import (
        create_qa_catalog_tables,
        seed_builtin_qa_methods,
    )
    from yoke_core.domain.project_structure import create_project_structure_tables
    from yoke_core.domain.strategy_docs_schema import (
        STRATEGY_DOC_REVISIONS_CREATE_TABLE_SQL,
    )
    from yoke_core.domain.strategy_execution_schema import (
        ensure_strategy_execution_schema,
    )
    from yoke_core.domain.machine_verification_schema import ensure_test_machine_schema
    from yoke_core.domain.field_note_dash_promotion import (
        ensure_field_note_dash_promotion_schema,
    )
    from yoke_core.domain.schema_ouroboros_columns import (
        apply_ouroboros_columns,
    )
    from yoke_core.domain.machine_qa_pack import sync_machine_qa_pack_methods
    from yoke_core.domain.workflow_execution_instructions_schema import (
        ensure_workflow_execution_instructions_schema,
    )
    from yoke_core.domain.migration_yoke_ledger import (
        YOKE_LEDGER_CONTRACT,
        ensure_yoke_migration_ledger,
    )

    # The fixture schema is hand-composed and never runs converge_core_schema,
    # so the migration ledger has to be named here explicitly. Without it, any
    # code that asks a fixture database whether it is current — the health
    # predicate in particular — hits a missing table rather than an answer.
    # Stamp the ordered history as birth: the composed fixture already matches
    # current schema code, so pending apply on a later schema.cmd_init would
    # re-run entries against a database that never owed them.
    ensure_yoke_migration_ledger(conn)
    from yoke_core.domain import migrations as migration_history_package
    from yoke_core.domain.migration_boot_apply import stamp_history
    from yoke_core.domain.migration_history import history_dir, ordered_entries

    stamp_history(
        conn,
        ordered_entries(history_dir(migration_history_package)),
        ledger=YOKE_LEDGER_CONTRACT,
        applied_by="fixture-birth",
    )
    ensure_workflow_schema(conn)
    converge_builtin_workflows(conn)
    create_project_structure_tables(conn)
    create_qa_catalog_tables(conn)
    seed_builtin_qa_methods(conn)
    ensure_workflow_execution_instructions_schema(conn, commit=False)
    ensure_test_machine_schema(conn)
    ensure_field_note_dash_promotion_schema(conn)
    apply_ouroboros_columns(conn)
    sync_machine_qa_pack_methods(conn)
    create_decision_request_tables(conn)
    conn.execute(
        STRATEGY_DOC_REVISIONS_CREATE_TABLE_SQL.replace(" REFERENCES projects(id)", "")
    )
    ensure_strategy_execution_schema(conn)


__all__ = ("SCHEMA_DDL", "apply_fixture_ddl", "apply_fixture_schema")  # noqa: F822
