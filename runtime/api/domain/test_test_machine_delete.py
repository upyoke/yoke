"""QA registration deletion preserves history and physical-host obligations."""

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
    TEST_MACHINE_SETTINGS,
)
from runtime.api.domain.machine_reset_debt_test_support import verified_reset
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import machine_qa_delete as deletion
from yoke_core.domain.machine_qa_capability import (
    host_claim_target,
    replace_test_machine_settings,
    test_machine_list as list_machines,
)
from yoke_core.domain.machine_reset_debt import record_reset_owed
from yoke_core.domain.coordination_claims import acquire
from yoke_core.domain.projects_capabilities_settings import (
    cmd_capability_remove_settings,
)

NAME = TEST_MACHINE_SETTINGS["resource_name"]
CAP = "test-machine:" + NAME


@pytest.fixture
def machine(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    return test_db


def delete(project="yoke", **updates):
    return deletion.handle_delete(
        FunctionCallRequest(
            actor=ActorContext(session_id="session-machine-group"),
            function="test_machine.delete",
            target=TargetRef(kind="global"),
            payload={"project": project, "test_machine": NAME, **updates},
        )
    )


def capability_count(conn):
    return conn.execute(
        "SELECT count(*) FROM project_capabilities WHERE type=%s", (CAP,)
    ).fetchone()[0]


def test_deletes_cascades_and_allows_empty_project_and_reregistration(machine):
    verified_reset(machine, NAME, "fresh-host")
    outcome = delete()
    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["deleted"] is True
    assert capability_count(machine) == 0
    for table in ("test_machine_operation_receipts", "test_machine_verifications"):
        assert (
            machine.execute(
                f"SELECT count(*) FROM {table} WHERE capability_type=%s", (CAP,)
            ).fetchone()[0]
            == 0
        )
    assert list_machines(machine, project="yoke")["test_machines"] == []
    replace_test_machine_settings(
        machine, project="yoke", settings=TEST_MACHINE_SETTINGS, base_settings=None
    )
    assert capability_count(machine) == 1


def test_missing_registration_refuses_with_list_recipe(machine):
    assert delete().primary_success
    result = delete()
    assert result.error.code == "test_machine_not_found"
    assert "yoke test-machine list" in result.error.message


def test_active_physical_host_lease_refuses(machine):
    claim = acquire(
        machine, host_claim_target(NAME), "session-machine-group", reason="test custody"
    )
    result = delete()
    assert result.error.code == "test_machine_active_lease"
    assert capability_count(machine) == 1
    assert (
        machine.execute(
            "SELECT released_at FROM work_claims WHERE id=%s", (claim.id,)
        ).fetchone()[0]
        is None
    )


@pytest.mark.parametrize("state", ["waiting", "reserved"])
def test_unsettled_wait_any_project_refuses(machine, state):
    machine.execute(
        "INSERT INTO qa_test_machine_waits(id,test_machine,session_id,actor_id,queued_at,state,resume_command) "
        "VALUES('delete-wait',%s,'session-machine-group',1,CURRENT_TIMESTAMP,%s,'resume QA')",
        (NAME, state),
    )
    machine.commit()
    result = delete()
    assert result.error.code == "test_machine_wait_pending"
    assert capability_count(machine) == 1


@pytest.mark.parametrize("state", ["granted", "cancelled"])
def test_settled_history_is_unchanged(machine, state):
    machine.execute(
        "INSERT INTO qa_test_machine_waits(id,test_machine,session_id,actor_id,queued_at,state,resume_command) "
        "VALUES('delete-history',%s,'session-machine-group',1,CURRENT_TIMESTAMP,%s,'resume QA')",
        (NAME, state),
    )
    machine.commit()
    before = dict(
        machine.execute(
            "SELECT * FROM qa_test_machine_waits WHERE id='delete-history'"
        ).fetchone()
    )
    assert delete().primary_success
    assert (
        dict(
            machine.execute(
                "SELECT * FROM qa_test_machine_waits WHERE id='delete-history'"
            ).fetchone()
        )
        == before
    )


def test_owed_reset_refuses_and_preserves_receipts(machine):
    record_reset_owed(
        machine,
        case={"project_id": 1, "host_baseline": "fresh-host"},
        test_machine=NAME,
        lease_id=77,
    )
    machine.commit()
    result = delete()
    assert result.error.code == "machine_reset_owed"
    assert "yoke test-machine reset" in result.error.message
    assert capability_count(machine) == 1


def shared_registration(conn):
    conn.execute(
        "INSERT INTO projects(id,slug,name,public_item_prefix,created_at) VALUES(9001,'other','Other','OTH',CURRENT_TIMESTAMP)"
    )
    conn.execute(
        "INSERT INTO project_capabilities(project_id,type,settings,created_at) "
        "SELECT 9001,type,settings,created_at FROM project_capabilities WHERE project_id=1 AND type=%s",
        (CAP,),
    )
    conn.commit()


def test_post_delete_debt_check_rolls_back_cascades(machine):
    shared_registration(machine)
    record_reset_owed(
        machine,
        case={"project_id": 9001, "host_baseline": "fresh-host"},
        test_machine=NAME,
        lease_id=77,
    )
    machine.commit()
    verified_reset(machine, NAME, "fresh-host")
    result = delete()
    assert result.error.code == "machine_reset_owed"
    assert capability_count(machine) == 2
    assert (
        machine.execute(
            "SELECT count(*) FROM test_machine_operation_receipts WHERE capability_type=%s",
            (CAP,),
        ).fetchone()[0]
        == 2
    )


def test_deletes_only_selected_project_registration(machine):
    shared_registration(machine)
    result = delete()
    assert result.primary_success, result.error
    assert capability_count(machine) == 1
    assert (
        list_machines(machine, project="other")["test_machines"][0]["test_machine"]
        == NAME
    )


def test_generic_removal_refuses_before_connect(machine):
    with pytest.raises(ValueError, match="test_machine_delete_required"):
        cmd_capability_remove_settings("yoke", CAP, base_settings_json="{}")
    assert capability_count(machine) == 1


def test_explicit_name_required(machine):
    result = delete(test_machine=None)
    assert result.error.code == "payload_invalid"
    assert capability_count(machine) == 1
