"""Admit declared-host Command cases through the plan's existing host lease."""

from __future__ import annotations

from typing import Any
import time

from yoke_contracts.qa_case_starting_state import is_host_command

from yoke_core.domain.machine_qa_plan_case_execution import (
    MachinePlanCaseDispatchError,
    _dispatch,
    _waiting_case,
)
from yoke_core.domain.session_liveness_pump import SessionLivenessPump


class CommandPlanLiveness(SessionLivenessPump):
    """Refresh plan custody in the command's existing watcher tick."""

    def __init__(self, check_in):
        super().__init__()
        self._check_in = check_in
        self._last_plan_refresh = time.monotonic()

    def tick(self) -> bool:
        refreshed = super().tick()
        now = time.monotonic()
        if now - self._last_plan_refresh >= 60:
            self._check_in()
            self._last_plan_refresh = now
        return refreshed


def begin_command_host(
    case: dict[str, Any],
    *,
    execution_id: str,
    ordinal: int,
    target: Any,
    actor: Any,
    test_machine: str | None = None,
) -> dict[str, Any] | None:
    """Acquire the plan host or return the existing durable queue response.

    The case names no host: the server selects one by the case's OS and tags,
    or keeps the execution's bound lease, and *test_machine* is only the
    operator's per-run pin.
    """
    begun = _dispatch(
        "test_machine.plan_case.begin",
        target=target,
        actor=actor,
        payload={
            "execution_id": execution_id,
            "ordinal": ordinal,
            "requirement_id": int(case["requirement_id"]),
            **({"test_machine": test_machine} if test_machine else {}),
        },
        host_contact_possible=False,
    )
    if begun.get("state") == "waiting":
        return _waiting_case(
            begun, int(case["requirement_id"]), runner_id="worktree_run"
        )
    if begun.get("state") in {"blocked", "retained"}:
        return dict(begun["result"])
    if begun.get("state") != "ready" or not isinstance(begun.get("execution"), dict):
        raise ValueError("declared-host Command admission returned no lease contract")
    from yoke_core.domain.cloud_machine_power import power_dispatch_scope, power_on

    # The Command reaches the host itself, so its leased host must be up first.
    with power_dispatch_scope(actor=actor):
        power_on(str(begun["execution"]["project"]), begun["execution"]["settings"])
    reset_command_host(begun["execution"])
    return None


def reset_command_host(raw_contract: dict[str, Any]) -> dict[str, Any] | None:
    """Reach the baseline the admitted Command case declares, if it names one.

    Plan admission already put the case's ``host_baseline`` in the contract's
    ``baselines`` exactly as it does for a machine case; the Command runs on
    the operator's machine, so the reset happens here before it starts.
    """
    from yoke_core.domain.machine_qa_chain_restore import (
        STARTING_STATE_RESET_FAILED,
        baseline_receipt,
    )
    from yoke_core.domain.machine_qa_execution_contract import (
        HostControlExecutionContract,
    )
    from yoke_core.domain.machine_qa_host_control import (
        register_test_machine_host_control,
    )
    from yoke_core.domain.machine_qa_local_execution import _execution

    contract = HostControlExecutionContract.model_validate(raw_contract)
    if not contract.baselines:
        return None
    # Host control resolves through the OS-selecting factory, which a
    # Command run on the controller has not registered yet.
    register_test_machine_host_control()
    baseline = contract.baselines[0]
    reset = baseline_receipt(
        baseline,
        _execution(contract).reach_baseline,
        failure_code=STARTING_STATE_RESET_FAILED,
    )
    if not reset["ok"]:
        host = contract.settings["resource_name"]
        raise MachinePlanCaseDispatchError(
            f"Command case could not reset {host} to {baseline!r} before it "
            f"ran: {reset.get('diagnostic') or reset.get('evidence')}",
            error_code=reset.get("error_code") or STARTING_STATE_RESET_FAILED,
            recovery_hint=(
                f"repair {host} with `yoke test-machine verify --test-machine {host}`, then rerun the plan"
            ),
        )
    return reset


def command_liveness(requirement, check_in):
    """Supply plan heartbeats only for Commands declaring host custody."""
    if is_host_command(requirement):
        return {"liveness": CommandPlanLiveness(check_in)}
    return {}
