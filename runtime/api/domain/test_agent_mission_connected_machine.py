"""A mission records the Machine its connect registered, and walk-end retires it."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain import test_qa_fixture_project_disposal as disposal_support
from yoke_core.domain import agent_mission_connected_machine_cli as cli
from yoke_core.domain.agent_mission_connected_machine import (
    ConnectedMachineRefusal,
    connected_machine_notices,
    host_machine_id,
)
from yoke_core.domain.agent_mission_connected_machine_function import (
    FUNCTION_ID,
    handle_record_connected_machine,
)
from yoke_core.domain.db_helpers import utc_now
from yoke_core.domain.machine_registry import register_machine

OWN = "11111111-1111-4111-8111-111111111111"
TWIN = "22222222-2222-4222-8222-222222222222"
OLD = "33333333-3333-4333-8333-333333333333"
STRANGER = "44444444-4444-4444-8444-444444444444"
HOST_NAME = "qa-mac-mini"
_dispose = disposal_support._dispose
walking_mission = disposal_support.walking_mission
item_close_shares_the_fixture_connection = (
    disposal_support.item_close_shares_the_fixture_connection
)


def _actor(conn, actor_id: int) -> None:
    conn.execute(
        "INSERT INTO actors(id,kind,created_at) VALUES(%s,'human',%s) "
        "ON CONFLICT DO NOTHING",
        (actor_id, utc_now()),
    )


def _machine(conn, machine_id: str, *, owner: int = 1, age: timedelta = timedelta()):
    _actor(conn, owner)
    register_machine(
        conn,
        machine_id=machine_id,
        name=HOST_NAME,
        actor_id=owner,
        now=utc_now() - age,
    )


def _record(request, machine_id):
    return handle_record_connected_machine(
        request.model_copy(
            update={
                "function": FUNCTION_ID,
                "payload": {**request.payload, "machine_id": machine_id},
            }
        )
    )


def _docket(conn, run_id: int) -> dict:
    raw = conn.execute(
        "SELECT raw_result FROM qa_runs WHERE id=%s", (run_id,)
    ).fetchone()[0]
    conn.rollback()
    return json.loads(raw) if isinstance(raw, str) else raw


def _retired(conn, *machine_ids: str) -> dict[str, bool]:
    state = {
        machine_id: conn.execute(
            "SELECT retired_at FROM machines WHERE machine_id=%s", (machine_id,)
        ).fetchone()[0]
        is not None
        for machine_id in machine_ids
    }
    conn.rollback()
    return state


def test_connect_records_the_registered_machine_on_the_docket(test_db, walking_mission):
    _machine(test_db, OWN)

    outcome = _record(walking_mission, OWN)

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["machine_id"] == OWN
    assert outcome.result_payload["launch_hint"].endswith(f"--machine {OWN}")
    recorded = _docket(test_db, walking_mission.payload["run_id"])["connected_machine"]
    assert recorded["machine_id"] == OWN and recorded["name"] == HOST_NAME
    assert set(recorded) == {"machine_id", "name", "registered_at", "recorded_at"}
    assert _record(walking_mission, OWN).result_payload["connected_machine"] == (
        recorded
    )


@pytest.mark.parametrize(
    ("machine_id", "code"),
    [
        (None, "connected_machine_absent"),
        (STRANGER, "connected_machine_unregistered"),
        (OLD, "connected_machine_predates_mission"),
    ],
)
def test_a_machine_this_mission_did_not_create_is_refused(
    test_db, walking_mission, machine_id, code
):
    _machine(test_db, OLD, age=timedelta(days=3))

    outcome = _record(walking_mission, machine_id)

    assert not outcome.primary_success
    assert outcome.error.code == code
    assert "Recovery:" in outcome.error.message
    docket = _docket(test_db, walking_mission.payload["run_id"])
    assert "connected_machine" not in docket


def test_host_config_names_the_machine_id():
    control = FakeHostControl()
    path = f"{control.home}/.yoke/config.json"
    control.files[path] = json.dumps({"machine_id": OWN, "projects": {}})
    assert host_machine_id(control) == OWN
    control.files[path] = json.dumps({"projects": {}})
    assert host_machine_id(control) is None
    control.files[path] = "{not json"
    with pytest.raises(ConnectedMachineRefusal, match="config_unreadable"):
        host_machine_id(control)


def test_command_prints_the_machine_id_and_launch_hint(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "resolve_mission_contract", lambda p, *, prog: {})
    monkeypatch.setattr(cli, "_host_machine_id", lambda contract: OWN)

    def call(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            success=True,
            result={"machine_id": OWN, "launch_hint": f"... --machine {OWN}"},
            error=None,
        )

    monkeypatch.setattr("yoke_core.domain.qa_composed_dispatch.call_qa_function", call)
    flags = ["--item", "ITEM-4550", "--execution-id", "E1", "--requirement-id", "7"]

    assert cli.main([*flags, "--run-id", "991"]) == 0

    printed = json.loads(capsys.readouterr().out)
    assert printed["machine_id"] == OWN and OWN in printed["launch_hint"]
    assert calls[0]["function_id"] == FUNCTION_ID
    assert calls[0]["payload"]["machine_id"] == OWN
    assert calls[0]["payload"]["run_id"] == 991


def test_command_reads_a_declared_companion_through_mission_access(monkeypatch):
    calls, read = [], []
    companion = {"operation": "host_command", "lease_id": 8}

    def call(**kwargs):
        calls.append(kwargs)
        result = (
            {"execution": companion}
            if kwargs["function_id"] == "test_machine.mission.access"
            else {"machine_id": OWN, "launch_hint": f"--machine {OWN}"}
        )
        return SimpleNamespace(success=True, result=result, error=None)

    monkeypatch.setattr("yoke_core.domain.qa_composed_dispatch.call_qa_function", call)
    monkeypatch.setattr(
        cli, "_host_machine_id", lambda contract: read.append(contract) or OWN
    )
    flags = ["--item", "ITEM-4550", "--execution-id", "E1", "--requirement-id", "7"]

    assert cli.main([*flags, "--run-id", "991", "--test-machine", "linux-peer"]) == 0

    assert calls[0]["payload"]["test_machine"] == "linux-peer"
    assert read == [companion]
    assert calls[1]["function_id"] == FUNCTION_ID


def test_walk_end_retires_only_the_missions_own_machine(test_db, walking_mission):
    _machine(test_db, OWN)
    _machine(test_db, TWIN)
    _machine(test_db, OLD, age=timedelta(days=3))
    assert _record(walking_mission, OWN).primary_success

    outcome = _dispose(walking_mission, [])

    assert outcome.primary_success, outcome.error
    retirement = outcome.result_payload["connected_machine_retirement"]
    assert retirement == {"machine_id": OWN, "outcome": "retired", "recovery": None}
    assert _retired(test_db, OWN, TWIN, OLD) == {OWN: True, TWIN: False, OLD: False}
    rerun = _dispose(walking_mission, [])
    assert rerun.result_payload["connected_machine_retirement"]["outcome"] == (
        "already_retired"
    )


def _dispose_with_host(request, machine_id):
    return _dispose(
        request.model_copy(
            update={"payload": {**request.payload, "connected_machine_id": machine_id}}
        ),
        [],
    )


def test_walk_end_records_an_unrecorded_host_machine_then_retires_it(
    test_db, walking_mission
):
    _machine(test_db, OWN)
    _machine(test_db, TWIN)

    outcome = _dispose_with_host(walking_mission, OWN)

    assert outcome.result_payload["connected_machine_retirement"]["outcome"] == (
        "retired"
    )
    assert _retired(test_db, OWN, TWIN) == {OWN: True, TWIN: False}


def test_walk_end_never_retires_a_machine_older_than_the_mission(
    test_db, walking_mission
):
    _machine(test_db, OLD, age=timedelta(days=3))

    outcome = _dispose_with_host(walking_mission, OLD)

    assert outcome.result_payload["connected_machine_retirement"] == {
        "machine_id": OLD,
        "outcome": "skipped_predates_mission",
        "recovery": None,
    }
    assert _retired(test_db, OLD) == {OLD: False}
    assert _dispose_with_host(walking_mission, None).result_payload[
        "connected_machine_retirement"
    ]["outcome"] == ("none_recorded")


def test_a_forbidden_retirement_names_the_owners_recovery(
    test_db, walking_mission, monkeypatch
):
    monkeypatch.setattr(
        "yoke_core.domain.handlers.machine_registry._is_admin", lambda *a: False
    )
    _machine(test_db, OWN, owner=2)

    outcome = _dispose_with_host(walking_mission, OWN)

    assert outcome.primary_success, outcome.error
    retirement = outcome.result_payload["connected_machine_retirement"]
    assert retirement["outcome"] == "forbidden"
    assert retirement["recovery"] == (
        f"the Machine's owner runs `yoke machine retire {OWN} --confirm`"
    )
    assert _retired(test_db, OWN) == {OWN: False}
    (notice,) = connected_machine_notices(outcome.result_payload)
    assert notice.startswith(f"connected_machine_not_retired: Machine {OWN}")
    assert f"yoke machine retire {OWN} --confirm" in notice


def test_walk_end_disposal_request_carries_the_machine_and_names_its_recovery(
    monkeypatch,
):
    from yoke_contracts.api.function_call import ActorContext, TargetRef
    from yoke_core.domain.agent_mission_project_disposal import (
        request_project_disposal,
    )

    sent = []
    retirement = {
        "machine_id": OWN,
        "outcome": "forbidden",
        "recovery": f"the Machine's owner runs `yoke machine retire {OWN} --confirm`",
    }

    def call(**kwargs):
        sent.append(kwargs["payload"])
        return SimpleNamespace(
            success=True,
            result={"unsettled": [], "connected_machine_retirement": retirement},
            error=None,
        )

    monkeypatch.setattr("yoke_core.domain.qa_composed_dispatch.call_qa_function", call)

    failures, notices, recorded = request_project_disposal(
        target=TargetRef(kind="global", project_id="yoke"),
        actor=ActorContext(actor_id="1", session_id="s"),
        execution_id="E1",
        requirement_id=7,
        run_id=991,
        host_projects=[],
        connected_machine_id=OWN,
    )

    assert (failures, recorded) == ([], True)
    assert sent[0]["connected_machine_id"] == OWN
    assert notices == connected_machine_notices(
        {"connected_machine_retirement": retirement}
    )
