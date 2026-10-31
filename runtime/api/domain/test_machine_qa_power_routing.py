"""A power refusal keeps host-contact evidence across the refresh boundary."""

from types import SimpleNamespace

import pytest

from runtime.api.domain.test_golden_harness_refresh import World, contract
from yoke_contracts.machine_qa_failures import SSH_UNAVAILABLE, HostControlLocalError
from yoke_core.domain import host_control_runner
from yoke_core.domain import machine_qa_plan_case_execution as machine
from yoke_core.domain.qa_plan_execution_continuation import continuation_abort_reason
from yoke_core.domain.qa_plan_execution_abort_reason import (
    abort_reason_code,
    PRE_HOST_ERROR_REASON,
    CASE_EXECUTION_ERROR_REASON,
)


def _power_error(code=SSH_UNAVAILABLE):
    return HostControlLocalError(
        code=code,
        phase="power",
        detail="no host contact",
        recovery_hint="fix the instance",
    )


def test_refresh_keeps_the_original_power_refusal(monkeypatch):
    world = World(monkeypatch, None)
    original = _power_error("test_machine_power_no_public_address")

    def fail(*_):
        raise original

    monkeypatch.setattr(host_control_runner, "resolve_contract_host_control", fail)
    with pytest.raises(HostControlLocalError) as caught:
        world.run(contract())
    assert caught.value is original
    wrapped = machine._case_failure(caught.value, phase="refresh")
    assert wrapped.error_code == original.code
    assert wrapped.recovery_hint == original.recovery_hint
    assert wrapped.host_contact_possible is False
    assert (
        abort_reason_code(continuation_abort_reason({}, wrapped))
        == PRE_HOST_ERROR_REASON
    )


@pytest.mark.parametrize("step", ["record read", "reset"])
def test_refresh_contact_flag_matches_step(monkeypatch, step):
    from yoke_harness import golden_harness_clis

    world = World(monkeypatch, None)

    def fail(*_):
        raise RuntimeError("broken")

    if step == "record read":
        monkeypatch.setattr(golden_harness_clis, "read_golden_harness_clis", fail)
    else:
        monkeypatch.setattr(world, "reset", fail)
        monkeypatch.setattr(
            host_control_runner,
            "resolve_contract_host_control",
            lambda _: (SimpleNamespace(reset_installer_test_host=fail), None),
        )
    with pytest.raises(machine.MachinePlanCaseDispatchError) as caught:
        world.run(contract())
    assert caught.value.host_contact_possible is (step != "record read")


def test_refresh_ssh_failure_submits_unstarted_case_and_waits(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.test_machine_qa_host_unreachable import (
        _plan,
        _begin,
        _submit,
        ACTOR,
        MACHINE,
    )
    from yoke_core.domain.qa_plan_execution_store import lock_plan_execution
    from yoke_core.domain.qa_host_health import host_unhealthy
    from yoke_core.domain.coordination_claims import active_claim
    from yoke_core.domain.machine_qa_capability import host_claim_target

    execution, case = _plan(test_db, tmp_path, monkeypatch)
    begun = _begin(execution, case)
    submissions = []

    def dispatch(function_id, **kwargs):
        if function_id.endswith("begin"):
            return begun
        submissions.append(kwargs["payload"])
        outcome = _submit(execution, case, kwargs["payload"])
        assert outcome.primary_success, outcome.error
        return outcome.result_payload

    def fail(*args, **kwargs):
        raise _power_error()

    monkeypatch.setattr(machine, "_dispatch", dispatch)
    monkeypatch.setattr(machine, "refreshed_case_contract", fail)
    result = machine.execute_plan_machine_case(
        case, execution_id=execution["id"], ordinal=0, actor=ACTOR
    )
    assert result["verdict"] == "waiting"
    row = submissions[0]["results"][0]
    assert row["error_code"] == SSH_UNAVAILABLE
    assert row["case_outcome"] == "blocked_on_precondition"
    assert row["evidence"]["case_started"] is False
    assert lock_plan_execution(test_db, execution["id"])["state"] == "waiting"
    assert host_unhealthy(test_db, MACHINE)["error_code"] == SSH_UNAVAILABLE
    assert active_claim(test_db, host_claim_target(MACHINE)) is None
    assert test_db.execute(
        "SELECT 1 FROM qa_test_machine_waits WHERE qa_plan_execution_id=%s AND state='waiting'",
        (execution["id"],),
    ).fetchone()


def test_material_factory_receives_the_rebound_host(monkeypatch):
    from yoke_core.domain import cloud_machine_power

    material = SimpleNamespace(project="p", settings={"host": "old"})
    # Use the real material dataclass shape with an existing deterministic fixture.
    from dataclasses import make_dataclass

    Material = make_dataclass("Material", [("project", str), ("settings", dict)])
    material = Material("p", {"host": "old"})
    seen = []
    monkeypatch.setattr(
        host_control_runner, "materialize_test_machine_contract", lambda _: material
    )
    monkeypatch.setattr(cloud_machine_power, "power_on", lambda *_: {"host": "new"})
    monkeypatch.setattr(
        host_control_runner, "_factory", lambda value: seen.append(value) or "control"
    )
    control, returned = host_control_runner.resolve_contract_host_control({})
    assert control == "control"
    assert returned.settings == seen[0].settings == {"host": "new"}


@pytest.mark.parametrize("flag", [True, None])
def test_possible_or_unknown_contact_uses_case_error_reason(flag):
    error = RuntimeError("failure")
    if flag is not None:
        error.host_contact_possible = flag
    assert (
        abort_reason_code(continuation_abort_reason({}, error))
        == CASE_EXECUTION_ERROR_REASON
    )


@pytest.mark.parametrize("uncertain", [False, True])
def test_pause_recovery_names_file_only_for_recorded_uncertainty(
    monkeypatch, uncertain
):
    import json
    from unittest.mock import Mock
    from yoke_core.domain import qa_plan_execution_reentry as reentry
    from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError

    monkeypatch.setattr(reentry, "require_execution_target", lambda _: None)
    checkpoint = {"resumed": True, "checkin_cursor": 0}
    if uncertain:
        checkpoint["attempts"] = [{"outcome": "timeout"}]
    execution = {
        "state": "active",
        "cursor_ordinal": 0,
        "roster": [{}],
        "release_reason": reentry.PAUSE_REASON + json.dumps(checkpoint),
    }
    with pytest.raises(QaPlanExecutionStateError) as caught:
        reentry.resume_execution(Mock(), execution)
    assert ("--recovery-file" in str(caught.value)) is uncertain
    if not uncertain:
        assert "yoke test-machine reset" in str(caught.value)


def test_cli_operation_uses_settings_returned_by_power(monkeypatch):
    from yoke_cli.commands.adapters import test_machine_operation as cli
    from yoke_core.domain import cloud_machine_power
    from yoke_contracts.api.function_call import FunctionCallResponse
    from yoke_harness import (
        golden_snapshot_retention,
        harness_cli_latest,
        test_machine_operations,
    )

    seen = []
    execution = {"project": "yoke", "settings": {"host": "old"}}
    monkeypatch.setattr(cli, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(cli, "build_actor", lambda **_: SimpleNamespace())
    monkeypatch.setattr(cli, "emit_response", lambda *_a, **_k: 0)
    monkeypatch.setattr(cloud_machine_power, "power_on", lambda *_: {"host": "new"})

    def dispatch(**kwargs):
        result = (
            {"execution": execution}
            if kwargs["function_id"].endswith("begin")
            else {"status": "verified"}
        )
        return FunctionCallResponse(
            success=True, function=kwargs["function_id"], version="v1", result=result
        )

    monkeypatch.setattr(cli, "call_dispatcher", dispatch)
    monkeypatch.setattr(
        test_machine_operations,
        "execute_host_operation_contract",
        lambda raw, **_: (
            seen.append(raw)
            or SimpleNamespace(payload={}, cleanup_artifacts=lambda: None)
        ),
    )
    monkeypatch.setattr(
        golden_snapshot_retention, "retain_after_verified_capture", lambda *_: None
    )
    monkeypatch.setattr(
        harness_cli_latest, "warn_capture_behind_latest", lambda *_: None
    )
    assert (
        cli._execute(
            operation="reset",
            project="yoke",
            test_machine="lab",
            baseline=None,
            destination=None,
            probes_document=None,
            session_id=None,
            json_mode=False,
        )
        == 0
    )
    assert seen[0]["settings"]["host"] == "new"
