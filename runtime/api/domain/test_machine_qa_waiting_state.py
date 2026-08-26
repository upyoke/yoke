from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    TEST_MACHINE_SETTINGS,
    OpenFixtureConnection,
    baseline_group_request,
    materialize_installer_campaign,
)
from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE
from yoke_core.domain.coordination_claim_record import CoordinationClaim
from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from yoke_core.domain.work_claim_targets import make_qa_admission_target
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.function_authz_scope import PROJECT, classify
from yoke_core.domain.handlers.machine_qa_case import (
    handle_baseline_group_begin,
    handle_case_begin,
)
from yoke_core.domain.machine_qa_case_execution import (
    execute_materialized_machine_baseline_group,
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
from yoke_core.domain.host_control_runner import (
    TestMachineMaterial as MachineMaterial,
)


def test_held_lease_becomes_structured_machine_waiting_state(
    monkeypatch,
) -> None:
    from runtime.api.domain.machine_qa_test_support import (
        FakeHostControl,
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
    material = MachineMaterial(
        project_id=1,
        project="yoke",
        settings={
            "resource_name": "mac-mini-lab",
            "host": "test-mac.local",
            "user": "yoke-test",
            "operating_notes": "",
        },
        secrets={},
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_execution.resolve_host_control",
        lambda _conn, *, project: (FakeHostControl(), material),
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


def test_group_begin_lease_contention_records_nonterminal_waiting_cases(
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
    fresh = [row for row in rows if row["host_baseline"] == "fresh-host"]
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

    outcome = handle_baseline_group_begin(
        baseline_group_request(
            int(fresh[0]["id"]),
            function="test_machine.baseline_group.begin",
        )
    )

    assert outcome.primary_success
    assert acquisitions == 1
    assert outcome.result_payload["state"] == "waiting"
    result_payload = outcome.result_payload["result"]
    assert result_payload["baseline_ok"] is None
    expected_ids = [int(row["id"]) for row in fresh]
    assert result_payload["requirement_ids"] == expected_ids
    assert [
        result["requirement_id"] for result in result_payload["results"]
    ] == expected_ids
    assert all(
        result["case_outcome"] == "waiting"
        and result["verdict"] is None
        and result["evidence_count"] == 0
        and result["lease_context"]["id"] == 17
        for result in result_payload["results"]
    )
    runs = test_db.execute(
        "SELECT qa_requirement_id,verdict,case_outcome,completed_at,"
        "raw_result FROM qa_runs WHERE qa_requirement_id=ANY(%s) "
        "ORDER BY qa_requirement_id",
        (expected_ids,),
    ).fetchall()
    assert [int(row["qa_requirement_id"]) for row in runs] == expected_ids
    assert all(
        row["verdict"] is None
        and row["case_outcome"] == "waiting"
        and row["completed_at"] is None
        and json.loads(row["raw_result"])["evidence"]["lease"]["id"] == 17
        for row in runs
    )
    artifact_count = int(
        test_db.execute(
            "SELECT COUNT(*) FROM qa_artifacts a JOIN qa_runs r "
            "ON r.id=a.qa_run_id WHERE r.qa_requirement_id=ANY(%s)",
            (expected_ids,),
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
    request = baseline_group_request(
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


def test_baseline_group_client_dispatches_begin_then_submit_for_anchor(
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
        result={
            "anchor_requirement_id": 41,
            "requirement_ids": [41, 42],
        },
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
        "yoke_core.domain.ssh_mac_host_control.register_ssh_mac_host_control",
        lambda: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_local_execution.execute_machine_case_contract",
        lambda contract: LocalHostControlSubmission(
            payload={
                "lease_id": 17,
                "contract_digest": "digest",
                "baseline_ok": True,
                "results": [],
            }
        ),
    )
    result = execute_materialized_machine_baseline_group(
        {
            "requirement_id": 41,
            "runner_id": "host_control",
            "method_id": "machine-state-check",
            "project": "yoke",
            "plan_id": 999,
            "host_baseline": "client-forged-baseline",
            "method_config": {"assertions": [{"argv": ["/usr/bin/true"]}]},
            "entry_surface": None,
            "required_completion": None,
            "requirement_ids": [41, 999],
        }
    )

    assert result["requirement_ids"] == [41, 42]
    assert [call["function_id"] for call in calls] == [
        "test_machine.baseline_group.begin",
        "test_machine.baseline_group.submit",
    ]
    assert [call["target"].qa_requirement_id for call in calls] == [41, 41]
    assert calls[0]["payload"] == {}
    assert calls[1]["payload"] == {
        "lease_id": 17,
        "contract_digest": "digest",
        "baseline_ok": True,
        "results": [],
    }


def test_baseline_group_two_phase_is_project_write_authorized() -> None:
    for function_id in (
        "test_machine.baseline_group.begin",
        "test_machine.baseline_group.submit",
        "test_machine.baseline_group.abort",
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
