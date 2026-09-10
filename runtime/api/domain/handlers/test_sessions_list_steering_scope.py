"""A live steering claim is a project-membership fact for ``sessions.list``.

A session's own ``project_id`` binding is its home project. A session that
is actively steering a *different* project (a cross-project steering seat)
must still surface when that other project is the one being filtered on:
both the ``project=`` SQL filter and the ``projects=`` open-row fan-out
matched on home project alone, so a session steering a project other than
the one it started in never appeared there.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.api.fixtures.session_holdings import insert_steering_claim
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.sessions_list_read import list_sessions

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
    last_heartbeat: str | None = None,
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
            last_heartbeat or _iso(),
            last_heartbeat or _iso(),
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


def _request(payload: dict, *, actor_id: int | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(
            actor_id=str(actor_id) if actor_id is not None else None,
            session_id="",
        ),
        target=TargetRef(kind="global"),
        payload=payload,
    )


class TestProjectFilterHonorsLiveSteeringClaim:
    def test_a_session_steering_a_different_project_is_visible_there(self, test_db):
        _insert_project(test_db, _PLATFORM_PROJECT_ID, "platform")
        # Home project is 1 ("yoke"); the live steering claim targets platform.
        _insert_session(test_db, "s-root", project_id=1)
        insert_steering_claim(test_db, "s-root", project_id=_PLATFORM_PROJECT_ID)

        rows = list_sessions(project="platform")
        assert [row["session_id"] for row in rows] == ["s-root"]

    def test_a_document_scoped_steering_claim_matches_the_same_way(self, test_db):
        _insert_project(test_db, _PLATFORM_PROJECT_ID, "platform")
        _insert_session(test_db, "s-root", project_id=1)
        # A document-scoped seat still names the project in its scope, so
        # matching needs no special path beyond the plain project claim.
        from yoke_core.domain.work_claim_targets import make_steering_target

        target = make_steering_target(_PLATFORM_PROJECT_ID, document="CURRENT-PLAN")
        now = _iso()
        test_db.execute(
            "INSERT INTO work_claims (session_id, target_kind, scope, "
            "claimed_at, last_heartbeat, reason) VALUES (%s, %s, %s, %s, %s, %s)",
            ("s-root", target.kind, target.scope_json(), now, now, "strategy review"),
        )
        test_db.commit()

        rows = list_sessions(project="platform")
        assert [row["session_id"] for row in rows] == ["s-root"]

    def test_the_same_session_still_matches_its_own_home_project(self, test_db):
        _insert_project(test_db, _PLATFORM_PROJECT_ID, "platform")
        _insert_session(test_db, "s-root", project_id=1)
        insert_steering_claim(test_db, "s-root", project_id=_PLATFORM_PROJECT_ID)

        rows = list_sessions(project="yoke")
        assert [row["session_id"] for row in rows] == ["s-root"]

    def test_a_released_steering_claim_adds_no_visibility(self, test_db):
        _insert_project(test_db, _PLATFORM_PROJECT_ID, "platform")
        _insert_session(test_db, "s-root", project_id=1)
        insert_steering_claim(
            test_db, "s-root", project_id=_PLATFORM_PROJECT_ID, released_at=_iso(),
        )

        assert list_sessions(project="platform") == []

    def test_an_ended_session_gains_no_visibility_from_its_stale_claim(self, test_db):
        _insert_project(test_db, _PLATFORM_PROJECT_ID, "platform")
        # The non-destructive session end never releases claims, so an
        # ended session can still hold a live, unreleased steering claim;
        # that must not resurrect it as a candidate for the steered project.
        _insert_session(test_db, "s-root", project_id=1, ended_at=_iso())
        insert_steering_claim(test_db, "s-root", project_id=_PLATFORM_PROJECT_ID)

        assert list_sessions(project="platform") == []

    def test_an_unrelated_project_gains_no_visibility(self, test_db):
        _insert_project(test_db, _PLATFORM_PROJECT_ID, "platform")
        _insert_project(test_db, _THIRD_PROJECT_ID, "third")
        _insert_session(test_db, "s-root", project_id=1)
        insert_steering_claim(test_db, "s-root", project_id=_PLATFORM_PROJECT_ID)

        assert list_sessions(project="third") == []


class TestOpenRowsDedupeCrossProjectSteering:
    def test_a_session_matching_both_its_home_and_steered_project_appears_once(
        self, test_db,
    ):
        _insert_project(test_db, _PLATFORM_PROJECT_ID, "platform")
        _insert_session(test_db, "s-root", project_id=1)
        insert_steering_claim(test_db, "s-root", project_id=_PLATFORM_PROJECT_ID)

        outcome = handle_sessions_list(
            _request({"open": True, "projects": ["yoke", "platform"]})
        )
        assert outcome.primary_success
        session_ids = [row["session_id"] for row in outcome.result_payload["rows"]]
        assert session_ids == ["s-root"]


class TestAuthorizationBoundary:
    def test_a_restricted_actor_sees_the_steerer_only_through_a_visible_project(
        self, test_db,
    ):
        from yoke_core.domain.actors import seed_human_actor

        _insert_project(test_db, _PLATFORM_PROJECT_ID, "platform")
        _insert_project(test_db, _THIRD_PROJECT_ID, "third")
        _insert_session(test_db, "s-root", project_id=1)
        insert_steering_claim(test_db, "s-root", project_id=_PLATFORM_PROJECT_ID)

        actor_id = seed_human_actor(test_db)
        _grant_project_role(test_db, actor_id, 1)
        _grant_project_role(test_db, actor_id, _PLATFORM_PROJECT_ID)

        # Allowed steered project: the actor's own visibility grants platform,
        # so the cross-project steerer is a legitimate candidate there too.
        allowed = handle_sessions_list(
            _request({"open": True, "projects": ["platform"]}, actor_id=actor_id)
        )
        assert allowed.primary_success
        assert [row["session_id"] for row in allowed.result_payload["rows"]] == [
            "s-root",
        ]

        # Inaccessible project: the actor holds no role there, so the live
        # steering claim is not a back door around ordinary authorization.
        denied = handle_sessions_list(
            _request({"open": True, "projects": ["third"]}, actor_id=actor_id)
        )
        assert denied.primary_success
        assert denied.result_payload["rows"] == []
