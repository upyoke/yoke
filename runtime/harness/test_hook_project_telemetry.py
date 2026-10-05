"""Hook and guard events retain the caller's project instead of the serving tree."""

import sqlite3
from types import SimpleNamespace

import pytest

from yoke_core.domain import events, events_project_identity as identity
from yoke_core.domain import path_claim_bash_guard, path_claim_pre_edit_guard
from yoke_core.hooks import telemetry, stdin, dispatch_dedup
from yoke_core.domain import path_claims_dependency_events as dependency_events
from yoke_core.domain import path_claims_blocked_coordination_repair as repair
from yoke_core.domain import path_claims_blocked_reason_refresh as refresh


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.execute("CREATE TABLE items (id INTEGER, project_id INTEGER)")
    connection.execute("INSERT INTO items VALUES (6, 42)")
    connection.execute(
        "CREATE TABLE harness_sessions (session_id TEXT, project_id INTEGER)"
    )
    connection.execute("INSERT INTO harness_sessions VALUES ('worker', 42)")
    yield connection
    connection.close()


@pytest.mark.parametrize("session_id,expected", [("worker", 42), ("unknown", None)])
def test_server_event_uses_session_owner(conn, session_id, expected, monkeypatch):
    from yoke_contracts import project_defaults

    monkeypatch.setattr(
        project_defaults,
        "default_project_for_directory",
        lambda _: pytest.fail("server cwd cannot identify its caller"),
    )
    assert (
        identity.working_project_for_event(conn=conn, session_id=session_id) == expected
    )


def test_item_owner_precedes_session_owner(conn):
    conn.execute("INSERT INTO harness_sessions VALUES ('other', 9)")
    assert (
        identity.working_project_for_event(conn=conn, item_id=6, session_id="other")
        == 42
    )
    assert identity.working_project_for_event(conn=conn, item_id=999) is None


@pytest.mark.parametrize("project", ["42", None])
def test_local_hook_stamps_mapped_project_or_none(monkeypatch, project):
    from yoke_contracts import project_defaults

    monkeypatch.setattr(
        project_defaults, "default_project_for_directory", lambda _: project
    )
    monkeypatch.setattr(stdin, "default_project_for_directory", lambda _: project)
    monkeypatch.setattr(
        dispatch_dedup, "default_project_for_directory", lambda _: project
    )
    monkeypatch.setattr(stdin, "_stamp_first_user_prompt", lambda _: None)
    calls = []
    monkeypatch.setattr(events, "emit_event", lambda *a, **kw: calls.append(kw))
    telemetry._emit_hook_event(
        "HookDispatchTelemetry",
        event_type="hook_dispatch",
        severity="INFO",
        outcome="completed",
        module="runner",
        hook_event="Stop",
        executor="codex",
        session_id="unknown",
    )
    stdin.emit_session_hook_failed(
        hook_event="Stop",
        executor="codex",
        reason="timeout",
        latency_ms=1,
        stdin_state="empty",
        session_id_source="payload",
    )
    stdin.emit_harness_session_sent_first_user_prompt_submit("", "unknown")
    dispatch_dedup.emit_hook_dispatch_deduplicated(
        event_name="Stop", session_id="unknown", executor="codex", run_half="client"
    )
    assert len(calls) == 4
    assert all(call["project"] == project for call in calls)


@pytest.mark.parametrize("guard", [path_claim_bash_guard, path_claim_pre_edit_guard])
def test_guard_denial_uses_durable_session_project(conn, monkeypatch, guard):
    calls = []
    monkeypatch.setattr(events, "emit_event", lambda *a, **kw: calls.append(kw))
    record = SimpleNamespace(session_id="worker", cwd="/unmapped", tool_kind="Edit")
    verdict = SimpleNamespace(
        bash_verb="write", target_path="app.py", claim_id=1, failure_mode="out-of-claim"
    )
    guard._emit_denial(record=record, verdict=verdict, conn=conn)
    assert calls[0]["project"] == 42


@pytest.mark.parametrize(
    "emitter,extra",
    [
        (dependency_events.emit_blocked_reason_refreshed, {"released_claim_id": 2}),
        (repair._emit_repair_event, {"directional_release": False}),
        (refresh._emit_refresh_event, {"dependent_item_id": 6, "blocking_item_id": 7}),
    ],
)
def test_claim_dependency_event_uses_item_project(conn, monkeypatch, emitter, extra):
    calls = []
    monkeypatch.setattr(events, "emit_event", lambda *a, **kw: calls.append(kw))
    kwargs = dict(conn=conn, claim_id=1, item_id=6, prior_blocked_reason="old", **extra)
    if emitter is not repair._emit_repair_event:
        kwargs["new_blocked_reason"] = "new"
    emitter(**kwargs)
    assert calls[0]["project"] == 42
