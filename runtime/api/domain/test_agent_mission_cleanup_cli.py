"""Walk-end retains cleanup custody when scratch removal fails."""

from types import SimpleNamespace

import pytest
from yoke_contracts.machine_qa_failures import HostControlLocalError

from runtime.api.domain import (
    agent_mission_cleanup_test_support as cleanup_support,
)
from yoke_core.domain.agent_mission_recording import handle_agent_mission_access

RUN = cleanup_support.RUN
removed_mission = cleanup_support.removed_mission


@pytest.mark.parametrize("failure", [None, "teardown", "typed", "scratch"])
def test_walk_end_keeps_the_cleanup_lease_on_scratch_failure(
    monkeypatch, capsys, failure, removed_mission, test_db
):
    from yoke_core.domain import agent_mission_walk_cli, machine_qa_mission_walk
    from yoke_core.domain import qa_composed_dispatch

    request, _, original = removed_mission
    acquired = handle_agent_mission_access(request)
    assert acquired.primary_success, acquired.error

    def resolve(parsed, *, prog):
        parsed.cleanup_lease = True
        return acquired.result_payload["execution"]

    def teardown(*args, **kwargs):
        if failure == "teardown":
            raise RuntimeError("private-token")
        if failure == "typed":
            raise HostControlLocalError(
                code="baseline_restore_failed",
                phase="baseline_restore",
                detail="private-token",
                recovery_hint="Run `yoke test-machine reset --project yoke`.",
                stderr="private-token",
            )
        return {
            "removed": failure != "scratch",
            "scratch_path": r"C:\Users\tester\AppData\Local\YokeQaMission\walk",
            "removal_exit_code": int(failure == "scratch"),
            "removal_stderr": "Access is denied" if failure == "scratch" else "",
            "stale_owner_marker_removed": True,
            "starting_state_restore": {"restored": True, "baseline": "fresh-host"},
        }

    sent = []

    def dispatch(**kw):
        sent.append(kw)
        outcome = handle_agent_mission_access(
            request.model_copy(
                update={"function": kw["function_id"], "payload": kw["payload"]}
            )
        )
        assert outcome.primary_success, outcome.error
        return SimpleNamespace(success=True, result=outcome.result_payload)

    monkeypatch.setattr(agent_mission_walk_cli, "resolve_mission_contract", resolve)
    monkeypatch.setattr(
        machine_qa_mission_walk, "execute_agent_mission_walk_end", teardown
    )
    monkeypatch.setattr(
        qa_composed_dispatch,
        "call_qa_function",
        dispatch,
    )
    code = agent_mission_walk_cli.run_end(
        [
            "--execution-id",
            request.payload["execution_id"],
            "--requirement-id",
            str(request.payload["requirement_id"]),
            "--run-id",
            str(request.payload["run_id"]),
        ]
    )
    from yoke_core.domain.coordination_claims import get_claim

    assert code == {None: 0, "teardown": 2, "typed": 2, "scratch": 3}[failure]
    assert get_claim(test_db, original["lease_id"]).is_active is (failure == "scratch")
    if failure == "scratch":
        assert sent == []
        err = capsys.readouterr().err
        assert "mission_scratch_not_removed" in err
        assert "removal exited 1 (Access is denied)" in err
        return

    # An unexpected teardown exception still settles with reset debt.
    assert [call["function_id"] for call in sent] == ["test_machine.mission.access"]
    finish = sent[0]
    assert finish["payload"]["cleanup"] == "finish"
    assert finish["payload"]["lease_id"] == original["lease_id"]
    from yoke_core.domain.machine_reset_debt import reset_owed

    assert reset_owed(test_db, original["settings"]["resource_name"]) == (
        None if failure is None else "fresh-host"
    )
    assert (finish["payload"]["restore"] is None) == (failure is not None)
    output = capsys.readouterr()
    assert "private-token" not in output.out + output.err
