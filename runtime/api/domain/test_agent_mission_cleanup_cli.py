"""Walk-end finishes cleanup custody once disposal settles, even after local failure."""

from types import SimpleNamespace

import pytest

from runtime.api.domain import test_agent_mission_cleanup as cleanup_support
from yoke_core.domain.agent_mission_project_disposal import (
    FUNCTION_ID as DISPOSE,
    handle_mission_project_disposal,
)
from yoke_core.domain.agent_mission_recording import handle_agent_mission_access

RUN = cleanup_support.RUN
removed_mission = cleanup_support.removed_mission


@pytest.mark.parametrize("local_failure", [False, True])
def test_walk_end_finishes_its_cleanup_lease_once_disposal_settles(
    monkeypatch, capsys, local_failure, removed_mission, test_db
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
        if local_failure:
            raise RuntimeError("private-token")
        return {
            "removed": True,
            "stale_owner_marker_removed": True,
            "starting_state_restore": {"restored": True, "baseline": "fresh-host"},
        }

    sent = []

    def dispatch(**kw):
        sent.append(kw)
        handler = (
            handle_mission_project_disposal
            if kw["function_id"] == DISPOSE
            else handle_agent_mission_access
        )
        outcome = handler(
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
        machine_qa_mission_walk,
        "execute_agent_mission_project_uninstall",
        lambda *args, **kwargs: {"host_projects": [], "error": None},
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
    assert code == (2 if local_failure else 0)
    # Disposal settles while the aborted execution is live, then cleanup
    # finishes and ends it, even after a local teardown failure.
    assert [call["function_id"] for call in sent] == [
        DISPOSE,
        "test_machine.mission.access",
    ]
    finish = sent[1]
    assert finish["payload"]["cleanup"] == "finish"
    assert finish["payload"]["lease_id"] == original["lease_id"]
    from yoke_core.domain.machine_reset_debt import reset_owed

    assert reset_owed(test_db, original["settings"]["resource_name"]) == (
        "fresh-host" if local_failure else None
    )
    assert (finish["payload"]["restore"] is None) == local_failure
    output = capsys.readouterr()
    assert "private-token" not in output.out + output.err


def test_unsettled_disposal_defers_cleanup_and_names_the_release(
    monkeypatch, capsys, removed_mission, test_db
):
    from yoke_core.domain import agent_mission_project_disposal
    from yoke_core.domain import agent_mission_walk_cli, machine_qa_mission_walk
    from yoke_core.domain import qa_composed_dispatch
    from yoke_core.domain.coordination_claims import get_claim

    request, _, original = removed_mission
    acquired = handle_agent_mission_access(request)
    assert acquired.primary_success, acquired.error
    contract = acquired.result_payload["execution"]

    def resolve(parsed, *, prog):
        parsed.cleanup_lease = True
        return contract

    blocked = "fixture_project_not_disposed: project cedar is blocked"
    sent = []
    monkeypatch.setattr(agent_mission_walk_cli, "resolve_mission_contract", resolve)
    monkeypatch.setattr(
        machine_qa_mission_walk,
        "execute_agent_mission_project_uninstall",
        lambda *args, **kwargs: {"host_projects": [], "error": None},
    )
    monkeypatch.setattr(
        machine_qa_mission_walk,
        "execute_agent_mission_walk_end",
        lambda *args, **kwargs: {
            "removed": True,
            "stale_owner_marker_removed": True,
            "starting_state_restore": {"restored": True, "baseline": "fresh-host"},
        },
    )
    monkeypatch.setattr(
        agent_mission_project_disposal,
        "request_project_disposal",
        lambda **kwargs: ([blocked], [], True),
    )
    monkeypatch.setattr(
        qa_composed_dispatch, "call_qa_function", lambda **kw: sent.append(kw)
    )

    code = agent_mission_walk_cli.run_end(
        ["--execution-id", request.payload["execution_id"]]
        + ["--requirement-id", str(request.payload["requirement_id"])]
        + ["--run-id", str(request.payload["run_id"])]
    )

    assert code == 3
    # The lease stays held so the execution is live for the rerun.
    assert sent == []
    assert get_claim(test_db, original["lease_id"]).is_active
    err = capsys.readouterr().err
    assert blocked in err and "mission_cleanup_deferred" in err
    assert f"yoke claims work release --claim-id {contract['lease_id']}" in err
