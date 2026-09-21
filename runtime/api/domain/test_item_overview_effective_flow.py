"""Overview cards resolve the flow they will ship through, not only a pin."""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import release_delivery_summary as summary_module
from yoke_core.domain import workflow_project_defaults
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.item_overview_read import enrich_item_overview_rows
from yoke_core.domain.workflow_project_defaults import (
    WorkflowProjectDefaultError,
    set_delivery_default,
)

FLOW = "yoke-hosted-production"
PROJECT_ID = 1


def _version_id(conn, item_id: int) -> int:
    row = conn.execute(
        "SELECT workflow_version_id FROM items WHERE id = %s", (item_id,)
    ).fetchone()
    return int(row["workflow_version_id"] if hasattr(row, "keys") else row[0])


def _release_row(conn, item_id: int, *, deployment_flow: str = "") -> dict:
    row = {
        "internal_id": item_id,
        "id": item_id,
        "status": "release",
        "workflow_version_id": _version_id(conn, item_id),
    }
    if deployment_flow:
        row["deployment_flow"] = deployment_flow
    return row


def _active_flow(conn, flow_id: str) -> None:
    cmd_create(
        conn,
        flow_id,
        "yoke",
        flow_id,
        "",
        json.dumps([{"name": "deploy", "step_runner": "auto"}]),
        status="active",
    )


def _landing(conn, item_id: int, merge_sha: str) -> None:
    record_entry(
        conn,
        item_id=item_id,
        branch=f"LANE-{item_id}",
        target="main",
        commit_sha=merge_sha,
        merge_sha=merge_sha,
    )


def test_an_unpinned_item_inherits_the_project_default() -> None:
    with test_database() as conn:
        _active_flow(conn, FLOW)
        insert_item(conn, id=8500, title="unpinned", status="release")
        set_delivery_default(
            conn, project="yoke", workflow_id="issue", flow_id=FLOW,
        )
        conn.commit()
        enriched = enrich_item_overview_rows([_release_row(conn, 8500)])

    assert enriched[0]["completion_flow"] == FLOW
    assert enriched[0]["completion_flow_source"] == "project_default"


def test_a_stored_flow_is_the_items_own() -> None:
    with test_database() as conn:
        _active_flow(conn, FLOW)
        insert_item(
            conn, id=8501, title="pinned", status="release",
            deployment_flow=FLOW,
        )
        set_delivery_default(
            conn, project="yoke", workflow_id="issue", flow_id=FLOW,
        )
        conn.commit()
        enriched = enrich_item_overview_rows([
            _release_row(conn, 8501, deployment_flow=FLOW),
        ])

    assert enriched[0]["completion_flow"] == FLOW
    assert enriched[0]["completion_flow_source"] == "item"


def test_neither_a_pin_nor_a_default_is_none() -> None:
    with test_database() as conn:
        insert_item(conn, id=8502, title="no route", status="release")
        conn.commit()
        enriched = enrich_item_overview_rows([_release_row(conn, 8502)])

    assert enriched[0]["completion_flow"] == ""
    assert enriched[0]["completion_flow_source"] == "none"


def test_delivery_counts_key_off_the_effective_flow(monkeypatch) -> None:
    """Unpinned items count against the default they will ship through."""
    built: list[tuple] = []
    real = summary_module.ReleaseCandidates

    class _Counted(real):
        def __init__(self, conn, *, project_id, environment_id, flow=""):
            built.append((project_id, environment_id, flow))
            super().__init__(
                conn,
                project_id=project_id,
                environment_id=environment_id,
                flow=flow,
            )

    monkeypatch.setattr(summary_module, "ReleaseCandidates", _Counted)
    with test_database() as conn:
        _active_flow(conn, FLOW)
        insert_item(conn, id=8503, title="unpinned landing", status="release")
        set_delivery_default(
            conn, project="yoke", workflow_id="issue", flow_id=FLOW,
        )
        _landing(conn, 8503, "a" * 40)
        conn.commit()
        enrich_item_overview_rows([_release_row(conn, 8503)])

    assert len(built) == 1
    assert built[0][0] == PROJECT_ID
    assert built[0][2] == FLOW


def test_an_unreadable_default_is_named_and_does_not_blank_the_roster(
    monkeypatch,
) -> None:
    def _boom(*_args, **_kwargs):
        raise WorkflowProjectDefaultError("project default could not be read")

    monkeypatch.setattr(workflow_project_defaults, "get_delivery_default", _boom)
    with test_database() as conn:
        _active_flow(conn, FLOW)
        insert_item(conn, id=8504, title="unreadable", status="release")
        insert_item(
            conn, id=8505, title="pinned sibling", status="release",
            deployment_flow=FLOW,
        )
        conn.commit()
        enriched = enrich_item_overview_rows([
            _release_row(conn, 8504),
            _release_row(conn, 8505, deployment_flow=FLOW),
        ])

    by_id = {int(row["internal_id"]): row for row in enriched}
    assert by_id[8504]["completion_flow"] == ""
    assert by_id[8504]["completion_flow_source"] == "unreadable"
    assert by_id[8505]["completion_flow"] == FLOW
    assert by_id[8505]["completion_flow_source"] == "item"
    assert by_id[8505]["public_ref"]
