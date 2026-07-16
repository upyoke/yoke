"""Tests for the ``sessions.list`` read handler and its domain read.

Real-DB coverage on the ``test_db`` fixture: liveness derivation
(active / stale / ended), the executor-aware activity timestamp, the
active-claims join with typed-target display, the project and liveness
filters, actor attribution facts, and registration.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.sessions_list_read import (
    LIVENESS_STATES,
    SESSION_LIST_FIELDS,
    list_sessions,
)


def _iso(minutes_ago: int = 0) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


# Far past any executor-aware staleness TTL (they are minutes-scale).
_LONG_AGO_MINUTES = 60 * 24 * 30


def _request(payload: dict | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="sessions.list",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def _insert_session(
    conn,
    session_id: str,
    *,
    last_heartbeat: str,
    last_tool_call_at: str | None = None,
    ended_at: str | None = None,
    executor: str = "claude-code",
    lane: str = "primary",
    mode: str = "wait",
    project_id: int = 1,
    actor_id: int | None = None,
    current_item_id: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO harness_sessions ("
        "session_id, executor, provider, model, execution_lane, workspace, "
        "project_id, mode, offered_at, last_heartbeat, last_tool_call_at, "
        "ended_at, actor_id, current_item_id"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            session_id, executor, "anthropic", "test-model", lane,
            "/tmp/workspace", project_id, mode, last_heartbeat,
            last_heartbeat, last_tool_call_at, ended_at, actor_id,
            current_item_id,
        ),
    )
    conn.commit()


def _insert_item_claim(conn, session_id: str, item_id: int) -> None:
    conn.execute(
        "INSERT INTO work_claims ("
        "session_id, target_kind, item_id, claimed_at, last_heartbeat, reason"
        ") VALUES (%s, 'item', %s, %s, %s, %s)",
        (session_id, item_id, _iso(), _iso(), "implementation"),
    )
    conn.commit()


class TestLivenessDerivation:
    def test_active_stale_and_ended_states(self, test_db):
        _insert_session(test_db, "s-active", last_heartbeat=_iso())
        _insert_session(
            test_db, "s-stale",
            last_heartbeat=_iso(_LONG_AGO_MINUTES),
        )
        _insert_session(
            test_db, "s-ended",
            last_heartbeat=_iso(_LONG_AGO_MINUTES),
            ended_at=_iso(_LONG_AGO_MINUTES),
        )

        by_id = {row["session_id"]: row for row in list_sessions()}
        assert by_id["s-active"]["liveness"] == "active"
        assert by_id["s-stale"]["liveness"] == "stale"
        assert by_id["s-ended"]["liveness"] == "ended"

    def test_recent_tool_call_keeps_an_old_heartbeat_session_active(
        self, test_db,
    ):
        # Activity is MAX(last_heartbeat, last_tool_call_at) — the same
        # combined stamp the stale-session reclaim sweep consults.
        recent_tool_call = _iso()
        _insert_session(
            test_db, "s-tooling",
            last_heartbeat=_iso(_LONG_AGO_MINUTES),
            last_tool_call_at=recent_tool_call,
        )
        rows = list_sessions()
        assert rows[0]["session_id"] == "s-tooling"
        assert rows[0]["liveness"] == "active"
        assert rows[0]["activity_at"] == recent_tool_call

    def test_liveness_filter_and_rejection(self, test_db):
        _insert_session(test_db, "s-active", last_heartbeat=_iso())
        _insert_session(
            test_db, "s-ended",
            last_heartbeat=_iso(_LONG_AGO_MINUTES),
            ended_at=_iso(_LONG_AGO_MINUTES),
        )
        active_only = list_sessions(liveness="active")
        assert [row["session_id"] for row in active_only] == ["s-active"]
        ended_only = list_sessions(liveness="ended")
        assert [row["session_id"] for row in ended_only] == ["s-ended"]
        with pytest.raises(ValueError):
            list_sessions(liveness="running")


class TestClaimsAndAttribution:
    def test_active_item_claim_renders_display_target(self, test_db):
        from runtime.api.fixtures.backlog import insert_item

        insert_item(test_db, id=41, title="claimed work")
        test_db.commit()
        _insert_session(test_db, "s-holder", last_heartbeat=_iso())
        _insert_item_claim(test_db, "s-holder", 41)
        # A released claim must not appear as held.
        test_db.execute(
            "INSERT INTO work_claims ("
            "session_id, target_kind, item_id, claimed_at, last_heartbeat, "
            "released_at, release_reason"
            ") VALUES (%s, 'item', %s, %s, %s, %s, 'completed')",
            ("s-holder", 41, _iso(120), _iso(120), _iso(60)),
        )
        test_db.commit()

        rows = list_sessions()
        claims = rows[0]["claims"]
        assert len(claims) == 1
        assert claims[0]["target_kind"] == "item"
        assert claims[0]["target"] == "YOK-41"
        assert claims[0]["reason"] == "implementation"

    def test_process_and_epic_task_targets_render(self, test_db):
        _insert_session(test_db, "s-typed", last_heartbeat=_iso())
        test_db.execute(
            "INSERT INTO work_claims ("
            "session_id, target_kind, process_key, conflict_group, "
            "claimed_at, last_heartbeat"
            ") VALUES (%s, 'process', 'feed', 'feed', %s, %s)",
            ("s-typed", _iso(), _iso()),
        )
        test_db.execute(
            "INSERT INTO work_claims ("
            "session_id, target_kind, epic_id, task_num, "
            "claimed_at, last_heartbeat"
            ") VALUES (%s, 'epic_task', 9, 3, %s, %s)",
            ("s-typed", _iso(), _iso()),
        )
        test_db.commit()

        targets = {
            claim["target_kind"]: claim["target"]
            for claim in list_sessions()[0]["claims"]
        }
        assert targets["process"] == "feed"
        assert targets["epic_task"] == "epic 9 task 3"

    def test_system_actor_attribution_is_honest(self, test_db):
        row = test_db.execute(
            "SELECT id FROM actors WHERE kind = 'system' LIMIT 1",
        ).fetchone()
        system_actor_id = int(dict(row)["id"])
        _insert_session(
            test_db, "s-system", last_heartbeat=_iso(),
            actor_id=system_actor_id,
        )
        rows = list_sessions()
        assert rows[0]["actor_kind"] == "system"
        assert rows[0]["actor_id"] == system_actor_id
        # The label is the engine's display derivation: the system
        # component name, never something person-shaped.
        assert rows[0]["actor_label"]

    def test_current_item_renders_display_form(self, test_db):
        _insert_session(
            test_db, "s-on-item", last_heartbeat=_iso(),
            current_item_id="17",
        )
        assert list_sessions()[0]["current_item"] == "YOK-17"


class TestHandler:
    def test_handler_returns_fields_and_rows(self, test_db):
        _insert_session(test_db, "s-1", last_heartbeat=_iso())
        outcome = handle_sessions_list(_request())
        assert outcome.primary_success
        assert outcome.result_payload["fields"] == list(SESSION_LIST_FIELDS)
        rows = outcome.result_payload["rows"]
        assert [row["session_id"] for row in rows] == ["s-1"]

    def test_handler_project_filter_scopes_rows(self, test_db):
        test_db.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            "VALUES (%s, %s, %s, %s)",
            (77, "other", "Other", _iso()),
        )
        test_db.commit()
        _insert_session(test_db, "s-yoke", last_heartbeat=_iso())
        _insert_session(
            test_db, "s-other", last_heartbeat=_iso(), project_id=77,
        )
        outcome = handle_sessions_list(_request({"project": "other"}))
        assert outcome.primary_success
        rows = outcome.result_payload["rows"]
        assert [row["session_id"] for row in rows] == ["s-other"]
        assert rows[0]["project"] == "other"

    def test_handler_unknown_project_is_typed_not_found(self, test_db):
        outcome = handle_sessions_list(_request({"project": "nope"}))
        assert not outcome.primary_success
        assert outcome.error.code == "not_found"

    def test_handler_bad_liveness_is_typed_payload_error(self, test_db):
        outcome = handle_sessions_list(_request({"liveness": "running"}))
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"
        for state in LIVENESS_STATES:
            assert state in outcome.error.message

    def test_handler_requires_global_target(self):
        outcome = handle_sessions_list(
            FunctionCallRequest(
                function="sessions.list",
                actor=ActorContext(actor_id=None, session_id=""),
                target=TargetRef(kind="item", item_id=1),
                payload={},
            ),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_invalid"


class TestRegistration:
    def test_sessions_list_is_a_registered_claimless_read(self):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain import yoke_function_registry as registry
        from yoke_core.domain.yoke_function_actor_identity import is_read_only

        registry.reset_registry_for_tests()
        try:
            register_all_handlers()
            entry = registry.lookup("sessions.list")
            assert entry is not None
            assert entry.target_kinds == ("global",)
            assert is_read_only(entry)
        finally:
            registry.reset_registry_for_tests()
