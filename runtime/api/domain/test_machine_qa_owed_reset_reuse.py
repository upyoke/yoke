"""A recovered reset proves the case baseline without resetting the host twice."""

import pytest

from runtime.api.domain.machine_qa_chain_restore_test_support import _contract, _run


@pytest.mark.parametrize("owed", ["fresh-host", "shell-preconfigured"])
def test_recovery_reuses_only_the_same_starting_baseline(monkeypatch, owed):
    contract = _contract(baselines=["fresh-host"], ends_chain=False)
    contract.reset_owed_baseline = owed
    contract.project = "example"

    row, reached, ran = _run(monkeypatch, contract)

    assert reached == ([owed] if owed == "fresh-host" else [owed, "fresh-host"])
    assert ran == [11]
    assert row["verdict"] == "pass"
    assert row["evidence"]["owed_reset"]["ok"] is True
    assert row["evidence"]["owed_reset"]["baseline"] == owed


def test_a_failed_owed_reset_never_starts_the_case(monkeypatch):
    contract = _contract(baselines=["fresh-host"], ends_chain=False)
    contract.reset_owed_baseline = "fresh-host"
    contract.project = "example"

    from types import SimpleNamespace

    from yoke_core.domain import machine_qa_local_execution as local

    reached, ran = [], []
    execution = SimpleNamespace(
        material=SimpleNamespace(secrets={}),
        reach_baseline=lambda name: reached.append(name) or SimpleNamespace(
            ok=False, error_code="windows_profile_reset_failed", evidence={}
        ),
    )
    monkeypatch.setattr(
        local.HostControlExecutionContract, "model_validate", lambda raw: contract
    )
    monkeypatch.setattr(local, "_execution", lambda c, **kwargs: execution)
    monkeypatch.setattr(
        local, "execute_case_with_fixture_lifecycle", lambda e, c: ran.append(c)
    )
    submission = local.execute_machine_case_contract({"contract": "issued"})
    row = submission.payload["results"][0]

    assert reached == ["fresh-host"]
    assert ran == []
    assert row["error_code"] == "machine_needs_repair"
    assert row["evidence"]["owed_reset"]["ok"] is False
    assert (
        row["evidence"]["owed_reset"]["error_code"] == "windows_profile_reset_failed"
    )
    assert row["evidence"]["case_started"] is False


def test_a_failed_owed_mission_reset_names_its_cause():
    from types import SimpleNamespace

    from yoke_core.domain.agent_mission_preparation import prepare_mission

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
    evidence = {"reason": "Claude real request failed", "exit_code": 13}
    execution = SimpleNamespace(
        material=SimpleNamespace(secrets={}),
        reach_baseline=lambda name: SimpleNamespace(
            ok=False, error_code="windows_profile_reset_failed", evidence=evidence
        ),
    )

    result = prepare_mission(
        contract,
        execution_factory=lambda *a, **kw: execution,
        scratch_factory=lambda *a, **kw: pytest.fail("must not create scratch"),
    )

    preparation = result["preparation"]
    failure = preparation["evidence"]["preparation_failure"]
    assert preparation["error_code"] == "machine_needs_repair"
    assert failure["error_code"] == "machine_needs_repair"
    assert failure["exit_code"] == 13
    for text in ("windows_profile_reset_failed", "Claude real request failed", "exit_code=13"):
        assert text in failure["diagnostic"]
    assert "yoke test-machine reset" in failure["recovery"]


def test_reused_reset_receipt_clears_durable_debt(test_db, tmp_path, monkeypatch):
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from runtime.api.domain.machine_reset_debt_test_support import _debt
    from yoke_core.domain.machine_reset_debt import record_owed_reset, reset_owed

    configure_test_machine(test_db, tmp_path, monkeypatch)
    machine = _debt(test_db)
    contract = _contract(baselines=["fresh-host"], ends_chain=False)
    contract.reset_owed_baseline = "fresh-host"
    contract.project_id = 1
    contract.project = "example"
    contract.settings["resource_name"] = machine

    row, reached, _ = _run(monkeypatch, contract)
    record_owed_reset(test_db, contract, row["evidence"])

    assert reached == ["fresh-host"]
    assert reset_owed(test_db, machine) is None
