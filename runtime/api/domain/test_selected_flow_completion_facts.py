"""Selected-flow completion authority for delivery-evidence facts."""

from __future__ import annotations

import json
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


def _carry(conn, item_id, *run_ids):
    for run_id in run_ids:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES (%s, %s, %s)",
            (run_id, item_id, "2026-01-01T00:00:00Z"),
        )
    conn.commit()


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
        _carry(conn, item_id, "run-prod", "run-stage")
        row = latest_completion_run(conn, item_id)
        facts = load_item_facts(conn, item_id)
    finally:
        conn.close()
    assert row is not None
    assert row["id"] == "run-prod"
    assert row["flow"] == "prod-flow"
    assert facts[ITEM_DEPLOYMENT_RUN_SUCCEEDED].verdict is FactVerdict.ABSENT


def test_later_ancillary_failure_does_not_erase_selected_flow_success(db):
    item_id = 8612
    conn = connect_test_db(db)
    try:
        insert_item(
            conn, id=item_id, source=str(seed_human_actor(conn)),
            deployment_flow="prod-flow",
        )
        insert_deployment_run(
            conn, id="run-prod-ok", flow="prod-flow", status="succeeded",
            created_at="2026-01-01T00:00:00Z",
        )
        insert_deployment_run(
            conn, id="run-stage-fail", flow="stage-flow", status="failed",
            created_at="2026-02-01T00:00:00Z",
        )
        _carry(conn, item_id, "run-prod-ok", "run-stage-fail")
        row = latest_completion_run(conn, item_id)
        facts = load_item_facts(conn, item_id)
    finally:
        conn.close()
    assert row is not None
    assert row["id"] == "run-prod-ok"
    assert row["status"] == "succeeded"
    assert facts[ITEM_DEPLOYMENT_RUN_SUCCEEDED].verdict is FactVerdict.PRESENT


def test_combined_selected_flow_is_not_complete_until_the_run_succeeds(db):
    item_id = 8613
    conn = connect_test_db(db)
    try:
        insert_item(
            conn, id=item_id, source=str(seed_human_actor(conn)),
            deployment_flow="stage-then-prod",
        )
        insert_deployment_run(
            conn, id="run-combined", flow="stage-then-prod",
            status="executing", current_stage="prod-qa",
        )
        _carry(conn, item_id, "run-combined")
        mid = load_item_facts(conn, item_id)
        conn.execute(
            "UPDATE deployment_runs SET status='succeeded', "
            "current_stage='complete' WHERE id=%s",
            ("run-combined",),
        )
        conn.commit()
        done = load_item_facts(conn, item_id)
        row = latest_completion_run(conn, item_id)
    finally:
        conn.close()
    assert mid[ITEM_DEPLOYMENT_RUN_SUCCEEDED].verdict is FactVerdict.ABSENT
    assert done[ITEM_DEPLOYMENT_RUN_SUCCEEDED].verdict is FactVerdict.PRESENT
    assert row is not None
    assert row["id"] == "run-combined"
    assert row["status"] == "succeeded"


def _carrier_fact(db, item_id, *, status, bound_project_id):
    """The delivery fact for an item another project's run carried."""
    from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS

    item_project = SEED_PROJECT_IDS["externalwebapp"]
    bound = (
        [{"project_id": bound_project_id, "commit_sha": "c" * 40}]
        if bound_project_id is not None
        else []
    )
    conn = connect_test_db(db)
    try:
        insert_item(
            conn, id=item_id, source=str(seed_human_actor(conn)),
            project_id=item_project, deployment_flow="consumer-analysis",
        )
        insert_deployment_run(
            conn, id=f"run-carrier-{item_id}", flow="carrier-release",
            status=status, release_lineage="a" * 40,
            bound_sources=json.dumps(
                {"schema": 1, "projects": bound, "inputs": {}}
            ),
        )
        _carry(conn, item_id, f"run-carrier-{item_id}")
        return load_item_facts(conn, item_id)[ITEM_DEPLOYMENT_RUN_SUCCEEDED]
    finally:
        conn.close()


def test_cross_project_carrier_with_a_bound_source_delivers_the_item(db):
    from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS

    fact = _carrier_fact(
        db, 8620, status="succeeded",
        bound_project_id=SEED_PROJECT_IDS["externalwebapp"],
    )
    assert fact.verdict is FactVerdict.PRESENT


def test_carried_code_without_a_bound_source_is_not_completion_authority(db):
    fact = _carrier_fact(db, 8621, status="succeeded", bound_project_id=None)
    assert fact.verdict is FactVerdict.ABSENT


def test_a_failed_cross_project_carrier_delivers_nothing(db):
    from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS

    fact = _carrier_fact(
        db, 8622, status="failed",
        bound_project_id=SEED_PROJECT_IDS["externalwebapp"],
    )
    assert fact.verdict is FactVerdict.ABSENT


def test_a_later_cancelled_duplicate_does_not_shadow_the_delivering_run(db):
    item_id = 8630
    conn = connect_test_db(db)
    try:
        insert_item(
            conn, id=item_id, source=str(seed_human_actor(conn)),
            deployment_flow="prod-flow",
        )
        insert_deployment_run(
            conn, id="run-delivered", flow="prod-flow", status="succeeded",
            created_at="2026-01-01T00:00:00Z",
        )
        insert_deployment_run(
            conn, id="run-duplicate", flow="prod-flow", status="cancelled",
            created_at="2026-01-01T00:00:27Z",
        )
        _carry(conn, item_id, "run-delivered", "run-duplicate")
        row = latest_completion_run(conn, item_id)
    finally:
        conn.close()
    assert row is not None and row["id"] == "run-delivered"


def test_a_lone_cancelled_run_is_still_reported_unless_skipped(db):
    item_id = 8631
    conn = connect_test_db(db)
    try:
        insert_item(
            conn, id=item_id, source=str(seed_human_actor(conn)),
            deployment_flow="prod-flow",
        )
        insert_deployment_run(
            conn, id="run-only-cancelled", flow="prod-flow", status="cancelled",
        )
        _carry(conn, item_id, "run-only-cancelled")
        reported = latest_completion_run(conn, item_id)
        skipped = latest_completion_run(conn, item_id, skip_terminal_failures=True)
    finally:
        conn.close()
    assert reported is not None and reported["status"] == "cancelled"
    assert skipped is None
