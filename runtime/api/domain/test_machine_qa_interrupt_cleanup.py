"""Machine-lease cleanup when client-local execution is interrupted."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from yoke_core.domain.machine_qa_case_execution import (
    execute_materialized_machine_baseline_group,
)


def test_baseline_group_interrupt_aborts_issued_contract(
    monkeypatch,
) -> None:
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
        "yoke_core.domain.ssh_mac_host_control.register_ssh_mac_host_control",
        lambda: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_local_execution.execute_machine_case_contract",
        lambda _contract: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        execute_materialized_machine_baseline_group(
            {
                "requirement_id": 41,
                "runner_id": "host_control",
                "method_id": "machine-state-check",
                "project": "yoke",
                "plan_id": 999,
                "host_baseline": "fresh-host",
                "method_config": {"assertions": [{"argv": ["/usr/bin/true"]}]},
                "entry_surface": None,
                "required_completion": None,
            }
        )

    assert [call["function_id"] for call in calls] == [
        "test_machine.baseline_group.begin",
        "test_machine.baseline_group.abort",
    ]
    assert calls[1]["payload"] == {
        "lease_id": 17,
        "contract_digest": "digest",
        "reason": "local_execution_failed",
    }
