"""Materialized plan cases land with their creation events, or not at all."""

from __future__ import annotations

from runtime.api.domain.test_qa_plan_execution_authority import (
    _materialize_two_cases,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.db_helpers import query_rows, query_scalar


def _event_requirement_ids(conn) -> set[int]:
    """The requirement ids QARequirementCreated events actually name."""
    rows = query_rows(
        conn,
        "SELECT (envelope::jsonb -> 'context' -> 'detail' ->> 'requirement_id')"
        "::bigint AS requirement_id FROM events "
        "WHERE event_name = 'QARequirementCreated'",
    )
    return {
        int(row["requirement_id"])
        for row in rows
        if row["requirement_id"] is not None
    }


def test_flow_derived_materialization_emits_one_event_per_requirement() -> None:
    with test_database() as conn:
        requirement_ids = _materialize_two_cases(conn, item_id=4430)
        sources = {
            str(row["requirement_source"])
            for row in query_rows(
                conn,
                "SELECT requirement_source FROM qa_requirements WHERE item_id=4430",
            )
        }

        assert sources == {"flow_derived"}
        assert _event_requirement_ids(conn) == set(requirement_ids)


def test_uncommitted_materialization_leaves_neither_row_nor_event() -> None:
    """The event rides the caller's transaction, so a rollback loses both."""
    with test_database() as conn:
        _materialize_two_cases(conn, item_id=4431, commit=False)

        assert _event_requirement_ids(conn)
        conn.rollback()

        assert not _event_requirement_ids(conn)
        assert (
            int(
                query_scalar(
                    conn,
                    "SELECT COUNT(*) FROM qa_requirements WHERE item_id=4431",
                )
                or 0
            )
            == 0
        )
