"""Ended-history paging and compact projection for ``sessions.list``."""

from __future__ import annotations

import pytest

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.session_control_schema import create_session_control_tables
from yoke_core.domain.sessions_history_read import HISTORY_FIELDS


def _request(history: object, *, actor_id: int | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(
            actor_id=str(actor_id) if actor_id is not None else None,
            session_id="",
        ),
        target=TargetRef(kind="global"),
        payload={"history": history},
    )


def _insert_session(
    conn,
    session_id: str,
    *,
    ended_at: str | None,
    project_id: int = 1,
    executor: str = "codex",
    executor_surface: str = "codex-cli",
    model: str = "served-model",
    requested_model: str = "requested-model",
    machine_id: str = "machine-one",
    actor_id: int | None = None,
    recent_item_id: str | None = None,
    terminated_at: str | None = None,
) -> None:
    activity = ended_at or "2026-09-08T02:00:00Z"
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, executor_surface, provider, model, requested_model, "
        "workspace, project_id, mode, offered_at, last_heartbeat, last_tool_call_at, "
        "tool_call_count, ended_at, terminated_at, termination_reason, machine_id, "
        "actor_id, recent_item_id"
        ") VALUES (%s, %s, %s, 'openai', %s, %s, '/tmp/workspace', %s, "
        "'wait', %s, %s, %s, 1, %s, %s, %s, %s, %s, %s)",
        (
            session_id, executor, executor_surface, model, requested_model,
            project_id, activity, activity, activity, ended_at, terminated_at,
            "operator stop" if terminated_at else None, machine_id, actor_id,
            recent_item_id,
        ),
    )
    conn.commit()


def _prepare(conn) -> None:
    create_session_control_tables(conn)
    from yoke_core.domain.actors import seed_system_actor

    actor_id = seed_system_actor(conn, "test-component")
    conn.execute(
        "INSERT INTO session_relays ("
        "relay_id, machine_id, first_seen_at, last_seen_at, connected_until, "
        "state, hostname, actor_id, surface_versions, project_checkouts) "
        "VALUES ('relay-one', 'machine-one', %s, %s, %s, 'idle', 'studio', "
        "%s, '{}', '{}') "
        "ON CONFLICT (relay_id) DO NOTHING",
        (*(("2026-09-01T00:00:00Z",) * 3), actor_id),
    )
    conn.commit()


def test_history_is_compact_and_does_not_run_live_enrichment(test_db, monkeypatch):
    from runtime.api.fixtures.backlog import insert_item

    _prepare(test_db)
    insert_item(test_db, id=41, project_sequence=401, title="Archived work")
    _insert_session(
        test_db, "ended-one", ended_at="2026-09-08T03:00:00Z",
        recent_item_id="41",
    )
    _insert_session(test_db, "open-one", ended_at=None)

    def refuse_live_enrichment(*_args, **_kwargs):
        raise AssertionError("history must not execute live roster enrichment")

    monkeypatch.setattr(
        "yoke_core.domain.session_control_roster.session_control_roster_result",
        refuse_live_enrichment,
    )
    outcome = handle_sessions_list(_request({"limit": 50}))

    assert outcome.primary_success
    result = outcome.result_payload
    assert result["fields"] == list(HISTORY_FIELDS)
    assert result["matched_count"] == 1
    assert result["next_cursor"] is None
    assert [row["session_id"] for row in result["rows"]] == ["ended-one"]
    row = result["rows"][0]
    assert row["recent_item"] == "YOK-401"
    assert row["recent_item_title"] == "Archived work"
    assert row["machine_name"] == "studio"
    assert row["ended_cause"] == "wound_down"
    for live_only in (
        "claims", "holdings", "messageability", "native_process", "relay",
        "health", "current_item_held_by_other_session_id",
    ):
        assert live_only not in row


@pytest.mark.parametrize("terminated_at", [None, "2026-09-08T04:00:00Z"])
def test_history_projects_ended_state_without_inventing_custody(test_db, terminated_at):
    _prepare(test_db)
    ended_at = "2026-09-08T03:00:00Z"
    tool_at = "2026-09-08T02:30:00Z"
    _insert_session(test_db, "ended", ended_at=ended_at, terminated_at=terminated_at)
    test_db.execute(
        "UPDATE harness_sessions SET mode = 'parked', quiet_reason = %s, "
        "last_tool_call_at = %s WHERE session_id = 'ended'",
        ("Waiting for review", tool_at),
    )
    test_db.commit()

    row = handle_sessions_list(_request({})).result_payload["rows"][0]
    state = row["session_state"]
    assert state["presence"] == "ended"
    assert state["activity"] == "silent"
    assert state["in_flight"] is False
    assert state["intent"]["state"] == "parked"
    assert state["intent"]["reason"] == "Waiting for review"
    assert state["custody"] == {
        "holds": [], "holds_work_claim": None, "reclaimable": None,
        "reason": "custody_facts_unavailable",
    }
    assert row["next_actor"] == state["next_actor"]
    assert row["next_actor"]["actor"] == "nobody"
    assert row["next_actor"]["reason"] == "session_ended"
    assert parse_instant(row["next_actor"]["since"]) == parse_instant(terminated_at or ended_at)
    assert parse_instant(row["last_tool_call_at"]) == parse_instant(tool_at)


def test_history_cursor_pages_tied_activity_without_duplicates(test_db):
    _prepare(test_db)
    stamp = "2026-09-08T03:00:00Z"
    for session_id in ("session-a", "session-c", "session-b"):
        _insert_session(test_db, session_id, ended_at=stamp)

    first = handle_sessions_list(_request({"limit": 2})).result_payload
    second = handle_sessions_list(_request({
        "limit": 2, "cursor": first["next_cursor"],
    })).result_payload

    assert first["matched_count"] == second["matched_count"] == 3
    assert [row["session_id"] for row in first["rows"]] == [
        "session-c", "session-b",
    ]
    assert [row["session_id"] for row in second["rows"]] == ["session-a"]
    assert second["next_cursor"] is None


def test_history_search_filters_and_facets_cover_full_scope(test_db):
    from runtime.api.fixtures.backlog import insert_item
    from yoke_core.domain.actors import seed_human_actor
    from yoke_core.domain.actors import set_actor_name

    _prepare(test_db)
    actor_id = seed_human_actor(test_db)
    set_actor_name(test_db, actor_id, "History Operator")
    insert_item(test_db, id=42, project_sequence=402, title="Needle Project")
    _insert_session(
        test_db, "target", ended_at="2026-09-08T03:00:00Z",
        actor_id=actor_id, recent_item_id="42",
    )
    _insert_session(
        test_db, "other", ended_at="2026-09-08T02:00:00Z",
        executor="claude-code", executor_surface="claude-cli",
        machine_id="machine-two", model="other-model",
        requested_model="other-request",
    )

    for query in (
        "target", "needle project", "history operator",
        "served-model", "requested-model",
    ):
        searched = handle_sessions_list(_request({"search": query})).result_payload
        assert [row["session_id"] for row in searched["rows"]] == ["target"]
    project_search = handle_sessions_list(_request({"search": "yoke"})).result_payload
    assert {row["session_id"] for row in project_search["rows"]} == {"target", "other"}

    result = handle_sessions_list(_request({
        "search": "history operator",
        "harnesses": ["codex-cli"],
        "machines": ["machine-one"],
    })).result_payload

    assert [row["session_id"] for row in result["rows"]] == ["target"]
    assert result["matched_count"] == 1
    assert set(result["facets"]["harnesses"]) >= {"codex-cli", "claude-cli"}
    assert {row["id"] for row in result["facets"]["machines"]} == {
        "machine-one", "machine-two",
    }


def test_invisible_project_filter_returns_empty_instead_of_unscoped(test_db):
    from yoke_core.domain.actors import seed_human_actor

    _prepare(test_db)
    actor_id = seed_human_actor(test_db)
    test_db.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
        "VALUES (77, 'other', 'Other', 'OTH', %s)",
        ("2026-09-08T00:00:00Z",),
    )
    test_db.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (9001, 'history-reader', 'test role', %s)",
        ("2026-09-08T00:00:00Z",),
    )
    role_id = 9001
    test_db.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at) VALUES (%s, 1, %s, %s)",
        (actor_id, role_id, "2026-09-08T00:00:00Z"),
    )
    test_db.commit()
    _insert_session(test_db, "visible", ended_at="2026-09-08T03:00:00Z")
    _insert_session(
        test_db, "invisible", ended_at="2026-09-08T02:00:00Z", project_id=77,
    )

    result = handle_sessions_list(_request(
        {"projects": ["other"]}, actor_id=actor_id,
    )).result_payload
    assert result["rows"] == []
    assert result["matched_count"] == 0
    open_request = FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=str(actor_id), session_id=""),
        target=TargetRef(kind="global"),
        payload={"open": True, "projects": ["other"], "limit": 500},
    )
    assert handle_sessions_list(open_request).result_payload["rows"] == []


def test_history_validation_names_first_page_recovery(test_db):
    _prepare(test_db)
    malformed = handle_sessions_list(_request({"cursor": "not-a-cursor"}))
    oversized = handle_sessions_list(_request({"limit": 101}))
    mixed = FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={"history": {}, "open": True},
    )

    assert not malformed.primary_success
    assert malformed.error.code == "payload_invalid"
    assert "reload the first history page" in malformed.error.message
    assert malformed.error.jsonpath == "$.payload.history.cursor"
    assert not oversized.primary_success
    assert "reload the first history page" in oversized.error.message
    assert not handle_sessions_list(mixed).primary_success
