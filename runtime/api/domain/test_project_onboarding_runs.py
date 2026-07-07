from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_contracts.onboard_checklist import (
    BRANCH_LOCAL_CHECKOUT,
    BRANCH_MACHINE_ONLY,
    OPERATION_INIT,
    ROW_IDS,
    SCHEMA_NAME,
    STATUS_CONFIGURED,
    STATUS_DEFERRED,
    STATUS_VERIFIED,
)
from yoke_core.domain import project_onboarding_runs


def _conn() -> Any:
    name = pg_testdb.create_test_database()
    conn = pg_testdb.connect_test_database(name)
    return pg_testdb.drop_database_on_close(conn, name)


def test_project_onboarding_run_initializes_and_resumes() -> None:
    conn = _conn()

    first = project_onboarding_runs.init_run(
        conn=conn,
        run_id="run-checklist",
        project_id=7,
        branch=BRANCH_MACHINE_ONLY,
        checkout_path="/repo",
        machine_config_path="/home/.yoke/config.json",
    )
    second = project_onboarding_runs.init_run(
        conn=conn,
        run_id="run-checklist",
        project_id=7,
        branch=BRANCH_MACHINE_ONLY,
        row_status={"machine-profile": STATUS_VERIFIED},
    )

    assert first["resumed"] is False
    assert second["resumed"] is True
    assert second["operation"] == OPERATION_INIT
    assert second["summary"]["status"] == "open"
    rows = {row["row_id"]: row for row in second["rows"]}
    assert set(rows) == set(ROW_IDS)
    assert rows["machine-profile"]["status"] == STATUS_VERIFIED
    assert rows["project-source-choice"]["status"] == STATUS_DEFERRED
    assert rows["source-dev-admin-branch"]["status"] == STATUS_DEFERRED

    persisted = project_onboarding_runs.get_run("run-checklist", conn=conn)
    assert persisted["status"] == "open"
    assert persisted["machine_config_path"] == "/home/.yoke/config.json"
    assert persisted["doctor"]["readable"] is True
    assert persisted["metadata"]["authority"] == "db"
    assert persisted["run_id"] == "run-checklist"


def test_project_onboarding_run_updates_rows_and_reads_json_shape() -> None:
    conn = _conn()

    first = project_onboarding_runs.update_run(
        conn=conn,
        run_id="run-db-backed",
        project_id=11,
        branch=BRANCH_LOCAL_CHECKOUT,
        checkout_path="/workspace/app",
        github_repo="owner/repo",
        row_status={"machine-profile": STATUS_CONFIGURED},
        evidence={"machine-profile": {"source": "doctor", "ok": True}},
        blocker={"machine-profile": "waiting on auth"},
        note={"machine-profile": "profile created"},
        metadata={"doctor_source": "unit-test"},
    )
    second = project_onboarding_runs.update_run(
        conn=conn,
        run_id="run-db-backed",
        row_status={"machine-profile": STATUS_VERIFIED},
        blocker={"machine-profile": None},
    )

    assert first["resumed"] is False
    assert second["resumed"] is True
    assert second["operation"] == project_onboarding_runs.OPERATION_RUN
    assert second["run"]["schema"] == SCHEMA_NAME
    assert second["run"]["secret_free"] is True
    assert second["run"]["project"] == {
        "id": 11,
        "root": "/workspace/app",
        "github_repo": "owner/repo",
    }
    rows = {row["row_id"]: row for row in second["run"]["rows"]}
    assert rows["machine-profile"]["status"] == STATUS_VERIFIED
    assert rows["machine-profile"]["evidence"] == {"source": "doctor", "ok": True}
    assert rows["machine-profile"]["blocker"] == ""
    assert rows["machine-profile"]["note"] == "profile created"
    assert rows["machine-profile"]["label"] == rows["machine-profile"]["title"]
    assert second["summary"]["open_row_count"] == len(second["summary"]["open_rows"])
    assert second["doctor"]["status"] == "open"
    assert second["metadata"]["doctor_source"] == "unit-test"


def test_project_onboarding_run_rejects_unknown_status_and_row() -> None:
    conn = _conn()

    with pytest.raises(project_onboarding_runs.ProjectOnboardingRunError):
        project_onboarding_runs.init_run(
            conn=conn,
            run_id="run-checklist",
            row_status={"machine-profile": "done"},
        )

    with pytest.raises(project_onboarding_runs.ProjectOnboardingRunError):
        project_onboarding_runs.update_run(
            conn=conn,
            run_id="run-checklist",
            evidence={"missing-row": "evidence"},
        )
