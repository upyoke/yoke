"""Live scope coverage is the only elevated-operation session authority."""

import importlib
from unittest.mock import patch

import pytest

from runtime.api.domain.test_session_message_support import message_connection
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_contracts.session_queue_posture import SESSION_MODES
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.session_steering_authority import (
    require_steering_authority,
)
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.yoke_function_dispatch_claims import verify_claim
from yoke_core.domain.yoke_function_registry import lookup


def seat(conn, *, project=1, document=None):
    import json

    scope = {"project_id": project}
    if document:
        scope["document"] = document
    conn.execute(
        "INSERT INTO work_claims(session_id,target_kind,scope,claimed_at) "
        "VALUES ('s1','steering',?,'2026-01-01T00:00:00Z')",
        (json.dumps(scope),),
    )


@pytest.mark.parametrize(
    "state", ["live", "released", "ended", "terminated", "wrong_project"]
)
def test_authority_depends_on_live_covering_seat(state):
    conn = message_connection()
    seat(conn, project=2 if state == "wrong_project" else 1)
    if state == "released":
        conn.execute(
            "UPDATE work_claims SET released_at='2026-01-02T00:00:00Z' WHERE session_id='s1'"
        )
    elif state in ("ended", "terminated"):
        column = "ended_at" if state == "ended" else "terminated_at"
        conn.execute(
            f"UPDATE harness_sessions SET {column}='2026-01-02T00:00:00Z' WHERE session_id='s1'"
        )
    if state == "live":
        assert require_steering_authority(conn, caller_session_id="s1", project_id=1)[
            "claim_id"
        ]
    else:
        with pytest.raises(
            SessionError, match="requires a live steering seat for project 1"
        ):
            require_steering_authority(conn, caller_session_id="s1", project_id=1)


def test_document_scope_is_exact_and_authority_does_not_check_actor_kind_or_mode():
    conn = message_connection()
    seat(conn, document="AREA-PLAN")
    conn.execute("UPDATE harness_sessions SET actor_id=NULL WHERE session_id='s1'")
    target = {"project_id": 2, "document_project_id": 1, "document": "AREA-PLAN"}
    assert require_steering_authority(
        conn, caller_session_id="s1", project_id=2, target=target
    )
    with pytest.raises(SessionError):
        require_steering_authority(conn, caller_session_id="s1", project_id=1)


@pytest.mark.parametrize(
    "function",
    [
        "workflows.item.migrate",
        "strategy.claim.break_glass_release",
        "lifecycle.repair_status.execute",
        "claims.path.override",
        "session_control.qualification.open",
    ],
)
@pytest.mark.parametrize("allowed", [True, False])
def test_registered_operations_take_the_steering_gate(function, allowed):
    register_all_handlers()
    entry = lookup(function)
    assert entry.claim_required_kind == "steering"
    request = FunctionCallRequest(
        function=function, actor={"session_id": "s1"}, target={"kind": "global"}
    )
    with patch(
        "yoke_core.domain.yoke_function_dispatch_claims.steering_seat_for_request",
        return_value=({"claim_id": 1} if allowed else None, "alpha"),
    ):
        error = verify_claim(entry, request)
    if allowed:
        assert error is None
    else:
        assert error.error.code == "steering_seat_required"
        assert "requires a live steering seat for project alpha" in error.error.message
        assert "yoke say --steering" in error.error.message


def test_mode_convergence_is_idempotent_and_preserves_claims():
    conn = message_connection()
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN mode TEXT")
    conn.execute("UPDATE harness_sessions SET mode='operator' WHERE session_id='s1'")
    seat(conn)
    module = importlib.import_module(
        "yoke_core.domain.migrations.0069_retire_operator_session_mode"
    )
    module.apply(conn)
    module.apply(conn)
    module.invariants(conn)
    assert (
        conn.execute(
            "SELECT mode FROM harness_sessions WHERE session_id='s1'"
        ).fetchone()[0]
        == "wait"
    )
    assert require_steering_authority(conn, caller_session_id="s1", project_id=1)
    assert "operator" not in SESSION_MODES


@pytest.mark.parametrize("claim_in_target", [True, False])
@pytest.mark.parametrize("covered_owner", [True, False])
def test_path_override_uses_persisted_owner_instead_of_conflicting_item_hint(
    claim_in_target, covered_owner
):
    from contextlib import nullcontext
    from yoke_core.domain.yoke_function_dispatch_claims import steering_seat_for_request

    conn = message_connection()
    seat(conn, document="AREA-PLAN")
    conn.execute(
        "INSERT INTO item_strategy_docs VALUES (101,1,'AREA-PLAN','2026-01-01')"
    )
    conn.execute(
        "CREATE TABLE path_claims(id INTEGER,owner_kind TEXT,owner_item_id INTEGER)"
    )
    owner, hint = (101, 201) if covered_owner else (201, 101)
    conn.execute("INSERT INTO path_claims VALUES (1,'item',?)", (owner,))
    register_all_handlers()
    req = FunctionCallRequest(
        function="claims.path.override",
        actor={"session_id": "s1"},
        target={
            "kind": "item",
            "item_id": hint,
            **({"path_claim_id": 1} if claim_in_target else {}),
        },
        payload={} if claim_in_target else {"path_claim_id": 1},
    )
    with patch("yoke_core.domain.db_helpers.connect", return_value=nullcontext(conn)):
        found, project = steering_seat_for_request(lookup(req.function), req)
    assert bool(found) is covered_owner
    assert project == ("alpha" if covered_owner else "beta")


@pytest.mark.parametrize("action", ["Surface disable", "Surface enable"])
def test_surface_policy_mutations_require_live_project_coverage(action):
    from yoke_core.domain.handlers.session_surface_policy import _authorize

    conn = message_connection()
    seat(conn)
    req = FunctionCallRequest(
        function="session_control.surface_policy.disable",
        actor={"session_id": "s1"},
        target={"kind": "global"},
    )
    _authorize(conn, req, "alpha", action)
    with pytest.raises(SessionError, match="requires a live steering seat"):
        _authorize(conn, req, "beta", action)
