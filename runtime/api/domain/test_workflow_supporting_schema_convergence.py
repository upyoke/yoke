"""Boot-convergence coverage for additive workflow-supporting authorities."""

from __future__ import annotations

from yoke_core.domain.decision_request_contract import DECISION_EVENT_ROWS
from yoke_core.domain.migration_restore_point import RESTORE_POINT_ENV
from yoke_core.domain.qa_catalog_schema import BUILTIN_QA_METHODS
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.schema_init import converge_core_schema


def _row_count(conn, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_boot_converges_supporting_schema_and_code_owned_seeds(
    test_db, monkeypatch,
) -> None:
    monkeypatch.setenv(RESTORE_POINT_ENV, "workflow-schema-test-snapshot")
    converge_core_schema(test_db)

    for table in (
        "decision_requests",
        "addressed_event_deliveries",
        "ouroboros_entry_dispositions",
        "qa_methods",
        "qa_plans",
        "strategy_doc_revisions",
        "strategy_doc_claims",
        "test_machine_verifications",
    ):
        assert _table_exists(test_db, table), table

    for table, column in (
        ("addressed_event_deliveries", "event_name"),
        ("addressed_event_deliveries", "project_id"),
        ("addressed_event_deliveries", "event_outcome"),
        ("addressed_event_deliveries", "event_actor_id"),
        ("addressed_event_deliveries", "event_actor_label"),
        ("addressed_event_deliveries", "event_envelope"),
        ("qa_requirements", "case_position"),
        ("qa_requirements", "baseline_position"),
        ("qa_requirements", "entry_surface"),
        ("qa_requirements", "required_completion"),
        ("qa_requirements", "method_name"),
        ("qa_requirements", "executor_id"),
        ("qa_requirements", "required_capability_kind"),
        ("qa_requirements", "verdict_path"),
        ("qa_requirements", "workflow_transition_id"),
        ("qa_runs", "case_outcome"),
        ("strategy_docs", "parent_slug"),
        ("strategy_doc_revisions", "session_id"),
    ):
        assert _column_exists(test_db, table, column), f"{table}.{column}"

    expected_methods = {str(row["id"]) for row in BUILTIN_QA_METHODS}
    actual_methods = {
        str(row[0])
        for row in test_db.execute(
            "SELECT id FROM qa_methods WHERE source_kind='built_in'"
        ).fetchall()
    }
    assert expected_methods <= actual_methods

    expected_events = {str(row[0]) for row in DECISION_EVENT_ROWS}
    actual_events = {
        str(row[0])
        for row in test_db.execute("SELECT event_name FROM event_registry").fetchall()
    }
    assert expected_events <= actual_events

    seeded_counts = {
        table: _row_count(test_db, table) for table in ("qa_methods", "event_registry")
    }
    converge_core_schema(test_db)
    assert seeded_counts == {
        table: _row_count(test_db, table) for table in seeded_counts
    }
