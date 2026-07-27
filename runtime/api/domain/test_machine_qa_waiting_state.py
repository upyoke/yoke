from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    OpenFixtureConnection,
    baseline_group_request,
    materialize_installer_campaign,
)
from yoke_core.domain.actor_permissions import PERM_ITEMS_WRITE
from yoke_core.domain.coordination_leases import Lease
from yoke_core.domain.function_authz_scope import PROJECT, classify
from yoke_core.domain.handlers.test_machine_case import (
    handle_baseline_group_execute,
    handle_case_execute,
)
from yoke_core.domain.host_control_executor import (
    TestMachineMaterial as MachineMaterial,
)
from yoke_core.domain.machine_qa_case_execution import (
    execute_materialized_machine_baseline_group,
)
from yoke_core.domain.machine_qa_execution import (
    MachineQaLeaseHeld,
    acquire_machine_qa_lease,
)


def test_held_lease_becomes_structured_machine_waiting_state(
    monkeypatch,
) -> None:
    from runtime.api.domain.machine_qa_test_support import (
        FakeHostControl,
        make_conn,
    )

    conn = make_conn()
    conn.execute(
        "INSERT INTO coordination_leases("
        "id,project_id,lease_key,session_id,actor_id,"
        "acquired_at,heartbeat_at,released_at"
        ") VALUES(9,1,'QA_HOST:mac-mini-lab','holder-session','2',"
        "'2026-07-26T17:00:00Z','2026-07-26T17:01:00Z',NULL)"
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
            actor_id="3",
        )

    waiting = caught.value.waiting_result()
    assert waiting.case_outcome == "waiting"
    assert waiting.verdict == "waiting"
    assert waiting.evidence == {
        "executor_id": "host_control",
        "machine": "mac-mini-lab",
        "case_started": False,
        "lease": {
            "id": 9,
            "key": "QA_HOST:mac-mini-lab",
            "holder_session_id": "holder-session",
            "acquired_at": "2026-07-26T17:00:00Z",
            "heartbeat_at": "2026-07-26T17:01:00Z",
        },
    }


def test_group_lease_contention_records_nonterminal_waiting_cases(
    test_db,
    monkeypatch,
) -> None:
    rows = materialize_installer_campaign(test_db, item_id=4203)
    fresh = [row for row in rows if row["host_baseline"] == "fresh-host"]
    held = MachineQaLeaseHeld(
        lease=Lease(
            id=17,
            project_id=1,
            lease_key="QA_HOST:mac-mini-lab",
            session_id="holder-session",
            actor_id="2",
            acquired_at="2026-07-26T17:00:00Z",
            heartbeat_at="2026-07-26T17:01:00Z",
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
        "yoke_core.domain.machine_qa_execution.acquire_machine_qa_lease",
        acquire,
    )

    outcome = handle_baseline_group_execute(baseline_group_request(int(fresh[0]["id"])))

    assert outcome.primary_success
    assert acquisitions == 1
    assert outcome.result_payload["baseline_ok"] is None
    expected_ids = [int(row["id"]) for row in fresh]
    assert outcome.result_payload["requirement_ids"] == expected_ids
    assert [
        result["requirement_id"] for result in outcome.result_payload["results"]
    ] == expected_ids
    assert all(
        result["case_outcome"] == "waiting"
        and result["verdict"] is None
        and result["evidence_count"] == 0
        and result["lease_context"]["id"] == 17
        for result in outcome.result_payload["results"]
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


def test_single_case_lease_contention_preserves_rerun_identity(
    test_db,
    monkeypatch,
) -> None:
    rows = materialize_installer_campaign(test_db, item_id=4204)
    target = next(row for row in rows if row["host_baseline"] == "shell-preconfigured")
    held = MachineQaLeaseHeld(
        lease=Lease(
            id=18,
            project_id=1,
            lease_key="QA_HOST:mac-mini-lab",
            session_id="holder-session",
            acquired_at="2026-07-26T17:02:00Z",
        ),
        machine="mac-mini-lab",
    )
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect",
        lambda: OpenFixtureConnection(test_db),
    )
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_execution.acquire_machine_qa_lease",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(held),
    )
    request = baseline_group_request(int(target["id"])).model_copy(
        update={
            "function": "test_machine.case_execute",
        }
    )

    outcome = handle_case_execute(request)

    assert outcome.primary_success
    assert outcome.result_payload["requirement_id"] == int(target["id"])
    assert outcome.result_payload["case_outcome"] == "waiting"
    assert outcome.result_payload["verdict"] is None
    assert outcome.result_payload["lease_context"]["id"] == 18


def test_waiting_case_cli_returns_retryable_exit_with_structured_result(
    monkeypatch,
    capsys,
) -> None:
    from yoke_core.domain import qa_case_execution_cli

    result = {
        "requirement_id": 41,
        "executor_id": "host_control",
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


def test_baseline_group_client_sends_only_an_anchor(
    monkeypatch,
) -> None:
    response = SimpleNamespace(
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
        return response

    monkeypatch.setattr(
        "yoke_core.domain.qa_composed_dispatch.call_qa_function",
        dispatch,
    )
    result = execute_materialized_machine_baseline_group(
        {
            "requirement_id": 41,
            "executor_id": "host_control",
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
    assert calls[0]["function_id"] == ("test_machine.baseline_group_execute")
    assert calls[0]["target"].qa_requirement_id == 41
    assert calls[0]["payload"] == {}


def test_baseline_group_execution_is_project_write_authorized() -> None:
    spec = classify(
        "test_machine.baseline_group_execute",
        side_effects=True,
        project_permission=None,
    )
    assert (spec.scope, spec.permission_key) == (PROJECT, PERM_ITEMS_WRITE)


def test_baseline_group_is_registered_as_internal_item_claim_execution() -> None:
    from yoke_core.domain.handlers.__init_register__ import (
        register_all_handlers,
    )
    from yoke_core.domain.yoke_function_registry import (
        lookup,
        reset_registry_for_tests,
    )

    reset_registry_for_tests()
    try:
        register_all_handlers()
        entry = lookup("test_machine.baseline_group_execute")
        assert entry is not None
        assert entry.target_kinds == ("qa_requirement",)
        assert entry.claim_required_kind == "item"
        assert entry.adapter_status == "internal"
        assert "server_discovered_baseline_group" in entry.guardrails
        assert "lease_waiting_state" in entry.guardrails
    finally:
        reset_registry_for_tests()
