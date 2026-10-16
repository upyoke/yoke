"""Registration fixes exclusive ownership once across retries and surfaces."""

from contextlib import closing, contextmanager
import json
import sqlite3
from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.session_model_facts import facts_from_mapping
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import actor_permissions
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.session_actor_binding import ACTOR_INVALID
from yoke_core.domain import session_actor_binding, session_scope_identity
from yoke_core.api.routes import sessions_lifecycle as routes
from yoke_core.domain.external_identities import default_org_id
from yoke_core.domain.handlers import sessions_begin, sessions_identity
from yoke_core.domain import sessions_lifecycle_registry as registry
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_identity_read import resolve_session_identity
from yoke_core.domain.sessions_lifecycle_identity import resolve_session_project_id


@pytest.fixture
def world(test_db, monkeypatch):
    conn = test_db
    owner = seed_human_actor(conn, "Registration member")
    stranger = seed_human_actor(conn, "Registration nonmember")
    org = default_org_id(conn)
    actor_permissions.grant_actor_org_role(
        conn, actor_id=owner, org_id=org, role_name="operator"
    )
    conn.commit()
    events = []
    monkeypatch.setattr(
        registry._sa, "_emit_session_event", lambda *a, **kw: events.append(kw)
    )

    @contextmanager
    def connected():
        yield conn

    monkeypatch.setattr(sessions_begin, "_connect_rw", connected)
    monkeypatch.setattr(sessions_identity, "_connect_rw", connected)
    monkeypatch.setattr(sessions_identity, "_max_chain_steps", lambda: 3)
    return SimpleNamespace(
        conn=conn, owner=owner, stranger=stranger, org=org, events=events
    )


def register(w, sid="registration", **overrides):
    args = dict(
        session_id=sid,
        executor="codex-cli",
        provider="openai",
        model_facts=facts_from_mapping({"requested_model": "gpt-5"}),
        workspace="/tmp/registration",
        project_id=None,
        machine_scope=True,
        actor_id=w.owner,
    )
    args.update(overrides)
    return registry.register_session(w.conn, **args)


def stored(w, sid="registration"):
    return dict(
        w.conn.execute(
            "SELECT * FROM harness_sessions WHERE session_id=%s", (sid,)
        ).fetchone()
    )


def request(w, payload=None, sid="public-registration", function="sessions.begin"):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=str(w.owner), session_id=sid),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def test_machine_scope_registration_stores_org_without_synthetic_project(world):
    w = world
    before = w.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    row = register(w)
    assert (row["project_id"], row["org_id"], row["actor_id"]) == (None, w.org, w.owner)
    assert w.conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == before
    context = w.events[-1]["context"]
    assert (context["project_id"], context["org_id"], context["scope_kind"]) == (
        None,
        w.org,
        "org",
    )


@pytest.mark.parametrize(
    "kwargs,code",
    [
        ({"project_id": 999999, "machine_scope": False}, "PROJECT_NOT_FOUND"),
        ({"project_id": 0, "machine_scope": False}, "PROJECT_ID_INVALID"),
        ({"project_id": "bad", "machine_scope": False}, "PROJECT_ID_INVALID"),
        ({"project_id": 1}, "SESSION_SCOPE_AMBIGUOUS"),
        ({"machine_scope": False}, "SESSION_SCOPE_AMBIGUOUS"),
        ({"actor_id": 999999}, ACTOR_INVALID),
    ],
)
def test_invalid_registration_refuses_without_row(world, kwargs, code):
    with pytest.raises(SessionError) as caught:
        register(world, **kwargs)
    assert caught.value.code == code
    assert "recovery" in str(caught.value).lower()
    assert (
        world.conn.execute(
            "SELECT COUNT(*) FROM harness_sessions WHERE session_id='registration'"
        ).fetchone()[0]
        == 0
    )


def test_nonmember_cannot_register_machine_scope(world):
    with pytest.raises(SessionError) as caught:
        register(world, actor_id=world.stranger)
    assert caught.value.code == "SESSION_ORG_MEMBERSHIP_REQUIRED"
    assert "membership" in str(caught.value) and "Recovery:" in str(caught.value)
    assert (
        world.conn.execute(
            "SELECT COUNT(*) FROM harness_sessions WHERE session_id='registration'"
        ).fetchone()[0]
        == 0
    )


def test_missing_projects_table_still_refuses_with_recovery():
    with closing(sqlite3.connect(":memory:")) as conn:
        with pytest.raises(SessionError) as caught:
            resolve_session_project_id(conn, 1)
    assert caught.value.code == "PROJECTS_TABLE_REQUIRED"
    assert "restore the authority's schema" in str(caught.value)


@pytest.mark.parametrize("surface", ["claude-code", "codex-cli", "cursor-cli"])
@pytest.mark.parametrize("initial_project", [None, 1])
@pytest.mark.parametrize("ended", [False, True])
def test_duplicate_and_reactivation_keep_scope_after_cwd_change(
    world, surface, initial_project, ended
):
    w = world
    register(
        w,
        executor=surface,
        project_id=initial_project,
        machine_scope=initial_project is None,
    )
    if ended:
        w.conn.execute(
            "UPDATE harness_sessions SET ended_at=%s WHERE session_id='registration'",
            (utc_now(),),
        )
        w.conn.commit()
    opposite = dict(
        project_id=1 if initial_project is None else None,
        machine_scope=initial_project is not None,
        executor=surface,
        workspace="/tmp/another-folder",
    )
    if ended:
        register(w, **opposite)
        assert stored(w)["ended_at"] is None
        assert w.events[-1]["context"]["scope_kind"] == (
            "org" if initial_project is None else "project"
        )
    else:
        with pytest.raises(SessionError) as caught:
            register(w, **opposite)
        assert caught.value.code == "SESSION_EXISTS"
    row = stored(w)
    assert (row["project_id"], row["org_id"]) == (
        initial_project,
        w.org if initial_project is None else None,
    )
    if ended:
        assert row["workspace"] == "/tmp/another-folder"


@pytest.mark.parametrize("ended", [False, True])
def test_reregistration_other_project_refuses_before_identity_mutation(world, ended):
    w = world
    register(w, project_id=1, machine_scope=False)
    if ended:
        w.conn.execute(
            "UPDATE harness_sessions SET ended_at=%s WHERE session_id='registration'",
            (utc_now(),),
        )
        w.conn.commit()
    before = stored(w)
    with pytest.raises(SessionError) as caught:
        register(w, project_id=2, machine_scope=False, workspace="/tmp/other-project")
    assert caught.value.code == "SESSION_SCOPE_IMMUTABLE"
    assert "open a new session in that folder" in str(caught.value)
    assert stored(w) == before


@pytest.mark.parametrize("project", [None, 1])
def test_identity_read_returns_stored_scope(world, project):
    w = world
    register(w, project_id=project, machine_scope=project is None)
    identity = resolve_session_identity(w.conn, "registration")
    assert (identity.project_id, identity.org_id, identity.scope_kind) == (
        project,
        w.org if project is None else None,
        "org" if project is None else "project",
    )
    result = sessions_identity.handle_identity(
        request(w, sid="registration", function="sessions.identity")
    ).result_payload
    assert (result["project_id"], result["org_id"], result["scope_kind"]) == (
        identity.project_id,
        identity.org_id,
        identity.scope_kind,
    )
    if project is None:
        assert result["project_slug"] is None


@pytest.mark.parametrize("project", [None, 1])
def test_public_begin_threads_scope_and_authenticated_actor(world, project):
    w = world
    payload = dict(
        executor="codex-cli",
        provider="openai",
        workspace="/tmp/home",
        actor_id=w.stranger,
        org_id=999999,
    )
    payload.update(
        {"machine_scope": True} if project is None else {"project_id": project}
    )
    outcome = sessions_begin.handle_begin(request(w, payload))
    assert outcome.error is None
    row = outcome.result_payload["session"]
    assert (row["project_id"], row["org_id"], row["actor_id"]) == (
        project,
        w.org if project is None else None,
        w.owner,
    )
    retry = sessions_begin.handle_begin(request(w, payload))
    assert (
        retry.result_payload["success"] and retry.result_payload["already_registered"]
    )


@pytest.mark.parametrize("scope", [{}, {"project_id": 1, "machine_scope": True}])
def test_public_begin_rejects_ambiguous_scope(world, scope):
    payload = dict(
        executor="codex-cli", provider="openai", workspace="/tmp/home", **scope
    )
    outcome = sessions_begin.handle_begin(request(world, payload))
    assert outcome.error.code == "session_scope_ambiguous"
    assert "Recovery:" in outcome.error.message
    assert (
        world.conn.execute(
            "SELECT COUNT(*) FROM harness_sessions WHERE session_id='public-registration'"
        ).fetchone()[0]
        == 0
    )


def test_unavailable_authority_org_refuses_without_row(world, monkeypatch):
    def unavailable(conn):
        raise LookupError("authority organization unavailable")

    monkeypatch.setattr(session_scope_identity, "default_org_id", unavailable)
    with pytest.raises(SessionError) as caught:
        register(world)
    assert caught.value.code == "SESSION_ORG_UNRESOLVED"
    assert "Recovery:" in str(caught.value)
    assert (
        world.conn.execute(
            "SELECT COUNT(*) FROM harness_sessions WHERE session_id='registration'"
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("project", [None, 1])
def test_sessions_route_uses_the_same_scope_writer(world, monkeypatch, project):
    w = world

    class Connection:
        def __getattr__(self, name):
            return getattr(w.conn, name)

        def close(self):
            pass

    monkeypatch.setattr(
        routes,
        "_main_api",
        lambda: SimpleNamespace(get_db_readwrite=lambda: Connection()),
    )
    monkeypatch.setattr(
        session_actor_binding,
        "resolve_operating_actor",
        lambda conn: session_actor_binding.explicit_actor_binding(conn, w.owner),
    )
    payload = dict(
        session_id="route-registration",
        executor="codex-cli",
        provider="openai",
        workspace="/tmp/home",
    )
    payload.update(
        {"machine_scope": True} if project is None else {"project_id": project}
    )
    response = routes.api_register_session(routes.RegisterSessionRequest(**payload))
    assert response.status_code == 201
    row = json.loads(response.body)
    assert (row["project_id"], row["org_id"], row["actor_id"]) == (
        project,
        w.org if project is None else None,
        w.owner,
    )
    assert stored(w, "route-registration")["project_id"] == project
