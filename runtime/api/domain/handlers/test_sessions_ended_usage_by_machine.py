"""Machine-tile ended-usage aggregate: `sessions.list` with `ended_last_24h`.

A machine card's "Ended in last 24h" figure sums the FULL cumulative
`usage_totals` of every session whose end fell in the trailing 24-hour
window, scoped to the caller's authorized projects — never just whatever
page of sessions happened to be loaded.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_contracts.session_usage_facts import (
    USAGE_COMPLETE,
    ModelUsage,
    SessionUsage,
    usage_document,
)
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.session_control_schema import create_session_control_tables


def _iso(hours_ago: float = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _usage(tokens: int) -> str:
    return usage_document(SessionUsage(
        status=USAGE_COMPLETE,
        models=(ModelUsage(model="test-model", input=tokens),),
    ))


def _insert_session(
    conn,
    session_id: str,
    *,
    ended_at: str | None = None,
    terminated_at: str | None = None,
    machine_id: str | None = "machine-one",
    project_id: int = 1,
    usage_tokens: int | None = 1_000,
) -> None:
    # `offered_at` equal to the end stamp, paired with `tool_call_count = 0`,
    # is exactly what the probe predicate reads as a harness startup probe
    # rather than a real session — a nonzero count keeps this fixture out of
    # that exclusion regardless of the timestamps under test.
    activity = ended_at or terminated_at or _iso()
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, mode, offered_at, last_heartbeat, tool_call_count, "
        "ended_at, terminated_at, machine_id, usage_totals"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, %s)",
        (
            session_id, "claude-code", "anthropic", "test-model", "primary",
            "/tmp/workspace", project_id, "wait", activity, activity,
            ended_at, terminated_at, machine_id,
            _usage(usage_tokens) if usage_tokens is not None else None,
        ),
    )
    conn.commit()


def _request(*, actor_id: int | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(
            actor_id=str(actor_id) if actor_id is not None else None,
            session_id="",
        ),
        target=TargetRef(kind="global"),
        payload={"ended_last_24h": True},
    )


def test_cutoff_includes_only_sessions_ended_within_24h(test_db):
    create_session_control_tables(test_db)
    test_db.commit()
    _insert_session(test_db, "recent", ended_at=_iso(1), usage_tokens=1_000)
    _insert_session(test_db, "old", ended_at=_iso(25), usage_tokens=5_000)

    outcome = handle_sessions_list(_request())
    assert outcome.primary_success
    rows = outcome.result_payload["rows"]
    assert [row["session_id"] for row in rows] == ["recent"]
    assert rows[0]["usage_tokens"] == 1_000


def test_killed_session_is_dated_by_its_termination_stamp(test_db):
    create_session_control_tables(test_db)
    test_db.commit()
    # A killed session may carry only `terminated_at`; the window must not
    # silently drop it for lacking `ended_at`.
    _insert_session(
        test_db, "killed-recent", terminated_at=_iso(2), usage_tokens=750,
    )
    _insert_session(
        test_db, "killed-old", terminated_at=_iso(30), usage_tokens=999,
    )

    rows = handle_sessions_list(_request()).result_payload["rows"]
    assert [row["session_id"] for row in rows] == ["killed-recent"]


def test_active_session_is_excluded_even_with_recorded_usage(test_db):
    create_session_control_tables(test_db)
    test_db.commit()
    _insert_session(test_db, "still-active", usage_tokens=2_000)
    _insert_session(test_db, "ended", ended_at=_iso(1), usage_tokens=500)

    rows = handle_sessions_list(_request()).result_payload["rows"]
    assert [row["session_id"] for row in rows] == ["ended"]


def test_sessions_with_no_machine_are_skipped(test_db):
    create_session_control_tables(test_db)
    test_db.commit()
    _insert_session(
        test_db, "unattributed", ended_at=_iso(1), machine_id=None, usage_tokens=100,
    )
    _insert_session(
        test_db, "attributed", ended_at=_iso(1), machine_id="machine-one",
        usage_tokens=100,
    )

    rows = handle_sessions_list(_request()).result_payload["rows"]
    assert [row["session_id"] for row in rows] == ["attributed"]


def test_totals_are_pagination_independent(test_db):
    create_session_control_tables(test_db)
    test_db.commit()
    for index in range(5):
        _insert_session(
            test_db, f"ended-{index}", ended_at=_iso(1), usage_tokens=100,
        )

    result = handle_sessions_list(_request()).result_payload
    # Every matching session comes back in one read — a machine tile's total
    # must answer for the whole window, not one page of it.
    assert len(result["rows"]) == 5
    assert sum(row["usage_tokens"] for row in result["rows"]) == 500
    assert "next_cursor" not in result
    assert "matched_count" not in result


def test_scoped_by_machine_and_authorized_project(test_db):
    from yoke_core.domain.actors import seed_human_actor

    create_session_control_tables(test_db)
    test_db.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
        "VALUES (77, 'other', 'Other', 'OTH', %s)",
        (_iso(),),
    )
    test_db.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (9101, 'ended-usage-reader', 'test role', %s)",
        (_iso(),),
    )
    actor_id = seed_human_actor(test_db)
    test_db.execute(
        "INSERT INTO actor_project_roles (actor_id, project_id, role_id, granted_at) "
        "VALUES (%s, 1, 9101, %s)",
        (actor_id, _iso()),
    )
    test_db.commit()
    _insert_session(
        test_db, "visible", ended_at=_iso(1), project_id=1,
        machine_id="machine-a", usage_tokens=100,
    )
    _insert_session(
        test_db, "invisible", ended_at=_iso(1), project_id=77,
        machine_id="machine-b", usage_tokens=999,
    )

    rows = handle_sessions_list(
        _request(actor_id=actor_id)
    ).result_payload["rows"]
    assert [row["session_id"] for row in rows] == ["visible"]
    assert {row["machine_id"] for row in rows} == {"machine-a"}
    assert rows[0]["project_id"] == 1


def test_explicit_projects_narrows_within_actor_visibility(test_db):
    from yoke_core.domain.actors import seed_human_actor

    create_session_control_tables(test_db)
    test_db.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, created_at) "
        "VALUES (77, 'other', 'Other', 'OTH', %s)",
        (_iso(),),
    )
    test_db.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (9102, 'ended-usage-reader-2', 'test role', %s)",
        (_iso(),),
    )
    actor_id = seed_human_actor(test_db)
    for project_id in (1, 77):
        test_db.execute(
            "INSERT INTO actor_project_roles "
            "(actor_id, project_id, role_id, granted_at) VALUES (%s, %s, 9102, %s)",
            (actor_id, project_id, _iso()),
        )
    test_db.commit()
    _insert_session(
        test_db, "project-one", ended_at=_iso(1), project_id=1,
        machine_id="machine-a", usage_tokens=100,
    )
    _insert_session(
        test_db, "project-77", ended_at=_iso(1), project_id=77,
        machine_id="machine-b", usage_tokens=200,
    )

    request = FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=str(actor_id), session_id=""),
        target=TargetRef(kind="global"),
        payload={"ended_last_24h": True, "projects": ["1"]},
    )
    # The actor can see both projects, but the request named exactly one —
    # scoping must honor that, not fall back to every visible project.
    rows = handle_sessions_list(request).result_payload["rows"]
    assert [row["session_id"] for row in rows] == ["project-one"]


def test_unresolvable_project_ref_yields_no_rows(test_db):
    create_session_control_tables(test_db)
    test_db.commit()
    _insert_session(test_db, "ended", ended_at=_iso(1), usage_tokens=100)

    request = FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={"ended_last_24h": True, "projects": ["nope"]},
    )
    assert handle_sessions_list(request).result_payload["rows"] == []


def test_future_ended_at_is_included_not_just_the_recent_past(test_db):
    create_session_control_tables(test_db)
    test_db.commit()
    _insert_session(test_db, "future", ended_at=_iso(-1), usage_tokens=42)

    rows = handle_sessions_list(_request()).result_payload["rows"]
    assert [row["session_id"] for row in rows] == ["future"]


def test_ended_at_takes_priority_over_terminated_at_for_the_cutoff(test_db):
    create_session_control_tables(test_db)
    test_db.commit()
    # ended_at recent, terminated_at stale: COALESCE picks ended_at -> in.
    _insert_session(
        test_db, "ended-recent-terminated-old",
        ended_at=_iso(1), terminated_at=_iso(30), usage_tokens=100,
    )
    # ended_at stale, terminated_at recent: COALESCE still prefers the
    # non-null ended_at -> excluded, even though terminated_at alone
    # would fall inside the window.
    _insert_session(
        test_db, "ended-old-terminated-recent",
        ended_at=_iso(30), terminated_at=_iso(1), usage_tokens=200,
    )

    rows = handle_sessions_list(_request()).result_payload["rows"]
    assert [row["session_id"] for row in rows] == ["ended-recent-terminated-old"]


def test_history_and_ended_last_24h_are_mutually_exclusive(test_db):
    request = FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={"history": {}, "ended_last_24h": True},
    )
    outcome = handle_sessions_list(request)
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"


def test_ended_last_24h_rejects_singular_project(test_db):
    # Only the plural `projects` scoping key is supported; a caller that
    # sends the singular live-roster `project` key must be told rather
    # than silently ignored.
    request = FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={"ended_last_24h": True, "project": "yoke"},
    )
    outcome = handle_sessions_list(request)
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"


def test_ended_last_24h_cannot_combine_with_other_filters(test_db):
    request = FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={"ended_last_24h": True, "liveness": "ended"},
    )
    outcome = handle_sessions_list(request)
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
    assert "ended_last_24h" in outcome.error.message


def test_ended_last_24h_must_be_boolean(test_db):
    request = FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload={"ended_last_24h": "yes"},
    )
    outcome = handle_sessions_list(request)
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"
