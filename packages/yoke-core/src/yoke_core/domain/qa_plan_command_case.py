"""Admit declared-host Command cases through the plan's existing host lease."""

from __future__ import annotations

from typing import Any
import time

from yoke_core.domain.machine_qa_plan_case_execution import _dispatch, _waiting_case
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
    case: dict[str, Any], *, execution_id: str, ordinal: int, target: Any, actor: Any
) -> dict[str, Any] | None:
    """Acquire the plan host or return the existing durable queue response."""
    begun = _dispatch(
        "test_machine.plan_case.begin",
        target=target,
        actor=actor,
        payload={
            "execution_id": execution_id,
            "ordinal": ordinal,
            "requirement_id": int(case["requirement_id"]),
            "test_machine": case["method_config"]["test_machine"],
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
    from yoke_core.domain.cloud_machine_power import power_on

    # The Command reaches the host itself, so its leased host must be up first.
    power_on(str(begun["execution"]["project"]), begun["execution"]["settings"])
    return None


def command_liveness(requirement, check_in):
    """Supply plan heartbeats only for Commands declaring host custody."""
    if requirement.get("runner_id") == "worktree_run" and (
        requirement.get("method_config") or {}
    ).get("test_machine"):
        return {"liveness": CommandPlanLiveness(check_in)}
    return {}
