"""Credential-custody coverage for two-phase Test Machine execution."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.machine_qa_baseline_group_test_support import (
    configure_test_machine,
    materialize_installer_campaign,
)
from runtime.api.domain.machine_qa_test_support import FakeHostControl, make_conn
from yoke_cli.commands.adapters import (
    test_machine as test_machine_cli,
    test_machine_operation as test_machine_operation_cli,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
    TargetRef,
)
from yoke_core.domain.handlers.machine_qa import (
    handle_operation_on_control_plane,
)
from yoke_core.domain.handlers.machine_qa_operation import (
    handle_operation_begin,
    handle_operation_submit,
)
from yoke_core.domain.handlers.machine_qa_case import (
    handle_case_begin,
    handle_case_execute,
    handle_case_submit,
)
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_core.domain.machine_qa_local_execution import (
    execute_host_operation_contract,
    execute_machine_case_contract,
)

ACTOR = ActorContext(actor_id="2", session_id="session-machine-two-phase")


def _verify_request(function: str, payload: dict[str, Any]) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ACTOR,
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _case_request(
    function: str,
    requirement_id: int,
    payload: dict[str, Any] | None = None,
    *,
    actor: ActorContext = ACTOR,
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=actor,
        target=TargetRef(
            kind="qa_requirement",
            qa_requirement_id=requirement_id,
        ),
        payload=payload or {},
    )


def test_verification_begin_local_submit_persists_and_releases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        begun = handle_operation_begin(
            _verify_request(
                "test_machine.operation.begin",
                {"project": "yoke", "operation": "verify"},
            )
        )
        assert begun.primary_success
        execution = begun.result_payload["execution"]
        assert "secret" not in json.dumps(execution).lower()
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM work_claims WHERE released_at IS NULL "
                "AND target_kind IN ('migration_serialization','qa_admission','route_qualification')"
            ).fetchone()[0]
            == 1
        )

        submission = execute_host_operation_contract(execution)
        assert "top-secret" not in json.dumps(submission.payload)
        assert "[REDACTED]" in json.dumps(submission.payload)
        submitted = handle_operation_submit(
            _verify_request(
                "test_machine.operation.submit",
                {"project": "yoke", **submission.payload},
            )
        )
    finally:
        clear_host_control_factory()

    assert submitted.primary_success
    assert submitted.result_payload["status"] == "verified"
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM work_claims WHERE released_at IS NULL "
            "AND target_kind IN ('migration_serialization','qa_admission','route_qualification')"
        ).fetchone()[0]
        == 0
    )
    receipt = conn.execute(
        "SELECT status,receipt_json FROM test_machine_verifications WHERE project_id=1"
    ).fetchone()
    assert receipt["status"] == "verified"
    assert "top-secret" not in receipt["receipt_json"]


def test_submit_rejects_another_actor_without_releasing_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = make_conn()
    configure_test_machine(conn, tmp_path, monkeypatch)
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        begun = handle_operation_begin(
            _verify_request(
                "test_machine.operation.begin",
                {"project": "yoke", "operation": "verify"},
            )
        )
        submission = execute_host_operation_contract(
            begun.result_payload["execution"],
        )
    finally:
        clear_host_control_factory()
    request = _verify_request(
        "test_machine.operation.submit",
        {"project": "yoke", **submission.payload},
    ).model_copy(
        update={
            "actor": ActorContext(
                actor_id="3",
                session_id="different-session",
            ),
        }
    )

    submitted = handle_operation_submit(request)

    assert not submitted.primary_success
    assert "different session" in submitted.error.message
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM work_claims WHERE released_at IS NULL "
            "AND target_kind IN ('migration_serialization','qa_admission','route_qualification')"
        ).fetchone()[0]
        == 1
    )


@pytest.mark.parametrize(
    ("operation", "command"),
    [
        ("verify", "verify"),
        ("reset", "reset"),
        ("golden_capture", "golden-capture"),
        ("bridge_diagnose", "bridge-diagnose"),
    ],
)
def test_direct_hosted_operation_points_to_cli(
    operation: str,
    command: str,
) -> None:
    # The refusal names the operation the caller dispatched, which is the
    # function id itself rather than anything in the payload.
    outcome = handle_operation_on_control_plane(
        _verify_request(f"test_machine.{operation}", {"project": "yoke"})
    )

    assert not outcome.primary_success
    assert outcome.error.code == "host_control_client_required"
    assert f"yoke test-machine {command} --project yoke" in outcome.error.message


def test_direct_hosted_case_points_to_credential_owning_cli() -> None:
    outcome = handle_case_execute(
        _case_request(
            "test_machine.case_execute",
            41,
        )
    )

    assert not outcome.primary_success
    assert outcome.error.code == "host_control_client_required"
    assert "yoke qa case run --requirement-id 41" in outcome.error.message


def test_case_begin_local_submit_records_secret_free_evidence(
    test_db: Any,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    materialize_installer_campaign(test_db, item_id=4210)
    configure_test_machine(test_db, tmp_path, monkeypatch)
    requirement_id = int(
        test_db.execute(
            "SELECT id FROM qa_requirements "
            "WHERE item_id=%s AND method_id='machine-state-check' "
            "ORDER BY id LIMIT 1",
            (4210,),
        ).fetchone()[0]
    )
    register_host_control_factory(lambda _material: FakeHostControl())
    try:
        begun = handle_case_begin(
            _case_request(
                "test_machine.case.begin",
                requirement_id,
            )
        )
        assert begun.primary_success
        submission = execute_machine_case_contract(
            begun.result_payload["execution"],
        )
        assert "top-secret" not in json.dumps(submission.payload)
        submitted = handle_case_submit(
            _case_request(
                "test_machine.case.submit",
                requirement_id,
                submission.payload,
            )
        )
    finally:
        clear_host_control_factory()

    assert submitted.primary_success
    assert submitted.result_payload["case_outcome"] == "passed"
    run = test_db.execute(
        "SELECT verdict,raw_result FROM qa_runs WHERE id=%s",
        (submitted.result_payload["run_id"],),
    ).fetchone()
    assert run["verdict"] == "pass"
    assert "top-secret" not in run["raw_result"]
    assert "[REDACTED]" in run["raw_result"]
    assert submitted.result_payload["evidence_count"] == 1
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM work_claims WHERE released_at IS NULL "
            "AND target_kind IN ('migration_serialization','qa_admission','route_qualification')"
        ).fetchone()[0]
        == 0
    )


def test_cli_verify_local_failure_aborts_server_lease(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, Any]] = []
    begin = FunctionCallResponse(
        success=True,
        function="test_machine.operation.begin",
        version="v1",
        result={
            "execution": {
                "lease_id": 19,
                "contract_digest": "digest-19",
            },
        },
    )
    abort = FunctionCallResponse(
        success=True,
        function="test_machine.operation.abort",
        version="v1",
        result={
            "lease_id": 19,
            "released": True,
            "reason": "local_execution_failed",
        },
    )

    def dispatch(**kwargs: Any) -> FunctionCallResponse:
        calls.append(dict(kwargs))
        return begin if len(calls) == 1 else abort

    monkeypatch.setattr(
        test_machine_operation_cli,
        "ensure_handlers_loaded",
        lambda: None,
    )
    monkeypatch.setattr(test_machine_operation_cli, "call_dispatcher", dispatch)
    monkeypatch.setattr(
        "yoke_harness.test_machine_operations.execute_host_operation_contract",
        lambda _contract, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("local control unavailable")
        ),
    )

    exit_code = test_machine_cli.test_machine_verify(
        [
            "--project",
            "yoke",
            "--json",
        ]
    )

    assert exit_code == 1
    assert [call["function_id"] for call in calls] == [
        "test_machine.operation.begin",
        "test_machine.operation.abort",
    ]
    assert calls[1]["payload"] == {
        "project": "yoke",
        "lease_id": 19,
        "contract_digest": "digest-19",
        "operation": "verify",
        "baseline": None,
        "destination": None,
        "reason": "local_execution_failed",
    }
    emitted = json.loads(capsys.readouterr().out)
    assert emitted["function"] == "test_machine.verify"
    assert emitted["error"]["code"] == "host_control_local_execution_failed"
    assert "server lease was released" in emitted["error"]["message"]
