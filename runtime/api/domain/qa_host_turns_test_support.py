# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from contextlib import nullcontext

from uuid import uuid4

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.coordination_claims import (
    CoordinationClaimHeldError,
    acquire,
    active_claim,
    release,
)

from yoke_core.domain.handlers.claims_coordination_claim import handle_acquire

from yoke_core.domain.qa_host_turns import host_line, join_host_line

from yoke_core.domain.work_claim_targets import make_qa_admission_target

MACHINE = "linux-lab"

KEY = f"QA_HOST:{MACHINE}"


def _notices(monkeypatch):
    bodies = []

    def send(*args, **kwargs):
        bodies.append(kwargs["body"])
        return {"message_id": str(uuid4())}

    monkeypatch.setattr("yoke_core.domain.session_message_service.send_message", send)
    monkeypatch.setattr(
        "yoke_core.domain.session_explicit_wake.mark_explicit_stopped_wake",
        lambda *a, **k: None,
    )
    return bodies


def _execution_wait(conn, session_id, test_machine=MACHINE):
    execution_id = str(uuid4())
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,session_id,actor_id,"
        "roster_digest,roster_json,cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES(%s,%s,%s,'1',%s,'[]',0,'waiting',now(),now())",
        (execution_id, str(uuid4()), session_id, "a" * 64),
    )
    join_host_line(
        conn,
        make_qa_admission_target(test_machine),
        session_id=session_id,
        actor_id=1,
        resume_command="yoke qa plan run --project example --plan smoke",
        execution_id=execution_id,
    )
    conn.commit()
    return execution_id
