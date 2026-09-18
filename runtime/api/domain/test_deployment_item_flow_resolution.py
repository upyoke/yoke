"""Refusal text for an item whose delivery flow never resolved.

The run is attempted long after the filing that left the flow unset, so
the sentence has to carry the way out of it: the flows this project can
still deploy through, the fact that it has none yet, or that the project
named does not exist at all.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.deployment_item_flow_resolution import (
    NO_FLOW_HEAD,
    describe_missing_flow,
    freeze_item_completion_flow,
    item_completion_flow,
)
from yoke_core.domain.deployment_run_carried_membership import admit_run_item
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.workflow_project_defaults import set_delivery_default


def _patches(flow_ids, *, project_found=True, resolve_raises=None):
    """Patch the connection and project lookup the refusal text reads."""
    conn = mock.MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        (flow_id,) for flow_id in flow_ids
    ]
    return conn, mock.patch(
        "yoke_core.domain.db_helpers.connect", return_value=conn,
    ), mock.patch(
        "yoke_core.domain.deployment_item_flow_resolution.resolve_project",
        side_effect=resolve_raises,
        return_value=mock.MagicMock(id=7) if project_found else None,
    )


def test_refusal_names_the_projects_selectable_flows():
    conn, connect, project = _patches(["to-prod", "to-stage"])
    with connect, project:
        message = describe_missing_flow("YOK-42", "yoke")
    assert message.startswith(f"YOK-42 {NO_FLOW_HEAD}")
    assert "'yoke' declares no delivery default" in message
    assert "--flow with one of: to-prod, to-stage" in message
    conn.close.assert_called_once()


def test_refusal_reads_only_the_projects_active_flows():
    conn, connect, project = _patches(["to-prod"])
    with connect, project:
        describe_missing_flow("YOK-42", "yoke")
    sql, params = conn.execute.call_args.args
    assert "FROM deployment_flows" in sql
    assert params == (7, "active")


def test_refusal_without_active_flows_asks_for_a_declaration():
    _conn, connect, project = _patches([])
    with connect, project:
        message = describe_missing_flow("YOK-42", "yoke")
    assert "no active deployment flow to select" in message
    assert "Declare a flow for the project" in message
    # An empty roster makes --flow a dead end, so it is not offered alone.
    assert "--flow with one of" not in message


def test_refusal_for_an_unknown_project_does_not_send_the_operator_to_declare():
    _conn, connect, project = _patches([], project_found=False)
    with connect, project:
        message = describe_missing_flow("YOK-42", "ghost")
    assert message == f"YOK-42 {NO_FLOW_HEAD}: project 'ghost' does not exist."


def test_refusal_survives_an_unresolvable_project():
    conn, connect, project = _patches(
        [], resolve_raises=LookupError("slug names more than one project"),
    )
    with connect, project:
        message = describe_missing_flow("YOK-42", "yoke")
    assert message == f"YOK-42 {NO_FLOW_HEAD}"
    conn.close.assert_called_once()


def _active_flow(conn: Any, flow_id: str) -> None:
    cmd_create(
        conn,
        flow_id,
        "yoke",
        flow_id,
        "",
        json.dumps([{"name": "deploy", "step_runner": "auto"}]),
        status="active",
    )


def _unpinned_item(conn: Any, item_id: int) -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="blitz",
        status="implementing",
    )


def _pinned_flow(conn: Any, item_id: int) -> str:
    row = conn.execute(
        "SELECT COALESCE(deployment_flow, '') FROM items WHERE id = %s",
        (item_id,),
    ).fetchone()
    return str(row[0] if row is not None else "")


def test_freeze_pins_the_live_default_so_a_later_default_cannot_retarget(
    test_db: Any,
) -> None:
    _active_flow(test_db, "completion-alpha")
    _active_flow(test_db, "completion-beta")
    _unpinned_item(test_db, 9331)
    set_delivery_default(
        test_db, project="yoke", workflow_id="blitz", flow_id="completion-alpha",
    )
    assert item_completion_flow(test_db, 9331) == "completion-alpha"
    assert _pinned_flow(test_db, 9331) == ""

    assert freeze_item_completion_flow(test_db, 9331) == "completion-alpha"
    assert _pinned_flow(test_db, 9331) == "completion-alpha"

    set_delivery_default(
        test_db, project="yoke", workflow_id="blitz", flow_id="completion-beta",
    )
    assert item_completion_flow(test_db, 9331) == "completion-alpha"


def test_freeze_keeps_an_explicit_pin_when_the_project_default_moves(
    test_db: Any,
) -> None:
    _active_flow(test_db, "completion-pinned")
    _active_flow(test_db, "completion-moved")
    insert_item(
        test_db,
        id=9332,
        project_sequence=9332,
        workflow_id="blitz",
        status="implementing",
        deployment_flow="completion-pinned",
    )
    set_delivery_default(
        test_db, project="yoke", workflow_id="blitz", flow_id="completion-moved",
    )
    assert freeze_item_completion_flow(test_db, 9332) == "completion-pinned"
    assert _pinned_flow(test_db, 9332) == "completion-pinned"
    assert item_completion_flow(test_db, 9332) == "completion-pinned"


def test_admit_run_item_freezes_the_completion_flow_before_membership(
    test_db: Any,
) -> None:
    _active_flow(test_db, "completion-admit")
    _active_flow(test_db, "completion-later")
    _unpinned_item(test_db, 9333)
    set_delivery_default(
        test_db, project="yoke", workflow_id="blitz", flow_id="completion-admit",
    )
    test_db.execute(
        "INSERT INTO deployment_runs("
        "id, project_id, flow, release_lineage, status, created_at) "
        "VALUES ('run-completion-admit', 1, 'completion-admit', 'main', "
        "'created', '2026-09-17T00:00:00Z')"
    )
    test_db.commit()

    admit_run_item(test_db, run_id="run-completion-admit", item_id=9333)
    test_db.commit()

    assert _pinned_flow(test_db, 9333) == "completion-admit"
    set_delivery_default(
        test_db, project="yoke", workflow_id="blitz", flow_id="completion-later",
    )
    assert item_completion_flow(test_db, 9333) == "completion-admit"
