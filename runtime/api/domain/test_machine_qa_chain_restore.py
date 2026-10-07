"""The local runner resets before a chain and restores after it ends."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import machine_qa_local_execution as local
from yoke_core.domain.machine_qa_case_result import MachineCaseResult


def _contract(*, baselines, starting_state="baseline", ends_chain=True):
    case = SimpleNamespace(
        requirement_id=11,
        starting_state=starting_state,
        host_baseline="fresh-host" if starting_state != "as_is" else None,
        ends_chain=ends_chain,
        project="yoke",
    )
    return SimpleNamespace(
        operation="plan_case",
        baselines=list(baselines),
        cases=[case],
        settings={"resource_name": "mac-mini-lab"},
        lease_id=3,
        contract_digest="d" * 64,
    )


def _run(monkeypatch, contract, *, outcome="passed", reset_ok=True, raises=None):
    reached: list[str] = []
    ran: list[int] = []

    def reach(name):
        reached.append(name)
        ok = reset_ok if len(reached) == 1 and contract.baselines else True
        return SimpleNamespace(
            ok=ok, error_code=None if ok else "reset_failed", evidence={}
        )

    def run_case(execution, case):
        ran.append(case.requirement_id)
        if raises is not None:
            raise raises
        verdict = {"passed": "pass", "failed": "fail"}[outcome]
        return MachineCaseResult(
            case_outcome=outcome,
            verdict=verdict,
            evidence={"runner_id": "host_control", "machine": "mac-mini-lab"},
            error_code=None if outcome == "passed" else "check_failed",
        )

    execution = SimpleNamespace(
        material=SimpleNamespace(secrets={}), reach_baseline=reach
    )
    monkeypatch.setattr(
        local.HostControlExecutionContract, "model_validate", lambda raw: contract
    )
    monkeypatch.setattr(local, "_execution", lambda c, **kwargs: execution)
    monkeypatch.setattr(local, "execute_case_with_fixture_lifecycle", run_case)
    submission = local.execute_machine_case_contract({"contract": "issued"})
    return submission.payload["results"][0], reached, ran


def test_a_chain_end_resets_first_and_restores_after(monkeypatch) -> None:
    row, reached, ran = _run(monkeypatch, _contract(baselines=["fresh-host"]))
    assert reached == ["fresh-host", "fresh-host"]
    assert ran == [11]
    assert row["evidence"]["starting_state_restore"]["restored"] is True


def test_a_passing_case_inside_a_chain_leaves_the_machine_for_its_follower(
    monkeypatch,
) -> None:
    contract = _contract(baselines=["fresh-host"], ends_chain=False)
    row, reached, _ = _run(monkeypatch, contract)
    assert reached == ["fresh-host"]
    assert "starting_state_restore" not in row["evidence"]


def test_a_failed_case_restores_even_when_its_chain_continues(monkeypatch) -> None:
    contract = _contract(baselines=[], starting_state="inherit", ends_chain=False)
    row, reached, _ = _run(monkeypatch, contract, outcome="failed")
    assert reached == ["fresh-host"]
    assert row["evidence"]["starting_state_restore"]["baseline"] == "fresh-host"


def test_a_failed_reset_leaves_the_case_unstarted_and_blocked(monkeypatch) -> None:
    row, _, ran = _run(monkeypatch, _contract(baselines=["fresh-host"]), reset_ok=False)
    assert ran == []
    assert row["case_outcome"] == "blocked_on_precondition"
    assert row["error_code"] == "starting_state_reset_failed"
    assert row["evidence"]["case_started"] is False
    assert row["evidence"]["starting_state_reset"]["ok"] is False


def test_an_as_is_chain_records_that_nothing_can_be_restored(monkeypatch) -> None:
    contract = _contract(baselines=[], starting_state="as_is")
    row, reached, _ = _run(monkeypatch, contract)
    assert reached == []
    restore = row["evidence"]["starting_state_restore"]
    assert restore["restored"] is False
    assert "no declared starting state" in restore["reason"]


def test_a_local_error_still_restores_and_says_so(monkeypatch) -> None:
    with pytest.raises(RuntimeError) as raised:
        _run(
            monkeypatch,
            _contract(baselines=["fresh-host"]),
            raises=RuntimeError("terminal bridge lost"),
        )
    assert "starting state restored to 'fresh-host'" in raised.value.__notes__
