from __future__ import annotations

from yoke_core.domain.project_structure_write import apply_patch
import pytest
from uuid import uuid4

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


MACHINE_ID = str(uuid4())


@pytest.fixture
def onboarding_db():
    """Repoint the ambient DSN at a fresh disposable database.

    The handlers connect through ``project_onboarding_runs.connect`` (the
    ambient DB connector), so every call in a test lands in the same
    per-test database and run state persists across handler calls.
    """
    with pg_testdb.test_database():
        from yoke_core.domain.db_helpers import connect, utc_now

        conn = connect()
        for project_id in (9, 10):
            conn.execute(
                "INSERT INTO projects (id,slug,name,created_at) VALUES (%s,%s,%s,%s)",
                (project_id, f"project-{project_id}", "Example", utc_now()),
            )
        conn.commit()
        conn.close()
        yield


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id=""),
        target=TargetRef(kind="global"),
        payload={"machine_id": MACHINE_ID, **payload},
    )


@pytest.mark.parametrize(
    "raw", ["{broken", "[]", '{"machines":[]}', '{"execution_profile":[]}']
)
def test_unreadable_saved_metadata_refuses_without_repairing_it(onboarding_db, raw):
    from yoke_core.domain.db_helpers import connect

    first = onboard_checklist.handle_onboard_checklist_init(
        _request(
            "onboard.checklist.init",
            {"project_id": 9},
        )
    ).result_payload
    run_id = first["run_id"]
    conn = connect()
    conn.execute(
        "UPDATE project_onboarding_runs SET metadata_json = %s WHERE run_id = %s",
        (raw, run_id),
    )
    conn.commit()
    for handler in (
        onboard_checklist.handle_onboard_checklist_get,
        onboard_checklist.handle_onboard_checklist_run,
    ):
        result = handler(
            _request("onboard.checklist.get", {"project_id": 9, "run_id": run_id})
        )
        assert result.primary_success is False
        assert result.error.code == "setup_saved_evidence_unreadable"
    assert (
        conn.execute(
            "SELECT metadata_json FROM project_onboarding_runs WHERE run_id = %s",
            (run_id,),
        ).fetchone()[0]
        == raw
    )
    conn.close()


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


def test_onboard_checklist_init_handler_resolves_project_ref(onboarding_db) -> None:
    from yoke_core.domain.db_helpers import connect, iso8601_now

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
            (31, "demo", "Demo", iso8601_now()),
        )
        conn.commit()
    finally:
        conn.close()

    outcome = onboard_checklist.handle_onboard_checklist_init(
        _request(
            "onboard.checklist.init",
            {
                "run_id": "run-handler-standalone",
                "project": "demo",
                "checkout_path": "/repo",
            },
        )
    )

    assert outcome.primary_success is True
    assert outcome.result_payload["run"]["project_id"] == 31


def test_onboard_checklist_init_handler_rejects_unknown_project_ref(
    onboarding_db,
) -> None:
    outcome = onboard_checklist.handle_onboard_checklist_init(
        _request(
            "onboard.checklist.init",
            {"run_id": "run-handler-unknown-project", "project": "no-such-project"},
        )
    )

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "project_not_found"


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
                "project_id": 10,
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
    assert rows["machine-profile"]["status"] == "unknown"
    assert rows["machine-profile"]["saved_status"] == STATUS_VERIFIED
    assert rows["machine-profile"]["saved_evidence"] == {"checked_by": "doctor"}
    assert rows["machine-profile"]["reason"] == "machine_not_checked"
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
    assert outcome.error.code == "onboarding_row_invalid"


def test_read_only_get_preserves_profile_and_rechecks_changed_settings(onboarding_db):
    profile = {"hosting": "deferred", "delivery": "no-default"}
    first = onboard_checklist.handle_onboard_checklist_init(
        _request(
            "onboard.checklist.init",
            {
                "project_id": 9,
                "metadata": {"execution_profile": profile},
                "row_status": {"hosting-setup": "deferred"},
            },
        )
    ).result_payload
    same = onboard_checklist.handle_onboard_checklist_get(
        _request(
            "onboard.checklist.get",
            {"project_id": 9},
        )
    ).result_payload["run"]
    assert same["execution_profile"] == profile
    assert same["profile_changed"] is False
    assert same["updated_at"] == first["updated_at"]
    apply_patch(
        "9",
        ops=[
            {
                "op": "put",
                "family": "hosting_posture",
                "attachment": "project",
                "payload": {
                    "posture": "no-yoke-managed-host",
                    "provider": "existing-provider",
                },
            }
        ],
    )
    changed = onboard_checklist.handle_onboard_checklist_get(
        _request(
            "onboard.checklist.get",
            {"project_id": 9},
        )
    ).result_payload["run"]
    rows = {row["row_id"]: row for row in changed["rows"]}
    assert changed["profile_changed"] is True
    assert changed["execution_profile"] == profile
    assert changed["updated_at"] == first["updated_at"]
    assert rows["hosting-setup"]["status"] == "not-needed"
    assert rows["hosting-setup"]["saved_status"] == "deferred"
    assert rows["human-interview"]["reason"] == "setup_profile_changed"


def test_payload_cannot_escape_authorized_project(onboarding_db):
    request = FunctionCallRequest(
        function="onboard.checklist.init",
        actor=ActorContext(session_id=""),
        target=TargetRef(kind="global", project_id="9"),
        payload={"project_id": 10},
    )
    outcome = onboard_checklist.handle_onboard_checklist_init(request)
    assert outcome.primary_success is False
    assert outcome.error.code == "onboarding_project_mismatch"


def test_missing_read_does_not_initialize_a_run(onboarding_db):
    outcome = onboard_checklist.handle_onboard_checklist_get(
        _request(
            "onboard.checklist.get",
            {"project_id": 9},
        )
    )
    assert outcome.primary_success is True
    assert outcome.result_payload["exists"] is False
    assert outcome.result_payload["run"] is None


def test_get_projects_next_action_from_current_rows(onboarding_db):
    from yoke_core.domain.project_onboarding_next_action import select_next_action

    initialized = onboard_checklist.handle_onboard_checklist_init(
        _request(
            "onboard.checklist.init",
            {"project_id": 9},
        )
    )
    assert initialized.primary_success
    read = onboard_checklist.handle_onboard_checklist_get(
        _request(
            "onboard.checklist.get",
            {"project_id": 9},
        )
    )
    assert read.primary_success
    run = read.result_payload["run"]
    assert run["next_action"] == select_next_action(run["rows"], run["setup_readiness"])
    assert run["next_action"]["row_id"] == "package-install"
    assert initialized.result_payload["run"]["next_action"] == run["next_action"]
