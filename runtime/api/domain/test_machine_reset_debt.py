"""Unproven teardown releases custody but requires recovery before new host work."""

from types import SimpleNamespace

import pytest

from runtime.api.domain import test_agent_mission_cleanup as cleanup_support
from runtime.api.domain.machine_operation_test_support import run_operation
from yoke_core.domain.agent_mission_recording import handle_agent_mission_access
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.machine_reset_debt import record_reset_owed, reset_owed
from yoke_core.domain.qa_plan_execution_state import lock_plan_execution

removed_mission = cleanup_support.removed_mission


@pytest.mark.parametrize(
    "restore", [None, {"restored": False}, {"restored": True, "baseline": "other"}]
)
def test_unproven_finish_releases_and_records_owed_baseline(
    test_db,
    removed_mission,
    restore,
):
    request, _, original = removed_mission
    acquired = handle_agent_mission_access(request)
    assert acquired.primary_success, acquired.error
    finished = handle_agent_mission_access(
        request.model_copy(
            update={
                "payload": {
                    **request.payload,
                    "cleanup": "finish",
                    "lease_id": original["lease_id"],
                    "restore": restore,
                }
            }
        )
    )
    assert finished.primary_success, finished.error
    assert not get_claim(test_db, original["lease_id"]).is_active
    assert (
        lock_plan_execution(test_db, request.payload["execution_id"])[
            "machine_lease_id"
        ]
        is None
    )
    assert reset_owed(test_db, original["settings"]["resource_name"]) == "fresh-host"


def _debt(conn, baseline="fresh-host"):
    from runtime.api.domain.machine_operation_test_support import MACHINE

    record_reset_owed(
        conn,
        case={"project_id": 1, "host_baseline": baseline},
        machine=MACHINE,
        lease_id=77,
    )
    conn.commit()
    return MACHINE


def test_manual_success_clears_debt_and_failed_reset_retains_it(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from runtime.api.domain.machine_qa_test_support import FakeHostControl

    configure_test_machine(test_db, tmp_path, monkeypatch)
    machine = _debt(test_db)
    failed, _ = run_operation("reset", control=FakeHostControl(refuse_full_reset=True))
    assert failed.primary_success, failed.error
    assert reset_owed(test_db, machine) == "fresh-host"
    passed, _ = run_operation("reset", control=FakeHostControl())
    assert passed.primary_success, passed.error
    assert reset_owed(test_db, machine) is None


def test_steering_names_owed_machine_and_reset_command(test_db, tmp_path, monkeypatch):
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from yoke_core.domain.steering_fleet_report_test_machines import (
        read_reset_debts,
        reset_debt_lines,
    )

    configure_test_machine(test_db, tmp_path, monkeypatch)
    machine = _debt(test_db, "shell-preconfigured")
    rows = read_reset_debts(test_db, 1)
    assert rows == (
        (
            machine,
            f"yoke test-machine reset --project 1 --test-machine {machine} --baseline shell-preconfigured",
            None,
        ),
    )
    assert "machine_needs_repair" in reset_debt_lines(rows)[0]


@pytest.mark.parametrize("starting_state", ["as_is", "inherit"])
@pytest.mark.parametrize("ok", [False, True])
def test_no_baseline_case_recovers_before_any_case_work(
    monkeypatch, starting_state, ok
):
    from runtime.api.domain.test_machine_qa_chain_restore import _contract
    from yoke_core.domain import machine_qa_local_execution as local
    from yoke_core.domain.machine_qa_case_result import MachineCaseResult

    contract = _contract(baselines=[], starting_state=starting_state, ends_chain=False)
    contract.project = "example"
    contract.reset_owed_baseline = "shell-preconfigured"
    calls = []
    execution = SimpleNamespace(
        material=SimpleNamespace(secrets={}),
        reach_baseline=lambda name: (
            calls.append(name) or SimpleNamespace(ok=ok, error_code=None, evidence={})
        ),
    )
    monkeypatch.setattr(
        local.HostControlExecutionContract, "model_validate", lambda raw: contract
    )
    monkeypatch.setattr(local, "_execution", lambda c, **kwargs: execution)
    monkeypatch.setattr(
        local,
        "execute_case_with_fixture_lifecycle",
        lambda e, c: calls.append("case") or MachineCaseResult("passed", "pass", {}),
    )
    row = local.execute_machine_case_contract({}).payload["results"][0]
    assert calls == (["shell-preconfigured", "case"] if ok else ["shell-preconfigured"])
    assert row["evidence"]["owed_reset"]["ok"] is ok
    if not ok:
        assert row["error_code"] == "machine_needs_repair"
        assert row["evidence"]["case_started"] is False
        assert "yoke test-machine reset" in row["evidence"]["owed_reset"]["recovery"]


@pytest.mark.parametrize("ok", [False, True])
def test_mission_recovers_before_scratch_and_commands(monkeypatch, ok):
    from yoke_core.domain.agent_mission_preparation import prepare_mission

    calls = []
    contract = SimpleNamespace(
        baselines=[],
        cases=[SimpleNamespace(host_baseline=None, method_config={})],
        plan_execution_id="mission",
        continues_execution_id=None,
        lease_id=4,
        contract_digest="d",
        reset_owed_baseline="fresh-host",
        settings={"resource_name": "lab"},
        project="example",
    )
    execution = SimpleNamespace(
        material=SimpleNamespace(secrets={}),
        control=object(),
        reach_baseline=lambda name: (
            calls.append(name) or SimpleNamespace(ok=ok, error_code=None, evidence={})
        ),
    )
    monkeypatch.setattr(
        "yoke_core.domain.agent_mission_preparation.require_mission_disk_space",
        lambda c: {},
    )
    result = prepare_mission(
        contract,
        execution_factory=lambda *a, **kw: execution,
        scratch_factory=lambda *a, **kw: (
            calls.append("scratch") or {"scratch_path": "scratch"}
        ),
    )
    assert calls == (["fresh-host", "scratch"] if ok else ["fresh-host"])
    assert result["preparation"]["ok"] is ok
    if not ok:
        assert result["preparation"]["error_code"] == "machine_needs_repair"
        assert (
            "yoke test-machine reset"
            in result["preparation"]["evidence"]["preparation_failure"]["recovery"]
        )


def test_failed_artifact_storage_still_releases_and_records_debt(
    test_db, removed_mission, monkeypatch
):
    request, _, original = removed_mission
    acquired = handle_agent_mission_access(request)
    assert acquired.primary_success, acquired.error

    def unavailable(*args):
        raise OSError("artifact store unavailable")

    monkeypatch.setattr(
        "yoke_core.domain.handlers.qa_artifact_add.handle_qa_artifact_add", unavailable
    )
    finished = handle_agent_mission_access(
        request.model_copy(
            update={
                "payload": {
                    **request.payload,
                    "cleanup": "finish",
                    "lease_id": original["lease_id"],
                    "restore": {"restored": True, "baseline": "fresh-host"},
                }
            }
        )
    )
    assert not finished.primary_success
    assert finished.error.code == "mission_restore_evidence_failed"
    assert not get_claim(test_db, original["lease_id"]).is_active
    assert reset_owed(test_db, original["settings"]["resource_name"]) == "fresh-host"


def test_debt_changes_fleet_actionability_fingerprint_and_render(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from yoke_core.domain.steering_fleet_report_render import (
        report_body,
        scope_actionable_digest,
    )
    from yoke_core.domain.steering_fleet_report_projection import report_dict

    seed_steering_scope(test_db)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    before = compose(test_db)
    machine = _debt(test_db)
    report = compose(test_db)
    assert report.actionable
    assert report.fingerprint() != before.fingerprint()
    assert report.reset_debts[0][0] == machine
    assert report_dict(report)["reset_debts"][0]["machine"] == machine
    assert "machine_needs_repair" in report_body(report)
    assert "yoke test-machine reset" in scope_actionable_digest(report)


def test_debt_writer_preserves_the_callers_transaction(test_db, tmp_path, monkeypatch):
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from runtime.api.domain.machine_operation_test_support import MACHINE

    configure_test_machine(test_db, tmp_path, monkeypatch)
    test_db.execute("CREATE TEMP TABLE reset_debt_probe (value INTEGER)")
    test_db.commit()
    test_db.execute("INSERT INTO reset_debt_probe VALUES (1)")
    record_reset_owed(
        test_db,
        case={"project_id": 1, "host_baseline": "fresh-host"},
        machine=MACHINE,
        lease_id=77,
    )
    test_db.rollback()
    assert test_db.execute("SELECT count(*) FROM reset_debt_probe").fetchone()[0] == 0
    assert reset_owed(test_db, MACHINE) is None


def test_lost_savepoint_is_not_treated_as_an_artifact_failure(
    test_db, removed_mission, monkeypatch
):
    from yoke_core.domain.db_savepoint import SavepointLostError

    request, _, original = removed_mission
    assert handle_agent_mission_access(request).primary_success

    def lost(*args):
        raise SavepointLostError("transaction lost")

    monkeypatch.setattr(
        "yoke_core.domain.handlers.qa_artifact_add.handle_qa_artifact_add", lost
    )
    with pytest.raises(SavepointLostError):
        handle_agent_mission_access(
            request.model_copy(
                update={
                    "payload": {
                        **request.payload,
                        "cleanup": "finish",
                        "lease_id": original["lease_id"],
                        "restore": {"restored": True, "baseline": "fresh-host"},
                    }
                }
            )
        )
    assert get_claim(test_db, original["lease_id"]).is_active


@pytest.mark.parametrize("starting_state", ["as_is", "inherit"])
def test_no_baseline_debt_does_not_authorize_reset_or_erase_real_debt(
    test_db, tmp_path, monkeypatch, starting_state
):
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from runtime.api.domain.machine_operation_test_support import MACHINE

    configure_test_machine(test_db, tmp_path, monkeypatch)
    case = {"project_id": 1, "host_baseline": None, "starting_state": starting_state}
    record_reset_owed(test_db, case=case, machine=MACHINE, lease_id=78)
    assert reset_owed(test_db, MACHINE) is None
    _debt(test_db, "shell-preconfigured")
    record_reset_owed(test_db, case=case, machine=MACHINE, lease_id=78)
    assert reset_owed(test_db, MACHINE) == "shell-preconfigured"
