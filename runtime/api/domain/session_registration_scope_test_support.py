# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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
