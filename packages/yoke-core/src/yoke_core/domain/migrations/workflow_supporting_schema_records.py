"""Propagate additive workflow-supporting records to existing universes."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.decision_request_contract import DECISION_EVENT_ROWS
from yoke_core.domain.decision_request_schema import create_decision_request_tables
from yoke_core.domain.machine_qa_method_contracts import MACHINE_METHODS
from yoke_core.domain.machine_qa_pack import (
    MACHINE_QA_PACK,
    sync_machine_qa_pack_methods,
)
from yoke_core.domain.qa_catalog_schema import (
    BUILTIN_QA_METHODS,
    create_qa_catalog_tables,
)
from yoke_core.domain.schema_common import (
    _column_exists,
    _index_exists,
    _table_exists,
)
from yoke_core.domain.strategy_execution_events import (
    STRATEGY_EXECUTION_EVENT_ROWS,
)
from yoke_core.domain.strategy_execution_schema import (
    ensure_strategy_execution_schema,
)
from yoke_core.domain.test_machine_schema import ensure_test_machine_schema


MIGRATION_NAME = "workflow_supporting_schema_records"

_REQUIRED_TABLES = (
    "actors",
    "event_registry",
    "events",
    "items",
    "organizations",
    "projects",
    "qa_requirements",
    "qa_runs",
    "strategy_doc_revisions",
    "strategy_docs",
    "workflows",
)

_TARGET_TABLES = (
    "addressed_event_deliveries",
    "decision_request_actor_authorities",
    "decision_request_role_authorities",
    "decision_requests",
    "item_strategy_docs",
    "qa_methods",
    "qa_plan_cases",
    "qa_plan_item_attachments",
    "qa_plan_project_defaults",
    "qa_plans",
    "strategy_doc_claims",
    "test_machine_verifications",
)

_TARGET_COLUMNS = (
    ("qa_requirements", "expected_outcome"),
    ("qa_requirements", "host_baseline"),
    ("qa_requirements", "instructions"),
    ("qa_requirements", "method_config"),
    ("qa_requirements", "method_id"),
    ("qa_requirements", "plan_case_key"),
    ("qa_requirements", "plan_id"),
    ("qa_requirements", "workflow_transition_id"),
    ("qa_runs", "capture_degraded_reason"),
    ("qa_runs", "case_outcome"),
    ("strategy_doc_revisions", "session_id"),
    ("strategy_docs", "parent_slug"),
)

_TARGET_INDEXES = (
    ("addressed_event_deliveries", "idx_addressed_events_actor_unread"),
    ("decision_request_actor_authorities", "idx_decision_request_actors_actor"),
    ("decision_request_role_authorities", "idx_decision_request_roles_scope"),
    ("decision_requests", "idx_decision_requests_org_status"),
    ("decision_requests", "idx_decision_requests_project_status"),
    ("decision_requests", "uq_decision_requests_open_subject"),
    ("item_strategy_docs", "idx_item_strategy_docs_document"),
    ("qa_plan_cases", "idx_qa_plan_cases_plan"),
    ("qa_plan_item_attachments", "idx_qa_item_attachments_plan"),
    ("qa_plan_project_defaults", "idx_qa_project_defaults_plan"),
    ("qa_plans", "idx_qa_plans_project"),
    ("qa_requirements", "idx_qa_requirement_materialization"),
    ("strategy_doc_claims", "idx_strategy_doc_claims_item_history"),
    ("strategy_doc_claims", "uq_strategy_doc_claims_active_document"),
    ("strategy_doc_claims", "uq_strategy_doc_claims_active_item"),
    ("strategy_docs", "idx_strategy_docs_parent"),
)


def apply(conn: Any) -> None:
    """Create supporting records through their code-owned schema functions."""
    missing = [table for table in _REQUIRED_TABLES if not _table_exists(conn, table)]
    if missing:
        raise RuntimeError(
            "workflow-supporting schema requires deployed base tables: "
            + ", ".join(missing)
        )

    ensure_strategy_execution_schema(conn, commit=False)
    create_decision_request_tables(conn, commit=False)
    create_qa_catalog_tables(conn, commit=False)
    ensure_test_machine_schema(conn, commit=False)
    sync_machine_qa_pack_methods(conn, commit=False)


def invariants(conn: Any) -> None:
    """Require the complete additive shape and its code-owned seed rows."""
    missing_tables = [
        table for table in _TARGET_TABLES if not _table_exists(conn, table)
    ]
    if missing_tables:
        raise AssertionError(
            "workflow-supporting tables are missing: " + ", ".join(missing_tables)
        )

    missing_columns = [
        f"{table}.{column}"
        for table, column in _TARGET_COLUMNS
        if not _column_exists(conn, table, column)
    ]
    if missing_columns:
        raise AssertionError(
            "workflow-supporting columns are missing: " + ", ".join(missing_columns)
        )

    missing_indexes = [
        index
        for table, index in _TARGET_INDEXES
        if not _index_exists(conn, index, table)
    ]
    if missing_indexes:
        raise AssertionError(
            "workflow-supporting indexes are missing: " + ", ".join(missing_indexes)
        )

    expected_methods = {str(method["id"]) for method in BUILTIN_QA_METHODS}
    actual_methods = {
        str(row[0])
        for row in conn.execute(
            "SELECT id FROM qa_methods WHERE source_kind='built_in'"
        ).fetchall()
    }
    if missing_methods := sorted(expected_methods - actual_methods):
        raise AssertionError(
            "built-in QA methods are missing: " + ", ".join(missing_methods)
        )

    machine_method_owners = {
        str(row[0]): (str(row[1]), str(row[2] or ""))
        for row in conn.execute(
            "SELECT id,source_kind,source_ref FROM qa_methods"
        ).fetchall()
        if str(row[0]) in MACHINE_METHODS
    }
    invalid_machine_methods = sorted(
        method_id
        for method_id in MACHINE_METHODS
        if machine_method_owners.get(method_id) != ("pack", MACHINE_QA_PACK)
    )
    if invalid_machine_methods:
        raise AssertionError(
            "Machine QA Pack methods are missing or have invalid ownership: "
            + ", ".join(invalid_machine_methods)
        )

    expected_events = {
        str(row[0]) for row in (*DECISION_EVENT_ROWS, *STRATEGY_EXECUTION_EVENT_ROWS)
    }
    actual_events = {
        str(row[0])
        for row in conn.execute("SELECT event_name FROM event_registry").fetchall()
    }
    if missing_events := sorted(expected_events - actual_events):
        raise AssertionError(
            "workflow-supporting events are missing: " + ", ".join(missing_events)
        )


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
