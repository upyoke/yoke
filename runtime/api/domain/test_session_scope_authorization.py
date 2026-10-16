"""Scope identity and authorization do not borrow another actor's authority."""

from contextlib import contextmanager
from dataclasses import FrozenInstanceError
import sqlite3
from types import SimpleNamespace

import pytest
from yoke_core.domain import session_scope_identity as scope
from yoke_core.domain.sessions_analytics import SessionError


@pytest.fixture
def conn():
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript("""
        CREATE TABLE organizations(id INTEGER);
        INSERT INTO organizations VALUES(7);
        CREATE TABLE actor_org_roles(actor_id INTEGER, org_id INTEGER);
        INSERT INTO actor_org_roles VALUES(1,7), (2,7), (3,8);
        CREATE TABLE projects(id INTEGER, slug TEXT);
        INSERT INTO projects VALUES(4,'garden');
        CREATE TABLE harness_sessions(session_id TEXT, actor_id INTEGER);
        INSERT INTO harness_sessions VALUES('owned',1), ('stranger',2);
    """)
    yield db
    db.close()


def test_scope_requires_exactly_one():
    for project, org in [(None, None), (1, 7)]:
        with pytest.raises(SessionError, match="exactly one"):
            scope.SessionScope(project, org)
    project = scope.session_scope_of({"project_id": 4, "org_id": None})
    assert project.kind == "project"
    assert scope.SessionScope(None, 7).kind == "org"
    with pytest.raises(FrozenInstanceError):
        project.project_id = 5


def test_org_from_authority_only(conn):
    assert scope.resolve_registration_scope(
        conn, actor_id=1, project_id=None, machine_scope=True
    ) == scope.SessionScope(None, 7)
    assert scope.resolve_registration_scope(
        conn, actor_id=1, project_id=4, machine_scope=False
    ) == scope.SessionScope(4, None)
    for project, machine in [(4, True), (None, False)]:
        with pytest.raises(SessionError) as refusal:
            scope.resolve_registration_scope(
                conn, actor_id=1, project_id=project, machine_scope=machine
            )
        assert refusal.value.code == "SESSION_SCOPE_AMBIGUOUS"
    with pytest.raises(TypeError):
        scope.resolve_registration_scope(
            conn, actor_id=1, project_id=None, machine_scope=True, org_id=8
        )


def test_non_member_refused_with_recovery(conn):
    with pytest.raises(SessionError) as refusal:
        scope.resolve_registration_scope(
            conn, actor_id=3, project_id=None, machine_scope=True
        )
    assert refusal.value.code == "SESSION_ORG_MEMBERSHIP_REQUIRED"
    assert str(refusal.value).endswith(
        "Recovery: reconnect with `yoke connection set` or ask an org admin for membership."
    )
    conn.execute("DELETE FROM organizations")
    with pytest.raises(SessionError) as refusal:
        scope.resolve_registration_scope(
            conn, actor_id=1, project_id=None, machine_scope=True
        )
    assert refusal.value.code == "SESSION_ORG_UNRESOLVED"


def test_operate_session_org_rules(conn, monkeypatch):
    monkeypatch.setattr(
        scope.actor_permissions,
        "org_permission_decision",
        lambda *a, **kw: SimpleNamespace(allowed=kw["actor_id"] == 2),
    )

    def allowed(actor, owner):
        return scope.actor_may_operate_session(
            conn,
            actor_id=actor,
            scope=scope.SessionScope(None, 7),
            session_actor_id=owner,
            permission_key="sessions.read",
        )

    assert allowed(1, 1)
    assert not allowed(None, None)
    assert allowed(2, 1)
    assert not allowed(1, 2)
    assert not allowed(3, 1)
    conn.execute("DELETE FROM actor_org_roles WHERE actor_id=1")
    assert allowed(1, 1)
    monkeypatch.setattr(
        scope.actor_permissions,
        "permission_decision",
        lambda *a, **kw: SimpleNamespace(
            allowed=kw["actor_id"] == 1 and kw["project_id"] == 4
        ),
    )
    assert scope.actor_may_operate_session(
        conn,
        actor_id=1,
        scope=scope.SessionScope(4, None),
        session_actor_id=2,
        permission_key="sessions.read",
    )
    assert not scope.actor_may_operate_session(
        conn,
        actor_id=3,
        scope=scope.SessionScope(4, None),
        session_actor_id=3,
        permission_key="sessions.read",
    )


@pytest.mark.parametrize(
    "project,org,machine,actor,relay_actor,expected",
    [
        (4, None, "other", 2, 1, True),
        (5, None, "same", 1, 1, False),
        (None, 7, "same", 1, 1, True),
        (None, 7, "other", 1, 1, False),
        (None, 7, "same", 2, 1, False),
        (None, 7, "same", 1, None, False),
        (None, None, "same", 1, 1, False),
        (4, 7, "same", 1, 1, False),
    ],
)
def test_relay_serves_scope_matrix(project, org, machine, actor, relay_actor, expected):
    assert (
        scope.relay_serves_scope(
            relay_machine_id="same",
            relay_actor_id=relay_actor,
            advertised_project_ids={4},
            row_machine_id=machine,
            row_project_id=project,
            row_org_id=org,
            row_actor_id=actor,
        )
        is expected
    )


@pytest.fixture
def hook_db(conn, monkeypatch):
    @contextmanager
    def connect():
        yield conn

    monkeypatch.setattr(scope.db_helpers, "connect", connect)


def test_hook_request_machine_scope_ownership(hook_db):
    assert scope.authorize_hook_request(1, None, ["owned", "new"]).denial_code is None
    denied = scope.authorize_hook_request(1, None, ["owned", "stranger"])
    assert denied.denial_code == "HOOK_SESSION_DENIED"
    assert "stranger" not in denied.reason
    assert (
        scope.authorize_hook_request(None, None, []).denial_code
        == "HOOK_SESSION_DENIED"
    )


def test_hook_request_project_visibility(hook_db, monkeypatch):
    monkeypatch.setattr(scope, "actor_visible_project_ids", lambda *a: {4})
    assert scope.authorize_hook_request(1, 4, []).project_slug == "garden"
    denied = scope.authorize_hook_request(1, 77, [])
    assert denied.denial_code == "HOOK_PROJECT_DENIED"
    assert "77" not in denied.reason


def test_hook_request_auth_unavailable(monkeypatch):
    def unavailable():
        raise RuntimeError("hidden project database error")

    monkeypatch.setattr(scope.db_helpers, "connect", unavailable)
    decision = scope.authorize_hook_request(1, 4, [])
    assert decision.denial_code == "HOOK_SCOPE_AUTH_UNAVAILABLE"
    assert "hidden" not in decision.reason
    assert "Recovery:" in decision.reason
