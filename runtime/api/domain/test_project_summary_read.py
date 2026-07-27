"""Authoritative aggregate facts for the Projects roster."""

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.projects_get import handle_projects_list

from runtime.api.fixtures.backlog import insert_item


def test_project_summary_counts_active_work_and_distinct_blocked_items(test_db):
    insert_item(
        test_db,
        id=601,
        title="Implementation in flight",
        type="issue",
        status="implementing",
    )
    insert_item(
        test_db,
        id=602,
        title="Review in flight",
        type="issue",
        status="reviewing-implementation",
    )
    insert_item(
        test_db,
        id=603,
        title="Terminal work",
        type="issue",
        status="done",
    )
    insert_item(
        test_db,
        id=604,
        title="Operator hold",
        type="issue",
        status="refined-idea",
        blocked=1,
        blocked_reason="waiting on a decision",
    )

    outcome = handle_projects_list(
        FunctionCallRequest(
            function="projects.list",
            actor=ActorContext(actor_id=None, session_id=""),
            target=TargetRef(kind="global"),
            payload={"include_summary": True},
        ),
    )

    assert outcome.primary_success
    row = next(row for row in outcome.result_payload["rows"] if row["slug"] == "yoke")
    assert row["in_flight_count"] == 2
    assert row["ready_count"] >= 2
    assert row["blocked_count"] == 1
    assert row["has_strategy"] is (row["strategy_doc_count"] > 0)
