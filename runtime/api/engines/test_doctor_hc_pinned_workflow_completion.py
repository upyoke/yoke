"""Doctor completion checks use immutable workflow-version semantics."""

from __future__ import annotations

import pytest

from runtime.api.workflow_version_test_helpers import (
    publish_issue_completion_stage,
)
from runtime.api.engines._doctor_hc_meta_full_test_helpers import (
    _insert_deployment_flow,
    _insert_item,
    _make_conn,
    _result,
    _run_hc,
)
from yoke_core.engines.doctor import (
    hc_deferred_items,
    hc_orphaned_done_items,
    hc_undeployed_done,
)


@pytest.fixture()
def conn():
    connection = _make_conn()
    try:
        yield connection
    finally:
        connection.close()


def test_undeployed_check_uses_pinned_terminal_stage(conn):
    publish_issue_completion_stage(conn)
    _insert_deployment_flow(conn, "release-flow")
    _insert_item(
        conn,
        1,
        "Terminal undeployed item",
        workflow_id="issue",
        status="archived",
        created_at="2025-01-01T00:00:00Z",
        updated_at="2025-01-01T00:00:00Z",
    )

    result = _result(_run_hc(hc_undeployed_done, conn))
    assert result.result == "WARN"
    assert "YOK-1" in result.detail


def test_orphaned_lane_check_uses_pinned_terminal_stage(conn):
    publish_issue_completion_stage(conn)
    _insert_item(
        conn,
        2,
        "Terminal item with lane",
        workflow_id="issue",
        status="archived",
    )
    conn.execute(
        "INSERT INTO item_worktrees "
        "(id, item_id, branch, path, lane_role, state, created_at, updated_at) "
        "VALUES (2, 2, 'item-2', '/tmp/item-2', 'implementation', 'active', "
        "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )

    result = _result(_run_hc(hc_orphaned_done_items, conn))
    assert result.result == "WARN"
    assert "YOK-2" in result.detail


def test_deferred_check_uses_task_graph_policy(conn):
    publish_issue_completion_stage(
        conn,
        generated_children="epic_tasks",
    )
    _insert_item(
        conn,
        3,
        "Terminal task graph",
        workflow_id="issue",
        status="archived",
        spec="This was deferred to a follow-up item.",
    )

    result = _result(_run_hc(hc_deferred_items, conn))
    assert result.result == "WARN"
    assert "YOK-3" in result.detail
