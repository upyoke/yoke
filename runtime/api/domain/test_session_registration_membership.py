"""Registration retries authorize the immutable scope they retain."""

import pytest
from uuid import uuid4

from runtime.api.domain.test_session_registration_scope import (
    register,
    request,
    stored,
    world as world,
)
from yoke_contracts.session_model_facts import facts_from_mapping
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import actor_permissions, session_scope_identity
from yoke_core.domain.handlers import sessions_begin
from yoke_core.domain.sessions_analytics import SessionError


def prepare_retry(w, ended):
    register(w)
    if ended:
        w.conn.execute(
            "UPDATE harness_sessions SET ended_at=%s WHERE session_id='registration'",
            (utc_now(),),
        )
        w.conn.commit()


def retry(w, boundary):
    payload = dict(
        executor="codex-cli",
        provider="openai",
        requested_model="gpt-5",
        requested_reasoning_effort="high",
        project_id=1,
        machine_scope=False,
        workspace="/tmp/another-registration-folder",
        executor_version="9.9.9",
        machine_id=str(uuid4()),
        native_thread_id="another-registration-thread",
    )
    if boundary == "public":
        outcome = sessions_begin.handle_begin(request(w, payload, sid="registration"))
        error = outcome.error
        return (error.code.upper(), error.message) if error else (None, "")
    facts = facts_from_mapping(payload)
    for key in ("requested_model", "requested_reasoning_effort"):
        payload.pop(key)
    try:
        register(w, model_facts=facts, **payload)
    except SessionError as error:
        return error.code, error.message
    return None, ""


def assert_refused_without_mutation(w, boundary, code):
    before = stored(w)
    events = list(w.events)
    observed, message = retry(w, boundary)
    assert observed == code, {
        "observed": observed,
        "row_unchanged": stored(w) == before,
        "events_unchanged": w.events == events,
    }
    assert "Recovery:" in message
    assert "yoke connection set" in message
    assert stored(w) == before
    assert w.events == events
    return message


@pytest.mark.parametrize("ended", [False, True])
@pytest.mark.parametrize("boundary", ["registry", "public"])
def test_retained_org_retry_requires_membership(world, ended, boundary):
    w = world
    prepare_retry(w, ended)
    w.conn.execute(
        "DELETE FROM actor_org_roles WHERE actor_id=%s AND org_id=%s",
        (w.owner, w.org),
    )
    w.conn.commit()
    assert_refused_without_mutation(w, boundary, "SESSION_ORG_MEMBERSHIP_REQUIRED")


@pytest.mark.parametrize("ended", [False, True])
@pytest.mark.parametrize("boundary", ["registry", "public"])
def test_retained_org_retry_rejects_a_different_authority(
    world, monkeypatch, ended, boundary
):
    w = world
    prepare_retry(w, ended)
    other = w.conn.execute(
        "INSERT INTO organizations(slug,name,created_at) VALUES (%s,%s,%s) RETURNING id",
        ("other-registration-authority", "Other registration authority", utc_now()),
    ).fetchone()[0]
    actor_permissions.grant_actor_org_role(
        w.conn, actor_id=w.owner, org_id=other, role_name="operator"
    )
    w.conn.commit()
    monkeypatch.setattr(session_scope_identity, "default_org_id", lambda conn: other)
    message = assert_refused_without_mutation(w, boundary, "SESSION_ORG_UNRESOLVED")
    assert str(other) not in message and str(w.org) not in message
    assert "other-registration-authority" not in message
