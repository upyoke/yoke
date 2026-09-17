"""Selected-flow completion authority for delivery-evidence facts."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.deployment_qa_source_obligation import latest_completion_run
from yoke_core.domain.gate_satisfier_facts import FactVerdict
from yoke_core.domain.gate_satisfier_item_facts import (
    ITEM_DEPLOYMENT_RUN_SUCCEEDED,
    load_item_facts,
)


def _apply_deploy_schema() -> None:
    from yoke_core.domain import deployment_runs_schema, schema
    from yoke_core.domain.db_helpers import connect
    from yoke_core.domain.project_seed_test_helpers import seed_project_identities

    schema.cmd_init()
    conn = connect()
    try:
        seed_project_identities(conn)
    finally:
        conn.close()
    deployment_runs_schema.cmd_init()


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path, _apply_deploy_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def test_delivery_evidence_ignores_succeeded_runs_on_another_flow(db):
    item_id = 8610
    conn = connect_test_db(db)
    try:
        insert_item(
            conn, id=item_id, source=str(seed_human_actor(conn)),
            deployment_flow="prod-flow",
        )
        insert_deployment_run(
            conn, id="run-stage", flow="stage-flow", status="succeeded",
        )
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES (%s, %s, %s)",
            ("run-stage", item_id, "2026-01-01T00:00:00Z"),
        )
        conn.commit()
        facts = load_item_facts(conn, item_id)
    finally:
        conn.close()
    assert facts[ITEM_DEPLOYMENT_RUN_SUCCEEDED].verdict is FactVerdict.ABSENT


def test_latest_completion_run_is_the_selected_flow_even_when_older(db):
    item_id = 8611
    conn = connect_test_db(db)
    try:
        insert_item(
            conn, id=item_id, source=str(seed_human_actor(conn)),
            deployment_flow="prod-flow",
        )
        insert_deployment_run(
            conn, id="run-prod", flow="prod-flow", status="executing",
            created_at="2026-01-01T00:00:00Z",
        )
        insert_deployment_run(
            conn, id="run-stage", flow="stage-flow", status="succeeded",
            created_at="2026-02-01T00:00:00Z",
        )
        for run_id in ("run-prod", "run-stage"):
            conn.execute(
                "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
                "VALUES (%s, %s, %s)",
                (run_id, item_id, "2026-01-01T00:00:00Z"),
            )
        conn.commit()
        row = latest_completion_run(conn, item_id)
    finally:
        conn.close()
    assert row is not None
    assert row["id"] == "run-prod"
    assert row["flow"] == "prod-flow"
