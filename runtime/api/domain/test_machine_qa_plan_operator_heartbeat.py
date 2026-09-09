"""Plan-scoped operator gates retain server-owned execution authority."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from yoke_contracts.api.function_call import ActorContext
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_core.domain import machine_qa_plan_case_execution


def test_plan_case_progress_heartbeats_before_submission(
    monkeypatch: Any,
) -> None:
    calls: list[str] = []

    def dispatch(
        function_id: str,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(function_id)
        if function_id == "test_machine.plan_case.begin":
            return {"state": "ready", "execution": {"issued": True}}
        if function_id == "test_machine.plan_case.submit":
            return {"result": {"requirement_id": 77}}
        return {}

    def execute(
        _contract: dict[str, Any],
        *,
        progress_callback: Any,
    ) -> Any:
        progress_callback()
        return SimpleNamespace(
            payload={"lease_id": 1, "contract_digest": "digest", "results": []},
            cleanup_artifacts=lambda: None,
        )

    monkeypatch.setattr(machine_qa_plan_case_execution, "_dispatch", dispatch)
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_local_execution.execute_machine_case_contract",
        execute,
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_host_control.register_ssh_mac_host_control",
        lambda: None,
    )

    result = machine_qa_plan_case_execution.execute_plan_machine_case(
        {
            "requirement_id": 77,
            "item_id": 1919,
            "deployment_run_id": None,
        },
        execution_id="plan-execution",
        ordinal=2,
        actor=ActorContext(actor_id="2", session_id="session"),
    )

    assert result == {"requirement_id": 77}
    assert calls == [
        "test_machine.plan_case.begin",
        "qa.plan_execution.heartbeat",
        "test_machine.plan_case.submit",
    ]


def test_plan_case_preserves_local_connection_diagnostics(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        machine_qa_plan_case_execution,
        "_dispatch",
        lambda function_id, **_kwargs: (
            {"state": "ready", "execution": {"issued": True}}
            if function_id == "test_machine.plan_case.begin"
            else {}
        ),
    )
    monkeypatch.setattr(
        "yoke_core.domain.ssh_mac_host_control.register_ssh_mac_host_control",
        lambda: None,
    )

    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise HostControlLocalError(
            code="host_control_connection_failed",
            phase="host_facts_ssh",
            detail="SSH could not collect host facts",
            exit_code=255,
            stderr="Permission denied (publickey)",
            recovery_hint="Check network reachability and SSH authorization.",
        )

    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_local_execution.execute_machine_case_contract",
        refuse,
    )

    with pytest.raises(
        machine_qa_plan_case_execution.MachinePlanCaseDispatchError
    ) as caught:
        machine_qa_plan_case_execution.execute_plan_machine_case(
            {"requirement_id": 77, "item_id": 1919},
            execution_id="plan-execution",
            ordinal=2,
            actor=ActorContext(actor_id="2", session_id="session"),
        )

    assert caught.value.error_code == "host_control_connection_failed"
    assert "phase=host_facts_ssh" in str(caught.value)
    assert "exit_code=255" in str(caught.value)
    assert "Permission denied (publickey)" in str(caught.value)
    assert "Check network reachability" in str(caught.value)
