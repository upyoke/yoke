"""The two ways an envelope could talk its way past the candidate review.

The server derives only the actor from the credential; the session id
travels as the caller wrote it. So a worker could name the steering seat's
session, or name no session at all and take the browser branch. Neither is
closed by a server check alone on a workstation where every surface shares
one operator credential -- the first is stopped at the hook before the
command runs, the second by an origin mark the UI server sets around its
own dispatch and no envelope can carry.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.steering_claim_test_support import (
    acquire_steering,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.ui_browser_origin import ui_browser_origin
from yoke_core.domain import lint_claim_ownership_mutations as lint
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.item_posture_amend import amend_item_posture
from yoke_core.domain.merge_candidate_review_authority import UNAUTHORIZED_CODE
from yoke_core.domain.merge_candidate_review_gate import (
    POSTURE_KEY,
    evaluate_candidate_review,
)
from yoke_core.domain.work_claim_targets import make_item_target

HEAD = "f" * 40
WORKER_SESSION = "spoof-worker"
STEERING_SESSION = "spoof-seat"
REVIEWER = 9401


def _deny(command: str, ambient: str = WORKER_SESSION):
    return lint.evaluate_payload(
        {"session_id": ambient, "tool_input": {"command": command}}
    )


# --- (a) naming another session's id is denied before the command runs ------


def test_resolving_with_a_foreign_session_id_is_denied() -> None:
    verdict = _deny(
        f"yoke decision-requests resolve 77 approve --session-id {STEERING_SESSION}"
    )
    assert verdict is not None
    reason, family = verdict
    assert family == "yoke/decision-requests-resolve"
    assert "claim-boundary bypass" in reason
    assert STEERING_SESSION in reason


def test_a_wrapper_does_not_launder_the_foreign_session_id() -> None:
    """`yoke dev run -- yoke ...` and global flags still match."""
    verdict = _deny(
        "yoke --env prod dev run -- yoke decision-requests resolve 77 approve "
        f"--session-id {STEERING_SESSION}"
    )
    assert verdict is not None
    assert verdict[1] == "yoke/decision-requests-resolve"


def test_relaxing_the_posture_with_a_foreign_session_id_is_denied() -> None:
    verdict = _deny(
        "yoke workflows item-posture amend YOK-1 --key merge_candidate_review "
        f'--clear --reason "off" --session-id {STEERING_SESSION}'
    )
    assert verdict is not None
    assert verdict[1] == "yoke/workflows-item-posture-amend"


def test_selecting_the_posture_is_not_session_bound() -> None:
    """Tightening is always allowed, so it is not the lint's business."""
    assert (
        _deny(
            "yoke workflows item-posture amend YOK-1 --key merge_candidate_review "
            f'--value true --reason "review this one" --session-id {STEERING_SESSION}'
        )
        is None
    )


def test_another_posture_key_is_not_session_bound() -> None:
    assert (
        _deny(
            "yoke workflows item-posture amend YOK-1 --key deployment --clear "
            f'--reason "no deploy" --session-id {STEERING_SESSION}'
        )
        is None
    )


def test_the_session_s_own_id_is_allowed() -> None:
    assert (
        _deny(
            "yoke decision-requests resolve 77 approve "
            f"--session-id {WORKER_SESSION}"
        )
        is None
    )


# --- (b) the session-less branch needs a server-established UI origin -------


def _item(conn) -> int:
    row = insert_item(
        conn,
        id=2900,
        workflow_id="dash",
        status="reviewing-implementation",
        workflow_posture=json.dumps({POSTURE_KEY: True}),
    )
    return int(row["id"])


def _world(conn) -> tuple[int, int]:
    item_id = _item(conn)
    project_id = int(
        conn.execute(
            "SELECT project_id FROM items WHERE id = %s", (item_id,)
        ).fetchone()[0]
    )
    seed_roles_and_permissions(conn)
    conn.execute(
        "INSERT INTO actors (id, kind, system_component, created_at) "
        "VALUES (%s, 'human', NULL, NOW()) ON CONFLICT DO NOTHING",
        (REVIEWER,),
    )
    grant_actor_project_role(
        conn, actor_id=REVIEWER, project_id=project_id, role_name=ROLE_OWNER
    )
    seed_session(conn, WORKER_SESSION, project_id)
    target = make_item_target(item_id)
    now = iso8601_now()
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claim_type, claimed_at, last_heartbeat) "
        "VALUES (%s, %s, %s, 'exclusive', %s, %s)",
        (WORKER_SESSION, target.kind, target.scope_json(), now, now),
    )
    conn.commit()
    verdict = evaluate_candidate_review(
        conn,
        item_id=item_id,
        commit_sha=HEAD,
        branch="YOK-9000",
        target="main",
        session_id=WORKER_SESSION,
    )
    return item_id, int(verdict.request_id)


def test_a_session_less_call_without_ui_origin_is_refused() -> None:
    """Omitting the session is not a way to become a person at a browser."""
    with test_database() as conn:
        _item_id, request_id = _world(conn)
        with pytest.raises(PermissionError) as caught:
            resolve_decision_request(
                conn,
                request_id,
                actor_id=REVIEWER,
                action="approve",
                note="pretending to be the Inbox",
                session_id="",
            )
        message = str(caught.value)
        assert UNAUTHORIZED_CODE in message
        assert "machine API token" in message


def test_the_ui_server_s_own_dispatch_clears_it() -> None:
    with test_database() as conn:
        item_id, request_id = _world(conn)
        with ui_browser_origin():
            row = resolve_decision_request(
                conn,
                request_id,
                actor_id=REVIEWER,
                action="approve",
                note="answered in the Inbox",
                session_id="",
            )
        assert row["resolution_action"] == "approve"
        cleared = evaluate_candidate_review(
            conn,
            item_id=item_id,
            commit_sha=HEAD,
            branch="YOK-9000",
            target="main",
            session_id=WORKER_SESSION,
        )
        assert cleared.satisfied is True


def test_the_origin_mark_does_not_survive_its_block() -> None:
    """It marks one dispatch, not the process."""
    with ui_browser_origin():
        pass
    with test_database() as conn:
        _item_id, request_id = _world(conn)
        with pytest.raises(PermissionError):
            resolve_decision_request(
                conn,
                request_id,
                actor_id=REVIEWER,
                action="approve",
                note="after the block",
                session_id="",
            )


def test_relaxing_the_posture_session_less_needs_the_same_origin() -> None:
    with test_database() as conn:
        item_id, _request_id = _world(conn)
        with pytest.raises(PermissionError) as caught:
            amend_item_posture(
                conn,
                item_id=item_id,
                key=POSTURE_KEY,
                clear=True,
                reason="turning it off without a session",
                actor_id=REVIEWER,
                session_id="",
            )
        assert UNAUTHORIZED_CODE in str(caught.value)


def test_the_answering_session_is_recorded_on_the_decision() -> None:
    """Every surface shares the actor, so the session is the audit."""
    with test_database() as conn:
        item_id, request_id = _world(conn)
        project_id = int(
            conn.execute(
                "SELECT project_id FROM items WHERE id = %s", (item_id,)
            ).fetchone()[0]
        )
        seed_session(conn, STEERING_SESSION, project_id)
        acquire_steering(conn, STEERING_SESSION, project_id)
        row = resolve_decision_request(
            conn,
            request_id,
            actor_id=REVIEWER,
            action="approve",
            note="read the diff",
            session_id=STEERING_SESSION,
        )
        decided = row["decisions"][-1]
        assert decided["decided_session_id"] == STEERING_SESSION
        assert decided["actor_id"] == REVIEWER
