"""Walk-end always records cleanup custody loss, even after local failure."""

from types import SimpleNamespace

import pytest

from runtime.api.domain import test_agent_mission_cleanup as cleanup_support
from yoke_core.domain.agent_mission_recording import handle_agent_mission_access

RUN = cleanup_support.RUN
removed_mission = cleanup_support.removed_mission


@pytest.mark.parametrize("local_failure", [False, True])
def test_walk_end_always_finishes_its_cleanup_lease(
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
        outcome = handle_agent_mission_access(
            request.model_copy(update={"payload": kw["payload"]})
        )
        assert outcome.primary_success, outcome.error
        return SimpleNamespace(success=True)

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
            "--deployment-run-id",
            RUN,
            "--execution-id",
            request.payload["execution_id"],
            "--requirement-id",
            str(request.payload["requirement_id"]),
            "--run-id",
            str(request.payload["run_id"]),
        ]
    )
    assert code == (2 if local_failure else 0)
    assert len(sent) == 1
    assert sent[0]["payload"]["cleanup"] == "finish"
    assert sent[0]["payload"]["lease_id"] == original["lease_id"]
    from yoke_core.domain.machine_reset_debt import reset_owed

    assert reset_owed(test_db, original["settings"]["resource_name"]) == (
        "fresh-host" if local_failure else None
    )
    assert (sent[0]["payload"]["restore"] is None) == local_failure
    output = capsys.readouterr()
    assert "private-token" not in output.out + output.err
