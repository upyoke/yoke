"""The ``run_onboard`` activation signal and the facts its card is drawn from.

A run row appears with the checklist's first write, so the module once
activated — and printed its execution-ready sentence — over a run blocked at
its first hosting step. These drive the handler against real checklist runs:
only a checklist with nothing open activates, and the reported facts name the
blocker, the next step, and the outcomes the universe can actually show. A
project that deployed is past onboarding whatever its checklist says: its run
is closed as superseded on the row itself, naming the deployment.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_deployment_run

from uuid import uuid4

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.onboard_checklist import (
    BRANCH_LOCAL_CHECKOUT,
    FIRST_ITEM_DONE_ROW_ID,
    ROW_IDS,
    STATUS_BLOCKED,
    STATUS_VERIFIED,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.overview_activation import (
    handle_overview_activation_get,
)
from yoke_core.domain.project_onboarding_run_supersede import (
    SUPERSEDED_BY_KEY,
)
from yoke_core.domain.project_onboarding_runs import get_run, init_run

HOSTING_ROW_ID = "hosting-setup"
SCAFFOLD_ROW_ID = "scaffold-install"
BLOCKER_TEXT = "aws-admin capability row absent"


def _onboard(actor_id=None):
    outcome = handle_overview_activation_get(
        FunctionCallRequest(
            function="overview.activation.get",
            actor=ActorContext(actor_id=actor_id, session_id=""),
            target=TargetRef(kind="global"),
            payload={},
        )
    )
    assert outcome.primary_success, outcome.error
    modules = {module["key"]: module for module in outcome.result_payload["modules"]}
    return modules["run_onboard"]


def _seed_run(conn, run_id, *, row_status=None, blocker=None):
    init_run(
        conn=conn,
        run_id=run_id,
        project_id=1,
        branch=BRANCH_LOCAL_CHECKOUT,
        machine_id=str(uuid4()),
        row_status=row_status,
        blocker=blocker,
    )


def _finished_statuses(**overrides):
    statuses = {
        row_id: STATUS_VERIFIED
        for row_id in ROW_IDS
        if row_id != FIRST_ITEM_DONE_ROW_ID
    }
    statuses.update(overrides)
    return statuses


def _seed_environments(conn, *names):
    now = iso8601_now()
    conn.execute(
        "INSERT INTO sites (id, project_id, name, created_at) VALUES (5, 1, 'app', %s)",
        (now,),
    )
    for index, name in enumerate(names):
        conn.execute(
            "INSERT INTO environments (id, site, project_id, name, created_at) "
            "VALUES (%s, 5, 1, %s, %s)",
            (50 + index, name, now),
        )
    conn.commit()


def test_saved_completion_does_not_activate_current_readiness(test_db):
    _seed_run(test_db, "saved-done", row_status=_finished_statuses())
    module = _onboard()
    assert module["state"] != "activated"
    assert module["onboard"]["setup_readiness"]["ready"] is False
    assert module["onboard"]["next"] == {"step": "1", "title": "Package install"}
    assert module["onboard"]["scaffold_installed"] is False


def test_overview_uses_the_same_refreshed_rows_as_checklist(test_db):
    _seed_run(test_db, "saved-choice", row_status=_finished_statuses())
    current = get_run("saved-choice", conn=test_db)
    overview = _onboard()["onboard"]
    assert overview["setup_readiness"] == current["setup_readiness"]
    assert overview["steps_total"] == len(current["rows"])
    assert overview["steps_done"] < overview["steps_total"]


def test_registered_environments_are_reported_without_claiming_readiness(test_db):
    _seed_environments(test_db, "prod", "stage")
    _seed_run(test_db, "saved-envs", row_status=_finished_statuses())
    onboard = _onboard()["onboard"]
    assert onboard["environments"] == ["development", "prod", "stage"]
    assert onboard["setup_readiness"]["ready"] is False


def test_a_universe_with_no_onboarding_run_reports_no_facts(test_db):
    module = _onboard()
    assert module["state"] != "activated"
    assert module["onboard"] is None


def _seed_deployment(conn, run_id, *, status, at):
    insert_deployment_run(
        conn,
        id=run_id,
        project_id=1,
        flow="flow-x",
        status=status,
        created_at=at,
        completed_at=at,
    )
    conn.commit()


def test_delivery_supersession_is_history_not_current_machine_readiness(test_db):
    _seed_run(test_db, "saved-stalled", row_status={HOSTING_ROW_ID: STATUS_BLOCKED})
    _seed_deployment(
        test_db, "run-20260101-001", status="succeeded", at="2026-01-01T00:00:00Z"
    )
    onboard = _onboard()["onboard"]
    assert onboard["run_status"] == "superseded"
    assert onboard["setup_readiness"]["ready"] is False
    assert onboard["next"] is None
    stored = get_run("saved-stalled", conn=test_db)
    assert stored["historical_status"] == "superseded"
    assert (
        stored["metadata"][SUPERSEDED_BY_KEY]["deployment_run_id"] == "run-20260101-001"
    )
    assert stored["summary"]["status"] != "complete"


def test_newer_failed_delivery_preserves_supersession_history(test_db):
    _seed_run(test_db, "saved-open", row_status=_finished_statuses())
    _seed_deployment(
        test_db, "run-20990101-001", status="failed", at="2099-01-01T00:00:00Z"
    )
    onboard = _onboard()["onboard"]
    assert onboard["run_status"] == "superseded"
    assert onboard["setup_readiness"]["ready"] is False
    assert onboard["superseded_by"]["deployment_run_id"] == "run-20990101-001"


def test_older_failed_delivery_does_not_supersede_the_current_run(test_db):
    _seed_run(test_db, "saved-open", row_status=_finished_statuses())
    _seed_deployment(
        test_db, "run-20000101-001", status="failed", at="2000-01-01T00:00:00Z"
    )
    module = _onboard()
    assert module["state"] != "activated"
    assert module["onboard"]["run_status"] == "open"
    assert module["onboard"]["superseded_by"] is None


def test_superseded_old_checklist_needs_no_current_rows(test_db):
    _seed_run(
        test_db, "historical-checklist", row_status={HOSTING_ROW_ID: STATUS_BLOCKED}
    )
    test_db.execute(
        "DELETE FROM project_onboarding_checklist_rows WHERE run_id=%s AND row_id=%s",
        ("historical-checklist", SCAFFOLD_ROW_ID),
    )
    test_db.commit()
    _seed_deployment(
        test_db,
        "run-20260101-001",
        status="succeeded",
        at="2026-01-01T00:00:00Z",
    )
    module = _onboard()
    progress = module["onboard"]
    assert module["state"] == "activated"
    assert progress["run_status"] == "superseded"
    assert progress["steps_total"] == len(ROW_IDS) - 1
    assert progress["setup_readiness"]["ready"] is False
    assert progress["next"] is None
    assert progress["blocker"] is None
    assert progress["scaffold_installed"] is False
    assert progress["superseded_by"]["deployment_run_id"] == "run-20260101-001"
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM project_onboarding_checklist_rows WHERE run_id=%s",
            ("historical-checklist",),
        ).fetchone()[0]
        == len(ROW_IDS) - 1
    )


def test_active_incomplete_checklist_has_typed_project_recovery(test_db):
    _seed_run(test_db, "incomplete-checklist")
    test_db.execute("UPDATE projects SET slug='example-project' WHERE id=1")
    test_db.execute(
        "DELETE FROM project_onboarding_checklist_rows WHERE run_id=%s AND row_id=%s",
        ("incomplete-checklist", SCAFFOLD_ROW_ID),
    )
    test_db.commit()
    outcome = handle_overview_activation_get(
        FunctionCallRequest(
            function="overview.activation.get",
            actor=ActorContext(session_id=""),
            target=TargetRef(kind="global"),
            payload={},
        )
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "setup_checklist_incomplete"
    assert "project example-project" in outcome.error.message
    assert (
        "yoke onboard checklist init --project example-project --checkout"
        in outcome.error.message
    )
