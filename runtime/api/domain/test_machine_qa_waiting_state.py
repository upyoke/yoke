from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    OpenFixtureConnection,
    machine_case_request,
    materialize_installer_campaign,
)
from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE
from yoke_core.domain.coordination_claim_record import CoordinationClaim
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_core.domain.work_claim_targets import make_qa_admission_target
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.function_authz_scope import PROJECT, classify
from yoke_core.domain.handlers.machine_qa_case import handle_case_begin
from yoke_core.domain.machine_qa_case_execution import (
    execute_materialized_machine_case,
)
from yoke_core.domain.machine_qa_local_execution import (
    LocalHostControlSubmission,
)
from yoke_core.domain.machine_qa_execution import (
    MachineQaLeaseHeld,
    acquire_machine_qa_lease,
)
from yoke_core.domain.machine_qa_execution_protocol import (
    MachineQaProtocolLeaseHeld,
)
from yoke_core.domain.machine_qa_capability import replace_test_machine_settings


def test_held_lease_becomes_structured_machine_waiting_state() -> None:
    from runtime.api.domain.machine_qa_test_support import (
        make_conn,
        register_test_machine,
    )

    conn = make_conn()
    register_test_machine(conn)
    now = iso8601_now()
    seed_qa_session(conn, "holder-session")
    conn.execute(
        "INSERT INTO work_claims("
        "id,session_id,target_kind,scope,claimed_at,last_heartbeat,released_at"
        ") VALUES(9,'holder-session','qa_admission',?,?,?,NULL)",
        (make_qa_admission_target("mac-mini-lab").scope_json(), now, now),
    )

    with pytest.raises(MachineQaLeaseHeld) as caught:
        acquire_machine_qa_lease(
            conn,
            project="yoke",
            session_id="waiting-session",
        )

    waiting = caught.value.waiting_result()
    assert waiting.case_outcome == "waiting"
    assert waiting.verdict == "waiting"
    lease = waiting.evidence["lease"]
    assert lease["id"] == 9
    assert lease["holder_session_id"] == "session holder-session"
    assert lease["heartbeat_age_seconds"] >= 0
    assert "yoke coordination-claim release" in lease["wait_message"]


def test_case_begin_lease_contention_records_a_nonterminal_waiting_run(
    test_db,
    monkeypatch,
) -> None:
    rows = materialize_installer_campaign(test_db, item_id=4203)
    replace_test_machine_settings(
        test_db,
        project="yoke",
        settings=TEST_MACHINE_SETTINGS,
        base_settings=None,
    )
    requirement_id = int(
        next(row for row in rows if row["host_baseline"] == "fresh-host")["id"]
    )
    held = MachineQaProtocolLeaseHeld(
        lease=CoordinationClaim(
            id=17,
            target=make_qa_admission_target("mac-mini-lab"),
            session_id="holder-session",
            actor_id="2",
            claimed_at="2026-07-26T17:00:00Z",
            last_heartbeat="2026-07-26T17:01:00Z",
        ),
        machine="mac-mini-lab",
    )
    acquisitions = 0

    def acquire(_conn: Any, **_kwargs: Any):
        nonlocal acquisitions
        acquisitions += 1
        raise held

    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: OpenFixtureConnection(test_db),
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_execution_protocol.begin_host_control_execution",
        acquire,
    )

    outcome = handle_case_begin(machine_case_request(requirement_id))

    assert outcome.primary_success
    assert acquisitions == 1
    assert outcome.result_payload["state"] == "waiting"
    result = outcome.result_payload["result"]
    assert result["requirement_id"] == requirement_id
    assert result["case_outcome"] == "waiting"
    assert result["verdict"] is None
    assert result["lease_context"]["id"] == 17
    runs = test_db.execute(
        "SELECT verdict,case_outcome,completed_at,raw_result FROM qa_runs "
        "WHERE qa_requirement_id=%s",
        (requirement_id,),
    ).fetchall()
    assert len(runs) == 1
    assert runs[0]["verdict"] is None
    assert runs[0]["case_outcome"] == "waiting"
    assert runs[0]["completed_at"] is None
    assert json.loads(runs[0]["raw_result"])["evidence"]["lease"]["id"] == 17
    artifact_count = int(
        test_db.execute(
            "SELECT COUNT(*) FROM qa_artifacts a JOIN qa_runs r "
            "ON r.id=a.qa_run_id WHERE r.qa_requirement_id=%s",
            (requirement_id,),
        ).fetchone()[0]
    )
    assert artifact_count == 0


def test_single_case_begin_contention_preserves_rerun_identity(
    test_db,
    monkeypatch,
) -> None:
    rows = materialize_installer_campaign(test_db, item_id=4204)
    replace_test_machine_settings(
        test_db,
        project="yoke",
        settings=TEST_MACHINE_SETTINGS,
        base_settings=None,
    )
    target = next(row for row in rows if row["host_baseline"] == "shell-preconfigured")
    held = MachineQaProtocolLeaseHeld(
        lease=CoordinationClaim(
            id=18,
            target=make_qa_admission_target("mac-mini-lab"),
            session_id="holder-session",
            claimed_at="2026-07-26T17:02:00Z",
        ),
        machine="mac-mini-lab",
    )
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: OpenFixtureConnection(test_db),
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_execution_protocol.begin_host_control_execution",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(held),
    )
    request = machine_case_request(
        int(target["id"]),
        function="test_machine.case.begin",
    )

    outcome = handle_case_begin(request)

    assert outcome.primary_success
    assert outcome.result_payload["state"] == "waiting"
    result = outcome.result_payload["result"]
    assert result["requirement_id"] == int(target["id"])
    assert result["case_outcome"] == "waiting"
    assert result["verdict"] is None
    assert result["lease_context"]["id"] == 18


def test_waiting_case_cli_returns_retryable_exit_with_structured_result(
    monkeypatch,
    capsys,
) -> None:
    from yoke_core.domain import qa_case_execution_cli

    result = {
        "requirement_id": 41,
        "runner_id": "host_control",
        "verdict": None,
        "case_outcome": "waiting",
        "lease_context": {
            "id": 18,
            "holder_session_id": "holder-session",
        },
    }
    monkeypatch.setattr(
        qa_case_execution_cli,
        "execute_case",
        lambda *_args, **_kwargs: result,
    )

    exit_code = qa_case_execution_cli.run(["--requirement-id", "41"])

    assert exit_code == qa_case_execution_cli.WAITING_RETRY_EXIT
    assert exit_code != 0
    assert json.loads(capsys.readouterr().out) == result


def test_case_client_dispatches_begin_then_submit_for_its_requirement(
    monkeypatch,
) -> None:
    begin = SimpleNamespace(
        success=True,
        result={
            "state": "ready",
            "execution": {"server": "issued-contract"},
        },
        error=None,
    )
    submit = SimpleNamespace(
        success=True,
        result={"requirement_id": 41, "verdict": "pass"},
        error=None,
    )
    calls: list[dict[str, Any]] = []

    def dispatch(**kwargs: Any) -> SimpleNamespace:
        calls.append(dict(kwargs))
        return begin if len(calls) == 1 else submit

    monkeypatch.setattr(
        "yoke_core.domain.qa_composed_dispatch.call_qa_function",
        dispatch,
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_host_control.register_test_machine_host_control",
        lambda: None,
    )
    executed: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_local_execution.execute_machine_case_contract",
        lambda contract: (
            executed.append(contract)
            or LocalHostControlSubmission(
                payload={
                    "lease_id": 17,
                    "contract_digest": "digest",
                    "results": [],
                }
            )
        ),
    )
    result = execute_materialized_machine_case(
        {
            "requirement_id": 41,
            "runner_id": "host_control",
            "method_id": "machine-state-check",
            "project": "yoke",
            "plan_id": 999,
            "host_baseline": "client-forged-baseline",
            "starting_state": "baseline",
            "method_config": {"assertions": [{"argv": ["/usr/bin/true"]}]},
            "entry_surface": None,
            "required_completion": None,
        }
    )

    assert result == {"requirement_id": 41, "verdict": "pass"}
    assert executed == [{"server": "issued-contract"}]
    assert [call["function_id"] for call in calls] == [
        "test_machine.case.begin",
        "test_machine.case.submit",
    ]
    assert [call["target"].qa_requirement_id for call in calls] == [41, 41]
    # The client forwards nothing from its own snapshot: the server rereads
    # the case and issues the only contract the local process may run.
    assert calls[0]["payload"] == {}
    assert calls[1]["payload"] == {
        "lease_id": 17,
        "contract_digest": "digest",
        "results": [],
    }


def test_plan_case_two_phase_is_project_write_authorized() -> None:
    for function_id in (
        "test_machine.plan_case.begin",
        "test_machine.plan_case.submit",
    ):
        spec = classify(
            function_id,
            side_effects=True,
            project_permission=None,
        )
        assert (spec.scope, spec.permission_key) == (
            PROJECT,
            PERM_ITEMS_WRITE,
        )
