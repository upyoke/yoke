"""The releasing CLI settles reset debt through the normal host operation."""

from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_operation_test_support import ACTOR, MACHINE
from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
from runtime.api.domain.machine_reset_debt_test_support import _debt
from runtime.api.fixtures.actor_roles import seed_org_role, seed_project_role
from yoke_cli.commands.adapters import test_machine_operation
from yoke_cli.transport.settled_response import settle_response
from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_core.domain import cloud_machine_power, machine_idle_stop
from yoke_core.domain.actor_permissions import ROLE_ADMIN, ROLE_OWNER, seed_roles_and_permissions
from yoke_core.domain.coordination_claims import acquire, active_claim
from yoke_core.domain.machine_reset_debt import owed_reset
from yoke_core.domain.steering_fleet_report_test_machines import (
    read_reset_debts,
    reset_debt_lines,
)
from yoke_core.domain.work_claim_targets import make_qa_admission_target
from yoke_core.domain.yoke_function_dispatch import dispatch


@pytest.fixture
def configured_host(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    seed_roles_and_permissions(test_db)
    seed_org_role(test_db, org_id=1, actor_id=1, role_name=ROLE_ADMIN, granted_by_actor_id=1)
    seed_project_role(test_db, project_id=1, actor_id=1, role_name=ROLE_OWNER, granted_by_actor_id=1)
    return make_qa_admission_target(MACHINE)


def _call(function_id, *, actor=ACTOR, payload):
    return dispatch(
        FunctionCallRequest(
            function=function_id, actor=actor,
            target=TargetRef(kind="global"), payload=payload,
        ),
        ambient_session_id=actor.session_id,
    )


@pytest.mark.parametrize("outcome", ["verified", "proof_error", "local_error", "no_debt"])
def test_release_settles_one_owed_reset(test_db, configured_host, monkeypatch, capsys, outcome):
    target = configured_host
    if outcome != "no_debt":
        _debt(test_db)
    lease = acquire(test_db, target, ACTOR.session_id)
    test_db.execute(
        "UPDATE test_machines SET yoke_started_at=now() WHERE name=%s", (MACHINE,)
    )
    test_db.commit()
    notices = []
    steps = []

    def stop(machines, *, actor, relay_env):
        assert machines == [{"test_machine": MACHINE, "power_project": "yoke"}]
        assert actor == ACTOR and relay_env == "fixture"
        assert active_claim(test_db, target) is None
        steps.append("stop")
        test_db.execute("UPDATE test_machines SET yoke_started_at=NULL WHERE name=%s", (MACHINE,))
        test_db.commit()
        # The idle stop's own release can carry the same reset notice.
        settle_response(
            FunctionCallResponse(
                success=True, function="claims.coordination_claim.release", version="v1",
                test_machines_to_reset=notices[0] if notices else [],
            ),
            actor=actor, relay_env=relay_env,
        )

    def nested_call(*, function_id, target, actor, relay_env, payload):
        assert target.kind == "global" and actor == ACTOR and relay_env == "fixture"
        steps.append(function_id.rsplit(".", 1)[-1])
        response = _call(function_id, actor=actor, payload=payload)
        if function_id == "test_machine.operation.begin":
            assert response.success, response.error
        return settle_response(response, actor=actor, relay_env=relay_env)

    def power_on(*args):
        assert active_claim(test_db, target).id != lease.id
        assert steps == ["stop", "begin"]
        steps.append("power_on")
        test_db.execute("UPDATE test_machines SET yoke_started_at=now() WHERE name=%s", (MACHINE,))
        test_db.commit()

    def execute(execution, *, probes_document):
        steps.append("reset")
        assert execution["baselines"] == ["fresh-host"]
        if outcome == "local_error":
            raise HostControlLocalError(
                code="windows_console_not_ready", phase="reset",
                detail="Console is unavailable", recovery_hint="Check the console.",
            )
        return SimpleNamespace(
            cleanup_artifacts=lambda: None,
            payload={
                "operation": "reset", "lease_id": execution["lease_id"],
                "contract_digest": execution["contract_digest"],
                "status": "verified" if outcome == "verified" else "error",
                "checks": [{"name": "fresh-host", "ok": outcome == "verified"}],
                "error_code": None if outcome == "verified" else "windows_console_not_ready",
            },
        )

    monkeypatch.setattr(machine_idle_stop, "stop_released", stop)
    monkeypatch.setattr(cloud_machine_power, "power_on", power_on)
    monkeypatch.setattr(test_machine_operation, "call_dispatcher", nested_call)
    monkeypatch.setattr("yoke_harness.test_machine_operations.execute_host_operation_contract", execute)
    response = _call(
        "claims.coordination_claim.release",
        payload={"claim_id": lease.id, "reason": "walk complete"},
    )
    assert response.success, response.error
    notices.append(response.test_machines_to_reset)
    assert notices[0] == (
        [] if outcome == "no_debt" else [{"test_machine": MACHINE, "baseline": "fresh-host"}]
    )
    assert settle_response(response, actor=ACTOR, relay_env="fixture") == response
    assert active_claim(test_db, target) is None
    stderr = capsys.readouterr().err
    debt = owed_reset(test_db, MACHINE)
    report = reset_debt_lines(read_reset_debts(test_db, 1))
    if outcome == "no_debt":
        assert steps == ["stop"]
    else:
        settlement = "abort" if outcome == "local_error" else "submit"
        assert steps == ["stop", "begin", "power_on", "reset", settlement, "stop"]
    if outcome in ("no_debt", "verified"):
        assert debt is None and not report and not stderr
    else:
        code = "machine_needs_repair" if outcome == "local_error" else "windows_console_not_ready"
        assert debt.attempt["status"] == "error"
        assert debt.attempt["error_code"] == code
        assert report == [
            f"Test Machine {MACHINE}: machine_needs_repair: automatic reset failed ({code}); "
            f"run `yoke test-machine reset --test-machine {MACHINE} --baseline fresh-host`"
        ]
        assert "windows_console_not_ready" in stderr
        assert f"yoke test-machine reset --test-machine {MACHINE} --baseline fresh-host" in stderr

    later = acquire(test_db, target, ACTOR.session_id)
    response = _call(
        "claims.coordination_claim.release",
        payload={"claim_id": later.id, "reason": "second release"},
    )
    assert response.success and not response.test_machines_to_reset


def test_reset_begin_rechecks_debt_and_host_custody(test_db, configured_host):
    target = configured_host
    payload = {
        "test_machine": MACHINE, "operation": "reset",
        "baseline": "fresh-host", "automatic_reset": True,
    }
    assert "no longer owed" in _call("test_machine.operation.begin", payload=payload).error.message
    _debt(test_db)
    holder = acquire(test_db, target, ACTOR.session_id)
    response = _call("test_machine.operation.begin", payload=payload)
    assert not response.success and "current holder" in response.error.message
    assert active_claim(test_db, target).id == holder.id


def test_release_with_waiter_does_not_offer_automatic_reset(test_db, configured_host, monkeypatch):
    from runtime.api.domain.machine_qa_session_seed import seed_qa_session
    from runtime.api.domain.qa_host_turns_test_support import _execution_wait, _notices

    target = configured_host
    waiter = "waiting-qa-session"
    seed_qa_session(test_db, waiter, messageable=True)
    _notices(monkeypatch)
    lease = acquire(test_db, target, ACTOR.session_id)
    _debt(test_db)
    _execution_wait(test_db, waiter, test_machine=MACHINE)

    response = _call(
        "claims.coordination_claim.release",
        payload={"claim_id": lease.id, "reason": "walk complete"},
    )

    assert response.success, response.error
    assert not response.test_machines_to_stop and not response.test_machines_to_reset
    assert active_claim(test_db, target).session_id == waiter
    assert owed_reset(test_db, MACHINE).attempt is None
