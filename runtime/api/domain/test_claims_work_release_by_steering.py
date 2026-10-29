# ruff: noqa: F811

"""A steering seat releases another session's claim without ending it."""

from __future__ import annotations

import pytest

from runtime.api.domain.test_claims_work_release_process_paths import (
    _seed_linked_path_claim,
    _seed_process_work_claim,
)
from runtime.api.domain.test_session_termination import (  # noqa: F401
    _add_open_message,
    _termination_schema_and_events,
    _add_target_claim,
    _register_operator_and_target,
)
from runtime.api.test_sessions import _register, conn  # noqa: F401
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.handlers.claims_work import handle_release
from yoke_core.domain import schema_init_actor_path_claim_tables as path_schema
from yoke_core.domain.schema_init_path_tables import create_path_registry_tables
from yoke_core.domain.yoke_function_dispatch_claims import verify_claim
from yoke_core.domain.yoke_function_registry import lookup, reset_registry_for_tests



@pytest.fixture(autouse=True)
def _registry():
    reset_registry_for_tests()
    register_all_handlers()
    yield
    reset_registry_for_tests()


def _claim_id(conn, session_id="worker") -> int:
    return int(
        conn.execute(
            "SELECT id FROM work_claims WHERE session_id=%s AND released_at IS NULL",
            (session_id,),
        ).fetchone()[0]
    )


def _release(claim_id: int, caller: str = "operator"):
    """Run the dispatcher's claim gate, then the handler when it allows."""
    request = FunctionCallRequest(
        function="claims.work.release",
        actor=ActorContext(session_id=caller),
        target=TargetRef(kind="claim", claim_id=claim_id),
        payload={"claim_id": claim_id, "reason": "holder stopped"},
    )
    refusal = verify_claim(lookup("claims.work.release"), request)
    return refusal if refusal is not None else handle_release(request)


def _assert_holder_intact(conn) -> None:
    session = conn.execute(
        "SELECT ended_at,terminated_at FROM harness_sessions WHERE session_id='worker'"
    ).fetchone()
    assert tuple(session) == (None, None)
    recipient = conn.execute(
        "SELECT state,cancelled_at FROM session_message_recipients"
    ).fetchone()
    assert tuple(recipient) == ("injected", None)


def test_steering_seat_releases_another_sessions_item_claim(conn) -> None:
    _register_operator_and_target(conn)
    _add_target_claim(conn)
    _add_open_message(conn)
    claim_id = _claim_id(conn)

    outcome = _release(claim_id)

    assert outcome.primary_success, outcome
    claim = conn.execute(
        "SELECT released_at,release_reason FROM work_claims WHERE id=%s",
        (claim_id,),
    ).fetchone()
    assert claim["released_at"] is not None
    assert claim["release_reason"]
    _assert_holder_intact(conn)


def test_steering_release_frees_linked_path_claims(conn, monkeypatch) -> None:
    # The session schema has no epic_tasks for the task-binding table.
    monkeypatch.setattr(
        path_schema, "create_path_claim_task_binding_table", lambda *a, **k: None
    )
    create_path_registry_tables(conn)
    path_schema.create_actor_path_claim_tables(conn)
    _register_operator_and_target(conn)
    _add_open_message(conn)
    claim_id = _seed_process_work_claim(
        conn, session_id="worker", process_key="STRATEGIZE"
    )
    path_claim_id = _seed_linked_path_claim(conn, work_claim_id=claim_id)
    conn.commit()

    outcome = _release(claim_id)

    assert outcome.result_payload["linked_path_claim_ids"] == [path_claim_id]
    state = conn.execute(
        "SELECT state FROM path_claims WHERE id=%s", (path_claim_id,)
    ).fetchone()[0]
    assert state == "released"
    _assert_holder_intact(conn)


def test_seat_on_one_project_releases_a_claim_on_another(conn) -> None:
    _register_operator_and_target(conn)
    conn.execute(
        "INSERT INTO projects (id,name,slug,created_at) "
        "VALUES (2,'Other','other','2026-08-26T12:00:00Z') ON CONFLICT DO NOTHING"
    )
    conn.execute("UPDATE harness_sessions SET project_id=2 WHERE session_id='worker'")
    conn.commit()
    _add_target_claim(conn, item_id=901)
    conn.execute("UPDATE items SET project_id=2 WHERE id=901")
    conn.commit()

    outcome = _release(_claim_id(conn))

    assert outcome.primary_success, outcome


def test_caller_without_a_seat_is_refused_with_the_release_command(conn) -> None:
    _register_operator_and_target(conn)
    _register(conn, session_id="bystander", actor_id=43)
    _add_target_claim(conn)
    claim_id = _claim_id(conn)

    refusal = _release(claim_id, caller="bystander")

    assert refusal.error.code == "claim_required"
    assert f"yoke claims work release --claim-id {claim_id}" in refusal.error.message
    assert "terminate" not in refusal.error.message
    released = conn.execute(
        "SELECT released_at FROM work_claims WHERE id=%s", (claim_id,)
    ).fetchone()[0]
    assert released is None


def test_released_claim_still_reports_not_active(conn) -> None:
    _register_operator_and_target(conn)
    _add_target_claim(conn)
    claim_id = _claim_id(conn)
    assert _release(claim_id).primary_success

    refusal = _release(claim_id)

    assert refusal.error.message == (
        f"claim {claim_id} is not an active claim; nothing to release"
    )
