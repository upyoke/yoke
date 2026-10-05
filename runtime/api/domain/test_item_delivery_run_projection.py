"""The item card reads completion authority and terminal timestamps together."""

import json

import pytest

from runtime.api.domain.test_selected_flow_completion_facts import db as _delivery_db
from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers.deployment_inspection import (
    handle_deployment_runs_find_by_item,
)
from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS


@pytest.fixture
def db(tmp_path, monkeypatch):
    yield from _delivery_db.__wrapped__(tmp_path, monkeypatch)


@pytest.mark.parametrize("status", ["succeeded", "executing"])
def test_card_completion_matches_cross_project_delivery_despite_cancelled_duplicate(
    db, status
):
    item_id = 8701
    conn = connect_test_db(db)
    consumer = SEED_PROJECT_IDS["externalwebapp"]
    try:
        insert_item(
            conn,
            id=item_id,
            source=str(seed_human_actor(conn)),
            project_id=consumer,
            deployment_flow="consumer-prod",
        )
        insert_deployment_run(
            conn,
            id="carrier",
            flow="shared-release",
            status=status,
            created_at="2026-01-01T00:00:00Z",
            started_at="2026-01-01T00:05:00Z",
            completed_at="2026-01-01T01:00:00Z" if status == "succeeded" else None,
            bound_sources=json.dumps(
                {
                    "schema": 1,
                    "projects": [
                        {"project_id": consumer, "commit_sha": "a" * 40},
                    ],
                    "inputs": {},
                }
            ),
        )
        insert_deployment_run(
            conn,
            id="duplicate",
            flow="consumer-prod",
            project_id=consumer,
            status="cancelled",
            created_at="2026-02-01T00:00:00Z",
        )
        for run_id in ("carrier", "duplicate"):
            conn.execute(
                "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
                "VALUES (%s,%s,%s)",
                (run_id, item_id, "2026-02-01T00:00:00Z"),
            )
        conn.commit()
    finally:
        conn.close()
    request = FunctionCallRequest.model_validate(
        {
            "function": "deployment_runs.find_by_item",
            "request_id": "card-read",
            "actor": {"session_id": "card-test"},
            "target": {"kind": "item", "item_id": item_id},
            "payload": {},
        }
    )
    result = handle_deployment_runs_find_by_item(request).result_payload
    assert result["completion_run"]["id"] == "carrier"
    assert result["completion_run"]["status"] == status
    assert [row["id"] for row in result["rows"]] == ["duplicate", "carrier"]
    row = result["rows"][1]
    assert row["started_at"] == "2026-01-01T00:05:00Z"
    assert row["completed_at"] == (
        "2026-01-01T01:00:00Z" if status == "succeeded" else ""
    )
