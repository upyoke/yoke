# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from typing import Any

from uuid import uuid4

from runtime.api.domain.machine_qa_host_test_support import (
    configure_test_machine,
    materialize_installer_campaign,
)

from runtime.api.domain.machine_qa_session_seed import seed_qa_session

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.coordination_claims import acquire, active_claim, release

from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin

from yoke_core.domain.machine_operation_recording import record_test_machine_operation

from yoke_core.domain.machine_qa_plan_case_execution import _waiting_case

from yoke_core.domain.machine_verification_recording import (
    record_test_machine_verification,
)

from yoke_core.domain.qa_host_health import HOST_UNHEALTHY_REASON, host_unhealthy

from yoke_core.domain.qa_host_turns import host_line

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

from yoke_core.domain.work_claim_targets import make_qa_admission_target

ACTOR = ActorContext(actor_id="1", session_id="session-machine-plan")

MACHINE = "mac-mini-lab"

ITEM_ID = 4431


def _notices(monkeypatch: Any) -> list[str]:
    bodies: list[str] = []

    def send(*args: Any, **kwargs: Any) -> dict[str, str]:
        bodies.append(kwargs["body"])
        return {"message_id": str(uuid4())}

    monkeypatch.setattr("yoke_core.domain.session_message_service.send_message", send)
    monkeypatch.setattr(
        "yoke_core.domain.session_explicit_wake.mark_explicit_stopped_wake",
        lambda *a, **k: None,
    )
    return bodies


def _project_id(conn: Any) -> int:
    return int(
        conn.execute("SELECT id FROM projects WHERE slug='yoke'").fetchone()["id"]
    )


def _record(conn: Any, operation: str, status: str, error: str | None = None) -> None:
    common = dict(
        test_machine=MACHINE,
        status=status,
        checks=[{"name": operation, "ok": status == "verified"}],
        error_code=error,
    )
    if operation == "verify":
        record_test_machine_verification(conn, _project_id(conn), **common)
    else:
        record_test_machine_operation(
            conn,
            _project_id(conn),
            operation=operation,
            lease_id=1,
            contract_digest="d" * 64,
            **common,
        )
    conn.commit()


def _begin(execution: dict, case: dict) -> Any:
    outcome = handle_plan_case_begin(
        FunctionCallRequest(
            function="test_machine.plan_case.begin",
            actor=ACTOR,
            target=TargetRef(kind="item", item_id=ITEM_ID),
            payload={
                "execution_id": str(execution["id"]),
                "ordinal": 0,
                "requirement_id": int(case["requirement_id"]),
            },
        )
    )
    assert outcome.primary_success, outcome.error
    return outcome.result_payload


def _wait_state(conn: Any, session_id: str) -> str:
    row = conn.execute(
        "SELECT state FROM qa_test_machine_waits WHERE session_id=%s ORDER BY queued_at DESC",
        (session_id,),
    ).fetchone()
    return str(row["state"])
