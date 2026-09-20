"""The open roster read covers every visible project in one pass.

``sessions.list {open: true}`` shows the live roster for each project the
caller can see. It used to run the whole roster pipeline — the roster query,
the whole-table claim-holder read, every page enrichment — once per visible
project and merge the results in Python, so its cost grew with the number of
projects on the account rather than with the sessions actually shown.

One pass now answers for the set. Membership still groups the page by
project, and a session whose live steering claim names another project still
appears under that project too, so what the roster shows is unchanged.
"""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import sessions_list_read
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.work_claim_targets import make_steering_target

from runtime.api.domain.handlers.test_sessions_list_handler import (
    _insert_session,
    _iso,
)


#: The roster groups by project only for a caller whose visibility is a
#: concrete set; a local unscoped call has no project set to group by.
_SCOPED_ACTOR_ID = 4242
_SCOPED_ROLE_ID = 4243


def _open_request(actor_id: int | None = _SCOPED_ACTOR_ID) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(
            actor_id=None if actor_id is None else str(actor_id),
            session_id="",
        ),
        target=TargetRef(kind="global"),
        payload={"open": True},
    )


def _scoped_actor(conn, project_ids: tuple[int, ...]) -> None:
    """An actor who can see exactly these projects, and nothing else."""
    conn.execute(
        "INSERT INTO actors (id, kind, name, created_at) "
        "VALUES (%s, 'human', 'Scoped Reader', %s) ON CONFLICT (id) DO NOTHING",
        (_SCOPED_ACTOR_ID, _iso()),
    )
    conn.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (%s, 'open-roster-reader', 'test role', %s) "
        "ON CONFLICT (id) DO NOTHING",
        (_SCOPED_ROLE_ID, _iso()),
    )
    for project_id in project_ids:
        conn.execute(
            "INSERT INTO actor_project_roles "
            "(actor_id, project_id, role_id, granted_at) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (_SCOPED_ACTOR_ID, project_id, _SCOPED_ROLE_ID, _iso()),
        )
    conn.commit()


def _insert_steering_claim(conn, session_id: str, project_id: int) -> None:
    target = make_steering_target(project_id)
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claimed_at, last_heartbeat, reason) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        (
            session_id,
            target.kind,
            target.scope_json(),
            _iso(),
            _iso(),
            "steering",
        ),
    )
    conn.commit()


def _second_project(conn) -> int:
    conn.execute(
        "INSERT INTO projects (id, slug, name, created_at) "
        "VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
        (88, "other", "Other", _iso()),
    )
    conn.commit()
    return 88


class TestOpenRosterSinglePass:
    def test_a_caller_who_can_see_no_project_sees_no_sessions(self, test_db):
        _insert_session(test_db, "hidden", last_heartbeat=_iso())
        test_db.execute(
            "INSERT INTO actors (id, kind, name, created_at) "
            "VALUES (%s, 'human', 'Unscoped Reader', %s) "
            "ON CONFLICT (id) DO NOTHING",
            (_SCOPED_ACTOR_ID, _iso()),
        )
        test_db.commit()

        outcome = handle_sessions_list(_open_request())

        assert outcome.primary_success
        assert outcome.result_payload["rows"] == []

    def test_every_visible_project_is_read_in_one_pass(self, test_db, monkeypatch):
        other = _second_project(test_db)
        _scoped_actor(test_db, (1, other))
        _insert_session(test_db, "home-1", last_heartbeat=_iso())
        _insert_session(test_db, "other-1", last_heartbeat=_iso(1), project_id=other)

        passes = []
        real_list_sessions = sessions_list_read.list_sessions

        def counted(**kwargs):
            passes.append(kwargs)
            return real_list_sessions(**kwargs)

        monkeypatch.setattr(sessions_list_read, "list_sessions", counted)
        outcome = handle_sessions_list(_open_request())

        assert outcome.primary_success
        assert len(passes) == 1
        shown = {row["session_id"] for row in outcome.result_payload["rows"]}
        assert {"home-1", "other-1"} <= shown

    def test_a_steering_claim_still_shows_the_holder_under_that_project(
        self, test_db,
    ):
        other = _second_project(test_db)
        _scoped_actor(test_db, (1, other))
        # A session that lives in project 1 but steers the other project: it
        # belongs to both groups, and appears exactly once.
        _insert_session(test_db, "steerer", last_heartbeat=_iso())
        _insert_steering_claim(test_db, "steerer", other)

        outcome = handle_sessions_list(_open_request())

        rows = outcome.result_payload["rows"]
        appearances = [row for row in rows if row["session_id"] == "steerer"]
        assert len(appearances) == 1

    def test_the_roster_groups_by_project_in_project_id_order(self, test_db):
        other = _second_project(test_db)
        _scoped_actor(test_db, (1, other))
        # The other project's session is the most recently active, so a flat
        # activity ordering would put it first; the grouped roster does not.
        _insert_session(test_db, "home-older", last_heartbeat=_iso(30))
        _insert_session(test_db, "other-newest", last_heartbeat=_iso(), project_id=other)

        outcome = handle_sessions_list(_open_request())

        order = [row["session_id"] for row in outcome.result_payload["rows"]]
        assert order.index("home-older") < order.index("other-newest")
