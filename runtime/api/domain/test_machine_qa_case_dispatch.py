"""Client dispatch coverage for one materialized Machine QA case."""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import pytest

from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain.machine_qa_case_execution import (
    MachineCaseDispatchError,
    execute_materialized_machine_case,
)
from yoke_core.domain.machine_qa_local_execution import (
    LocalHostControlSubmission,
)


def test_machine_leaf_dispatches_begin_then_submit_for_target() -> None:
    case = {
        "requirement_id": 41,
        "executor_id": "host_control",
        "method_id": "machine-state-check",
        "project": "yoke",
        "method_config": {"assertions": [{"argv": ["/usr/bin/true"]}]},
        "entry_surface": None,
        "required_completion": None,
    }
    begin = SimpleNamespace(
        success=True,
        result={
            "state": "ready",
            "execution": {"server": "issued-contract"},
        },
        error=None,
    )
    submit = SimpleNamespace(
        success=True,
        result={
            "requirement_id": 41,
            "executor_id": "host_control",
            "verdict": "pass",
        },
        error=None,
    )
    with (
        mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            side_effect=[begin, submit],
        ) as dispatch,
        mock.patch(
            "yoke_core.domain.ssh_mac_host_control.register_ssh_mac_host_control",
        ),
        mock.patch(
            "yoke_core.domain.machine_qa_local_execution.execute_machine_case_contract",
            return_value=LocalHostControlSubmission(
                payload={
                    "lease_id": 17,
                    "contract_digest": "digest",
                    "results": [],
                }
            ),
        ) as execute_local,
    ):
        result = execute_materialized_machine_case(
            case,
            actor=ActorContext(
                actor_id="2",
                session_id="session-machine-case",
            ),
        )

    assert result["requirement_id"] == 41
    assert execute_local.call_args.args == ({"server": "issued-contract"},)
    requests = [call.kwargs for call in dispatch.call_args_list]
    assert [request["function_id"] for request in requests] == [
        "test_machine.case.begin",
        "test_machine.case.submit",
    ]
    assert [request["target"].qa_requirement_id for request in requests] == [41, 41]
    assert requests[0]["payload"] == {}
    assert requests[1]["payload"] == {
        "lease_id": 17,
        "contract_digest": "digest",
        "results": [],
    }


def test_machine_leaf_local_failure_dispatches_abort() -> None:
    case = {
        "requirement_id": 41,
        "executor_id": "host_control",
        "method_id": "machine-state-check",
        "project": "yoke",
        "method_config": {"assertions": [{"argv": ["/usr/bin/true"]}]},
        "entry_surface": None,
        "required_completion": None,
    }
    begin = SimpleNamespace(
        success=True,
        result={
            "state": "ready",
            "execution": {
                "lease_id": 18,
                "contract_digest": "digest-18",
            },
        },
        error=None,
    )
    abort = SimpleNamespace(
        success=True,
        result={
            "lease_id": 18,
            "released": True,
            "reason": "local_execution_failed",
        },
        error=None,
    )
    with (
        mock.patch(
            "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
            side_effect=[begin, abort],
        ) as dispatch,
        mock.patch(
            "yoke_core.domain.ssh_mac_host_control.register_ssh_mac_host_control",
        ),
        mock.patch(
            "yoke_core.domain.machine_qa_local_execution.execute_machine_case_contract",
            side_effect=RuntimeError("local control unavailable"),
        ),
    ):
        with pytest.raises(
            MachineCaseDispatchError,
            match="server lease was released",
        ):
            execute_materialized_machine_case(
                case,
                actor=ActorContext(
                    actor_id="2",
                    session_id="session-machine-case",
                ),
            )

    requests = [call.kwargs for call in dispatch.call_args_list]
    assert [request["function_id"] for request in requests] == [
        "test_machine.case.begin",
        "test_machine.case.abort",
    ]
    assert requests[1]["payload"] == {
        "lease_id": 18,
        "contract_digest": "digest-18",
        "reason": "local_execution_failed",
    }


def test_machine_leaf_refuses_non_machine_executor() -> None:
    with mock.patch(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
    ) as dispatch:
        with pytest.raises(
            MachineCaseDispatchError,
            match="not a registered Machine QA case",
        ):
            execute_materialized_machine_case(
                {
                    "requirement_id": 41,
                    "executor_id": "worktree_run",
                    "method_id": "command",
                }
            )
    dispatch.assert_not_called()
