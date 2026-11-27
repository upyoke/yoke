"""An owner abort while a paired mission powers on keeps both hosts governed.

Feedback 98868: an owner abort during paired mission power-on made the
execution terminal while cloud startup still ran, and the runner then sent
heartbeat and ``mission.ready`` with released custody. Preparation now checks
in before the power call, so the admitted case's in-flight custody covers the
driver and its companion until the docket's restore receipt settles the
abort. These tests drive the registered admission, heartbeat, abort and
``mission.ready`` paths around the real credential-local preparation.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.agent_mission_host_access_test_support import (
    COMPANION,
    DRIVER,
)
from runtime.api.domain.agent_mission_qa_test_support import ACTOR, _request
from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    configure_test_machine,
    verify_fixture_host,
)
from runtime.api.domain.machine_qa_session_seed import seed_registered_qa_launch
from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import FunctionCallRequest, TargetRef
from yoke_contracts.machine_config.capability_secret_store import (
    store_test_machine_secret,
)
from yoke_core.domain.agent_mission_recording import handle_agent_mission_ready
from yoke_core.domain.coordination_claims import get_claim
from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin
from yoke_core.domain.handlers.qa_plan_execution import (
    handle_plan_execution_abort,
    handle_plan_execution_heartbeat,
)
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings
from yoke_core.domain.machine_qa_local_execution import prepare_agent_mission_contract
from yoke_core.domain.machine_qa_phase_heartbeat import MachineQaAborted
from yoke_core.domain.machine_reset_debt import owed_reset
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
)
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_host_leases import execution_host_leases
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

ITEM = 5765


def _call(handler: Any, function: str, execution_id: str, **payload: Any):
    return handler(
        FunctionCallRequest(
            function=function,
            actor=ACTOR,
            target=TargetRef(kind="item", item_id=ITEM),
            payload={"execution_id": execution_id, **payload},
        )
    )


@pytest.fixture
def paired(test_db: Any, tmp_path: Any, monkeypatch: Any):
    """A registered two-host mission admission that has not checked in yet."""
    configure_test_machine(test_db, tmp_path, monkeypatch)
    store_test_machine_secret(COMPANION, "ssh_private_key", "companion-test-key")
    replace_test_machine_settings(
        test_db,
        power_project="yoke",
        test_machine=COMPANION,
        settings={**TEST_MACHINE_SETTINGS, "resource_name": COMPANION, "os": "linux"},
        base_settings=None,
    )
    verify_fixture_host(test_db, COMPANION)
    plan = create_plan(test_db, project="yoke", slug="paired-power-on-mission")
    replace_plan_cases(
        test_db,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "paired-walk",
                "position": 1,
                "method_id": "exploratory-mission",
                "instructions": "Walk both declared hosts.",
                "expected_outcome": "Both hosts stay governed.",
                "method_config": {
                    "executor": "informed_subagent",
                    "test_machines": [{"os": "macos", "driver": True}, {"os": "linux"}],
                },
                "host_baselines": ["fresh-host"],
            }
        ],
    )
    insert_item(
        test_db, id=ITEM, title="Pair hosts", workflow_id="issue", status="implementing"
    )
    attach_plan_to_item(
        test_db, plan_id=int(plan["id"]), item_id=ITEM,
        transition_id="reviewing-implementation",
    )
    materialized = materialize_for_item(
        test_db, item_id=ITEM, transition_id="reviewing-implementation"
    )
    requirement = int(materialized["created_requirement_ids"][0])
    seed_registered_qa_launch(test_db, ACTOR.session_id)
    execution = begin_plan_execution(
        test_db,
        item_id=ITEM,
        transition_id="reviewing-implementation",
        actor_id=ACTOR.actor_id,
        session_id=ACTOR.session_id,
    )
    request = _request(
        "test_machine.plan_case.begin",
        item_id=ITEM,
        execution_id=execution["id"],
        requirement_id=requirement,
        ordinal=0,
    )
    begun = handle_plan_case_begin(request)
    assert begun.primary_success, begun.error
    assert begun.result_payload["state"] == "ready"
    hosts = FakeHostControl()
    register_host_control_factory(lambda _material: hosts)
    yield {
        "execution_id": str(execution["id"]),
        "request": request,
        "contract": begun.result_payload["execution"],
        "hosts": hosts,
    }
    clear_host_control_factory()


def _current(test_db: Any, execution_id: str) -> dict:
    current = lock_plan_execution(test_db, execution_id)
    test_db.rollback()
    return current


def _leases(test_db: Any, execution_id: str) -> dict[str, int]:
    execution = _current(test_db, execution_id)
    return {
        str(claim.target.scope["test_machine"]): int(claim.id)
        for claim in execution_host_leases(test_db, execution)
    }


def _beat(execution_id: str):
    """The runner's registered check-in, refused the way its dispatch refuses."""
    beat = _call(handle_plan_execution_heartbeat, "qa.plan_execution.heartbeat", execution_id)
    if not beat.primary_success:
        raise RuntimeError(f"{beat.error.code}: {beat.error.message}")
    return beat.result_payload


def _abort(execution_id: str):
    return _call(
        handle_plan_execution_abort,
        "qa.plan_execution.abort",
        execution_id,
        reason="owner stopped the run",
    )


def test_abort_during_paired_power_on_keeps_both_hosts_until_restore(
    test_db: Any, paired: dict, monkeypatch: Any
) -> None:
    execution_id = paired["execution_id"]
    leases = _leases(test_db, execution_id)
    assert set(leases) == {DRIVER, COMPANION}
    powered: list[str] = []
    raced: list[Any] = []

    def power_on(_project, settings, **_kwargs):
        powered.append(settings["resource_name"])
        # The owner aborts while the VM is still starting.
        raced.append(_abort(execution_id))
        current = _current(test_db, execution_id)
        assert current["state"] == "active"
        assert all(get_claim(test_db, lease).is_active for lease in leases.values())

    monkeypatch.setattr("yoke_core.domain.cloud_machine_power.power_on", power_on)
    prepared = prepare_agent_mission_contract(
        paired["contract"], progress_callback=lambda: _beat(execution_id)
    )

    assert powered == [DRIVER]
    assert not raced[0].primary_success
    assert "qa_abort_restore_pending" in raced[0].error.message
    preparation = prepared["preparation"]
    assert preparation["error_code"] == "qa_host_abort_requested"
    restore = preparation["evidence"]["starting_state_restore"]
    assert restore["restored"] is True and restore["baseline"] == "fresh-host"
    # Cancellation stopped preparation before any later host phase.
    assert "disk_preflight" not in preparation["evidence"]
    assert not preparation["evidence"]["scratch_created"]
    # Custody still covers both hosts until the docket's restore receipt lands.
    assert all(get_claim(test_db, lease).is_active for lease in leases.values())

    ready = handle_agent_mission_ready(
        paired["request"].model_copy(
            update={
                "function": "test_machine.mission.ready",
                "payload": {**paired["request"].payload, **prepared},
            }
        )
    )
    assert ready.primary_success, ready.error
    settled = _current(test_db, execution_id)
    assert settled["state"] == "aborted"  # No ordinary walk opened.
    assert settled["release_reason"].endswith("owner stopped the run")
    assert not any(get_claim(test_db, lease).is_active for lease in leases.values())
    # The untouched companion owes no new reset work.
    assert owed_reset(test_db, COMPANION) is None


def test_abort_settled_before_check_in_stops_before_power_on(
    test_db: Any, paired: dict, monkeypatch: Any
) -> None:
    execution_id = paired["execution_id"]
    leases = _leases(test_db, execution_id)
    aborted = _abort(execution_id)
    # An admitted case that has not begun host work aborts at once.
    assert aborted.primary_success, aborted.error
    assert aborted.result_payload["state"] == "aborted"
    powered: list[str] = []
    monkeypatch.setattr(
        "yoke_core.domain.cloud_machine_power.power_on",
        lambda _project, settings, **_k: powered.append(settings["resource_name"]),
    )
    with pytest.raises(RuntimeError, match="plan_execution_heartbeat_failed") as raised:
        prepare_agent_mission_contract(
            paired["contract"], progress_callback=lambda: _beat(execution_id)
        )
    assert raised.value.host_contact_possible is False
    assert powered == []
    assert paired["hosts"].commands == []
    # The owner's own stop keeps both hosts only as hold-overs for its next run.
    held = {row["test_machine"] for row in aborted.result_payload["test_machine_holdovers"]}
    assert held <= set(leases)
    assert owed_reset(test_db, DRIVER) is None
    assert owed_reset(test_db, COMPANION) is None


def test_recorded_cancellation_before_power_on_raises_untouched(
    paired: dict, monkeypatch: Any
) -> None:
    powered: list[str] = []
    monkeypatch.setattr(
        "yoke_core.domain.cloud_machine_power.power_on",
        lambda _project, settings, **_k: powered.append(settings["resource_name"]),
    )
    with pytest.raises(MachineQaAborted):
        prepare_agent_mission_contract(
            paired["contract"], progress_callback=lambda: {"abort_requested": True}
        )
    assert powered == []
