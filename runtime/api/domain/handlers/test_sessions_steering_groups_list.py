"""``sessions.steering_groups.list`` answers the group question directly.

The card tint ranks steering groups by sorted seat id and reads nothing
else, so it asks this read rather than the session roster. These cases pin
the two things that makes safe: the answer equals the set the roster's own
``steering_group_session_id`` projection yields, and it obeys the same
visibility boundary the roster applies.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.api.fixtures.session_holdings import insert_steering_claim
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.handlers.sessions_steering_groups import (
    handle_sessions_steering_groups_list,
)

# Project id 2 is already seeded as "externalwebapp" by the fixture schema;
# these tests use ids the fixture leaves free.
_PLATFORM_PROJECT_ID = 3
_THIRD_PROJECT_ID = 4


def _iso(minutes_ago: int = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _insert_session(
    conn,
    session_id: str,
    *,
    project_id: int = 1,
    ended_at: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, mode, offered_at, last_heartbeat, ended_at"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            "claude-code",
            "anthropic",
            "test-model",
            "primary",
            "/tmp/workspace",
            project_id,
            "wait",
            _iso(),
            _iso(),
            ended_at,
        ),
    )
    conn.commit()


def _insert_project(conn, project_id: int, slug: str) -> None:
    conn.execute(
        "INSERT INTO projects (id, slug, name, created_at) VALUES (%s, %s, %s, %s)",
        (project_id, slug, slug.title(), _iso()),
    )
    conn.commit()


def _insert_document_claim(conn, session_id: str, *, project_id: int, slug: str) -> None:
    from yoke_core.domain.work_claim_targets import make_steering_target

    target = make_steering_target(project_id, document=slug)
    now = _iso()
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, "
        "claimed_at, last_heartbeat, reason) VALUES (%s, %s, %s, %s, %s, %s)",
        (session_id, target.kind, target.scope_json(), now, now, "strategy review"),
    )
    conn.commit()


def _grant_project_role(conn, actor_id: int, project_id: int) -> None:
    conn.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (%s, %s, 'test role', %s) ON CONFLICT (id) DO NOTHING",
        (9000 + project_id, f"reader-{project_id}", _iso()),
    )
    conn.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at) VALUES (%s, %s, %s, %s)",
        (actor_id, project_id, 9000 + project_id, _iso()),
    )
    conn.commit()


def _request(
    function: str, payload: dict, *, actor_id: int | None = None
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(
            actor_id=str(actor_id) if actor_id is not None else None,
            session_id="",
        ),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _groups(payload: dict, *, actor_id: int | None = None) -> list[str]:
    outcome = handle_sessions_steering_groups_list(
        _request("sessions.steering_groups.list", payload, actor_id=actor_id)
    )
    assert outcome.primary_success, outcome.error
    return [row["steering_group_session_id"] for row in outcome.result_payload["rows"]]


def _roster_groups(*, actor_id: int | None = None) -> list[str]:
    """The same answer the way the tint used to reach it, for comparison."""
    outcome = handle_sessions_list(
        _request(
            "sessions.list", {"per_project": True, "open": True}, actor_id=actor_id
        )
    )
    assert outcome.primary_success, outcome.error
    return sorted(
        {
            str(row["steering_group_session_id"])
            for row in outcome.result_payload["rows"]
            if row.get("steering_group_session_id")
        }
    )


class TestTheGroupSetMatchesTheRoster:
    def test_every_live_seat_is_one_row_sorted_by_id(self, test_db):
        _insert_project(test_db, _PLATFORM_PROJECT_ID, "platform")
        _insert_session(test_db, "seat-b")
        _insert_session(test_db, "seat-a", project_id=_PLATFORM_PROJECT_ID)
        insert_steering_claim(test_db, "seat-b", project_id=1)
        insert_steering_claim(test_db, "seat-a", project_id=_PLATFORM_PROJECT_ID)

        assert _groups({}) == ["seat-a", "seat-b"]
        assert _groups({}) == _roster_groups()

    def test_a_seat_is_named_once_however_many_documents_it_holds(self, test_db):
        # A live seat is often two document claims on one session, and the
        # tint colors the session, not the claim.
        _insert_session(test_db, "seat-a")
        for slug in ("CURRENT-PLAN", "MASTER-PLAN"):
            _insert_document_claim(test_db, "seat-a", project_id=1, slug=slug)

        assert _groups({}) == ["seat-a"]

    def test_a_released_claim_is_not_a_seat(self, test_db):
        _insert_session(test_db, "seat-a")
        insert_steering_claim(test_db, "seat-a", project_id=1, released_at=_iso())

        assert _groups({}) == []
        assert _roster_groups() == []

    def test_an_ended_session_holding_an_unreleased_claim_is_not_a_seat(self, test_db):
        # The non-destructive session end never releases claims, so an ended
        # session can still hold one; a dead seat tints nothing.
        _insert_session(test_db, "seat-a", ended_at=_iso())
        insert_steering_claim(test_db, "seat-a", project_id=1)

        assert _groups({}) == []

    def test_a_session_holding_no_steering_claim_is_not_a_group(self, test_db):
        _insert_session(test_db, "worker-a")

        assert _groups({}) == []


class TestVisibilityBoundary:
    def test_a_seat_is_visible_through_the_project_it_steers(self, test_db):
        from yoke_core.domain.actors import seed_human_actor

        _insert_project(test_db, _PLATFORM_PROJECT_ID, "platform")
        _insert_project(test_db, _THIRD_PROJECT_ID, "third")
        # Home project is yoke; the seat steers platform. Granting platform
        # alone proves the steered half of the boundary on its own.
        _insert_session(test_db, "seat-a", project_id=1)
        insert_steering_claim(test_db, "seat-a", project_id=_PLATFORM_PROJECT_ID)
        actor_id = seed_human_actor(test_db)
        _grant_project_role(test_db, actor_id, _PLATFORM_PROJECT_ID)

        assert _groups({}, actor_id=actor_id) == ["seat-a"]

    def test_a_seat_is_visible_through_the_project_it_lives_in(self, test_db):
        from yoke_core.domain.actors import seed_human_actor

        _insert_project(test_db, _PLATFORM_PROJECT_ID, "platform")
        _insert_session(test_db, "seat-a", project_id=_PLATFORM_PROJECT_ID)
        insert_steering_claim(test_db, "seat-a", project_id=1)
        actor_id = seed_human_actor(test_db)
        _grant_project_role(test_db, actor_id, _PLATFORM_PROJECT_ID)

        assert _groups({}, actor_id=actor_id) == ["seat-a"]

    def test_a_seat_in_no_visible_project_is_withheld(self, test_db):
        from yoke_core.domain.actors import seed_human_actor

        _insert_project(test_db, _PLATFORM_PROJECT_ID, "platform")
        _insert_project(test_db, _THIRD_PROJECT_ID, "third")
        _insert_session(test_db, "seat-a", project_id=_THIRD_PROJECT_ID)
        insert_steering_claim(test_db, "seat-a", project_id=_THIRD_PROJECT_ID)
        actor_id = seed_human_actor(test_db)
        _grant_project_role(test_db, actor_id, _PLATFORM_PROJECT_ID)

        assert _groups({}, actor_id=actor_id) == []
        assert _roster_groups(actor_id=actor_id) == []


class TestRefusals:
    def test_it_takes_no_inputs_and_names_what_to_remove(self, test_db):
        outcome = handle_sessions_steering_groups_list(
            _request("sessions.steering_groups.list", {"project": "yoke"})
        )

        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
        assert "project" in outcome.error.message

    def test_it_refuses_a_non_global_target(self, test_db):
        request = _request("sessions.steering_groups.list", {})
        request.target = TargetRef(kind="item", item_id=1)

        outcome = handle_sessions_steering_groups_list(request)

        assert not outcome.primary_success
        assert outcome.error.code == "target_invalid"
