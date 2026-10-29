"""A recovered reset proves the case baseline without resetting the host twice."""

import pytest

from runtime.api.domain.test_machine_qa_chain_restore import _contract, _run


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

    row, reached, ran = _run(monkeypatch, contract, reset_ok=False)

    assert reached == ["fresh-host"]
    assert ran == []
    assert row["error_code"] == "machine_needs_repair"
    assert row["evidence"]["owed_reset"]["ok"] is False
    assert row["evidence"]["case_started"] is False


def test_reused_reset_receipt_clears_durable_debt(test_db, tmp_path, monkeypatch):
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from runtime.api.domain.test_machine_reset_debt import _debt
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
