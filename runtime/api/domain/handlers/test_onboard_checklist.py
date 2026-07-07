from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.onboard_checklist import (
    BRANCH_LOCAL_CHECKOUT,
    BRANCH_MACHINE_ONLY,
    OPERATION_INIT,
    SCHEMA_NAME,
    STATUS_CONFIGURED,
    STATUS_VERIFIED,
)
from yoke_core.domain import project_onboarding_runs
from yoke_core.domain.handlers import onboard_checklist


@pytest.fixture
def onboarding_db():
    """Repoint the ambient DSN at a fresh disposable database.

    The handlers connect through ``project_onboarding_runs.connect`` (the
    ambient DB connector), so every call in a test lands in the same
    per-test database and run state persists across handler calls.
    """
    with pg_testdb.test_database():
        yield


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id=""),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def test_onboard_checklist_init_handler_uses_db_record(onboarding_db) -> None:
    outcome = onboard_checklist.handle_onboard_checklist_init(
        _request(
            "onboard.checklist.init",
            {
                "run_id": "run-handler-init",
                "project_id": 9,
                "branch": BRANCH_MACHINE_ONLY,
                "machine_config_path": "/home/.yoke/config.json",
            },
        )
    )

    assert outcome.primary_success is True
    result = outcome.result_payload
    assert result["operation"] == OPERATION_INIT
    assert result["run"]["run_id"] == "run-handler-init"
    assert result["run"]["doctor"]["authority"] == "db"
    assert result["run"]["machine_config_path"] == "/home/.yoke/config.json"


def test_onboard_checklist_run_handler_updates_and_reads_json_shape(
    onboarding_db,
) -> None:
    first = onboard_checklist.handle_onboard_checklist_run(
        _request(
            project_onboarding_runs.OPERATION_RUN,
            {
                "run_id": "run-handler",
                "project_id": 10,
                "branch": BRANCH_LOCAL_CHECKOUT,
                "checkout_path": "/repo",
                "row_status": {"machine-profile": STATUS_CONFIGURED},
                "evidence": {"machine-profile": {"checked_by": "doctor"}},
                "blocker": {"machine-profile": "token missing"},
                "note": {"machine-profile": "created profile"},
            },
        )
    )
    second = onboard_checklist.handle_onboard_checklist_run(
        _request(
            project_onboarding_runs.OPERATION_RUN,
            {
                "run_id": "run-handler",
                "row_status": {"machine-profile": STATUS_VERIFIED},
                "blocker": {"machine-profile": None},
            },
        )
    )

    assert first.primary_success is True
    assert second.primary_success is True
    result = second.result_payload
    assert result["operation"] == project_onboarding_runs.OPERATION_RUN
    assert result["resumed"] is True
    assert result["run"]["schema"] == SCHEMA_NAME
    assert result["run"]["secret_free"] is True
    assert result["run"]["project"] == {"id": 10, "root": "/repo"}
    rows = {row["row_id"]: row for row in result["run"]["rows"]}
    assert rows["machine-profile"]["status"] == STATUS_VERIFIED
    assert rows["machine-profile"]["evidence"] == {"checked_by": "doctor"}
    assert rows["machine-profile"]["blocker"] == ""
    assert rows["machine-profile"]["note"] == "created profile"


def test_onboard_checklist_run_handler_rejects_invalid_row(onboarding_db) -> None:
    outcome = onboard_checklist.handle_onboard_checklist_run(
        _request(
            project_onboarding_runs.OPERATION_RUN,
            {
                "run_id": "run-handler-invalid",
                "row_status": {"not-a-row": STATUS_VERIFIED},
            },
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "onboard_checklist_failed"
