"""A steering seat rebinds a requirement on an unclaimed done item."""

from __future__ import annotations

import json

from runtime.api.domain.steering_claim_test_support import seed_session
from runtime.api.domain.qa_requirement_target_rebind_test_support import (
    _stamp_requirement,
    _yoke_development,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.handlers.qa_requirement_rebind import (
    handle_qa_requirement_rebind_target,
)
from yoke_core.domain.settings_cas import (
    apply_key_path_assignments,
    parse_settings_object,
)
from yoke_core.domain.steering_claims import acquire as acquire_seat
from yoke_core.domain.yoke_function_dispatch_claims import (
    verify_claim,
    who_claims_for_item,
)
from yoke_core.domain.yoke_function_registry import lookup

SEAT = "rebind-steering"
STRANGER = "rebind-stranger"
RATIONALE = "hosts.app was declared on the same environment"


def _move_declared_host(conn, environment_id: int) -> None:
    row = conn.execute(
        "SELECT settings FROM environments WHERE id=%s",
        (int(environment_id),),
    ).fetchone()
    merged = json.dumps(
        apply_key_path_assignments(
            parse_settings_object(str(row[0] or "{}"), what="settings"),
            {"hosts.app": "https://app.example.test"},
        )
    )
    conn.execute(
        "UPDATE environments SET settings=%s WHERE id=%s",
        (merged, int(environment_id)),
    )
    conn.commit()


def _done_requirement(conn, item_id: int) -> int:
    environment_id = _yoke_development(conn)
    requirement_id = _stamp_requirement(
        conn, item_id=item_id, environment_id=environment_id
    )
    conn.execute("UPDATE items SET status='done' WHERE id=%s", (item_id,))
    conn.commit()
    _move_declared_host(conn, environment_id)
    assert who_claims_for_item(item_id) is None
    return requirement_id


def _request(requirement_id: int, session_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="qa.requirement.rebind_target",
        actor=ActorContext(actor_id="2", session_id=session_id),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload={"rationale": RATIONALE},
    )


def _gate(request: FunctionCallRequest):
    register_all_handlers()
    return verify_claim(lookup(request.function), request)


def test_steering_seat_rebinds_requirement_on_unclaimed_done_item() -> None:
    with test_database() as conn:
        item_id = 9811
        requirement_id = _done_requirement(conn, item_id)
        project_id = int(
            conn.execute(
                "SELECT project_id FROM items WHERE id=%s", (item_id,)
            ).fetchone()[0]
        )
        seed_session(conn, SEAT, project_id)
        acquire_seat(
            conn,
            session_id=SEAT,
            project_id=project_id,
            reason="rebind stranded evidence",
        )
        request = _request(requirement_id, SEAT)
        assert _gate(request) is None
        outcome = handle_qa_requirement_rebind_target(request)
        assert outcome.primary_success
        assert outcome.result_payload["already_current"] is False
        assert (
            outcome.result_payload["from_digest"] != outcome.result_payload["to_digest"]
        )
        status = conn.execute(
            "SELECT status FROM items WHERE id=%s", (item_id,)
        ).fetchone()[0]
        assert status == "done"
        assert who_claims_for_item(item_id) is None


def test_done_item_without_seat_or_claim_refuses_rebind() -> None:
    with test_database() as conn:
        item_id = 9812
        requirement_id = _done_requirement(conn, item_id)
        project_id = int(
            conn.execute(
                "SELECT project_id FROM items WHERE id=%s", (item_id,)
            ).fetchone()[0]
        )
        seed_session(conn, STRANGER, project_id)
        refusal = _gate(_request(requirement_id, STRANGER))
        assert refusal.error.code == "claim_required"
        assert "rebind-target" in refusal.error.message
        assert "ask that holder" in refusal.error.message
