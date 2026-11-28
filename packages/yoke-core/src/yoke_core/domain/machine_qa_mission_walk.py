"""Credential-local start and end of one exploratory mission walk.

A mission is walked after its plan's other cases have run, so the Test
Machine it needs is put in place when the walk begins, not when the plan
recorded its docket: ``walk-start`` resets to the mission's declared
baseline, restores its declared OS packages and stages its scratch.
``walk-end`` removes the scratch, restores the declared baseline, and
records that restore on the mission's run. Windows retries failed scratch
removal after a successful restore can release its locks.
"""

from __future__ import annotations

import base64
import json
from typing import Any

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_core.domain.agent_mission_preparation import prepare_mission
from yoke_core.domain.machine_qa_chain_restore import (
    STARTING_STATE_RESTORE,
    restore_chain_start,
)
from yoke_core.domain.machine_qa_local_execution import _execution, _mission_contract
from yoke_core.domain.machine_qa_mission_scratch import (
    create_mission_scratch,
    remove_mission_scratch,
)
from yoke_contracts.machine_qa_result_safety import redact_machine_qa_value
from yoke_core.domain.machine_qa_submission_artifacts import ensure_secret_free_result


def execute_agent_mission_walk_start(raw_contract: dict[str, Any]) -> dict[str, Any]:
    """Put the Test Machine in the mission's declared starting state."""
    return prepare_mission(
        _mission_contract(raw_contract),
        execution_factory=_execution,
        scratch_factory=create_mission_scratch,
        refuse_existing_scratch=True,
    )


def execute_agent_mission_walk_end(
    raw_contract: dict[str, Any],
    *,
    timeout_seconds: int = 60,
    restore_proven: bool = False,
) -> dict[str, Any]:
    """Remove secret staging and restore the declared starting state.

    ``restore_proven`` means the server already holds this lease's verified
    post-cancellation reset to the declared baseline; walk-end then removes
    the scratch only and leaves ``starting_state_restore`` empty, so the
    server's own proof settles cleanup instead of a second restore.
    """
    contract = _mission_contract(raw_contract)
    execution = _execution(contract)
    scratch = {
        "execution_id": str(contract.plan_execution_id),
        "timeout_seconds": timeout_seconds,
    }
    teardown = remove_mission_scratch(execution.control, **scratch)
    restore = None if restore_proven else restore_chain_start(
        contract.cases[0],
        execution.reach_baseline,
        test_machine=contract.settings["resource_name"],
    )
    # Native Windows restore can stop processes holding the scratch open.
    if not teardown["removed"] and restore and restore["restored"] and contract.settings.get("os") == "windows":
        teardown = remove_mission_scratch(execution.control, **scratch)
    teardown[STARTING_STATE_RESTORE] = restore
    redacted = redact_machine_qa_value(
        teardown,
        tuple(execution.material.secrets.values()),
    )
    ensure_secret_free_result(redacted)
    return redacted


def mission_walk_unfinished(raw_contract: dict[str, Any]) -> bool:
    """Whether the mission's scratch shows its walk never ran walk-end."""
    from yoke_core.domain.machine_qa_mission_scratch import mission_scratch_present

    contract = _mission_contract(raw_contract)
    return mission_scratch_present(
        _execution(contract).control,
        execution_id=str(contract.plan_execution_id),
    )


def record_mission_restore(
    *,
    requirement_id: int,
    run_id: int,
    restore: dict[str, Any],
    actor: ActorContext,
) -> str | None:
    """Attach the restore receipt to the mission's run; return why not."""
    from yoke_core.domain.qa_composed_dispatch import call_qa_function

    response = call_qa_function(
        function_id="qa.artifact.add",
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload={
            "run_id": int(run_id),
            "artifact_type": STARTING_STATE_RESTORE,
            "content_base64": base64.b64encode(
                json.dumps(restore, sort_keys=True).encode("utf-8")
            ).decode("ascii"),
            "filename": "starting-state-restore.json",
            "content_type": "application/json",
        },
        actor=actor,
    )
    if response.success:
        return None
    error = response.error
    return f"{error.code}: {error.message}" if error else "qa.artifact.add failed"


__all__ = [
    "mission_walk_unfinished",
    "execute_agent_mission_walk_end",
    "execute_agent_mission_walk_start",
    "record_mission_restore",
]
