"""Machine-lease cleanup when client-local execution is interrupted."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from yoke_core.domain.machine_qa_case_execution import (
    MachineCaseDispatchError,
    execute_materialized_machine_case,
)

_CASE = {
    "requirement_id": 41,
    "runner_id": "host_control",
    "method_id": "machine-state-check",
    "project": "yoke",
    "plan_id": 999,
    "host_baseline": "fresh-host",
    "starting_state": "baseline",
    "method_config": {"assertions": [{"argv": ["/usr/bin/true"]}]},
    "entry_surface": None,
    "required_completion": None,
}


def _issue_then_fail_locally(monkeypatch, failure: BaseException) -> list[dict]:
    """Issue a ready case contract whose local execution raises ``failure``."""
    begin = SimpleNamespace(
        success=True,
        result={
            "state": "ready",
            "execution": {
                "lease_id": 17,
                "contract_digest": "digest",
            },
        },
        error=None,
    )
    aborted = SimpleNamespace(success=True, result={}, error=None)
    calls: list[dict[str, Any]] = []

    def dispatch(**kwargs: Any) -> SimpleNamespace:
        calls.append(dict(kwargs))
        return begin if len(calls) == 1 else aborted

    monkeypatch.setattr(
        "yoke_core.domain.qa_composed_dispatch.call_qa_function",
        dispatch,
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_host_control.register_test_machine_host_control",
        lambda: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_local_execution.execute_machine_case_contract",
        lambda _contract: (_ for _ in ()).throw(failure),
    )
    return calls


def _assert_case_lease_aborted(calls: list[dict]) -> None:
    assert [call["function_id"] for call in calls] == [
        "test_machine.case.begin",
        "test_machine.case.abort",
    ]
    assert calls[1]["payload"] == {
        "lease_id": 17,
        "contract_digest": "digest",
        "reason": "local_execution_failed",
    }


def test_case_interrupt_aborts_issued_contract_and_reraises(monkeypatch) -> None:
    calls = _issue_then_fail_locally(monkeypatch, KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        execute_materialized_machine_case(_CASE)

    _assert_case_lease_aborted(calls)


def test_case_local_failure_aborts_issued_contract_and_says_so(monkeypatch) -> None:
    calls = _issue_then_fail_locally(monkeypatch, RuntimeError("host vanished"))

    with pytest.raises(MachineCaseDispatchError, match="server lease was released"):
        execute_materialized_machine_case(_CASE)

    _assert_case_lease_aborted(calls)
