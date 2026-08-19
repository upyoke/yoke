"""Refusal text for an item whose delivery flow never resolved.

The run is attempted long after the filing that left the flow unset, so
the sentence has to carry the way out of it: the flows this project can
still deploy through, the fact that it has none yet, or that the project
named does not exist at all.
"""

from __future__ import annotations

from unittest import mock

from yoke_core.domain.deployment_item_flow_resolution import (
    NO_FLOW_HEAD,
    describe_missing_flow,
)


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
        message = describe_missing_flow(42, "yoke")
    assert message.startswith(f"item 42 {NO_FLOW_HEAD}")
    assert "'yoke' declares no delivery default" in message
    assert "--flow with one of: to-prod, to-stage" in message
    conn.close.assert_called_once()


def test_refusal_reads_only_the_projects_active_flows():
    conn, connect, project = _patches(["to-prod"])
    with connect, project:
        describe_missing_flow(42, "yoke")
    sql, params = conn.execute.call_args.args
    assert "FROM deployment_flows" in sql
    assert params == (7, "active")


def test_refusal_without_active_flows_asks_for_a_declaration():
    _conn, connect, project = _patches([])
    with connect, project:
        message = describe_missing_flow(42, "yoke")
    assert "no active deployment flow to select" in message
    assert "Declare a flow for the project" in message
    # An empty roster makes --flow a dead end, so it is not offered alone.
    assert "--flow with one of" not in message


def test_refusal_for_an_unknown_project_does_not_send_the_operator_to_declare():
    _conn, connect, project = _patches([], project_found=False)
    with connect, project:
        message = describe_missing_flow(42, "ghost")
    assert message == f"item 42 {NO_FLOW_HEAD}: project 'ghost' does not exist."


def test_refusal_survives_an_unresolvable_project():
    conn, connect, project = _patches(
        [], resolve_raises=LookupError("slug names more than one project"),
    )
    with connect, project:
        message = describe_missing_flow(42, "yoke")
    assert message == f"item 42 {NO_FLOW_HEAD}"
    conn.close.assert_called_once()
