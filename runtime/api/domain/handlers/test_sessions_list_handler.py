"""Tests for the ``sessions.list`` read handler and its domain read.

Real-DB coverage includes liveness, claims, filters, attribution, and roster.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.handlers.sessions_list import handle_sessions_list
from yoke_core.domain.session_control_roster import SESSION_CONTROL_ROSTER_FIELDS
from yoke_core.domain.session_control_schema import create_session_control_tables
from yoke_core.domain.sessions_list_read import LIVENESS_STATES, list_sessions
from yoke_core.domain.work_claim_targets import make_epic_task_target, make_item_target, make_process_target
from yoke_core.domain.work_processes import PROCESS_FEED


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
    terminated_at: str | None = None,
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
        "ended_at, terminated_at, actor_id, current_item_id"
        ") VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            session_id,
            executor,
            "anthropic",
            "test-model",
            lane,
            "/tmp/workspace",
            project_id,
            mode,
            last_heartbeat,
            last_heartbeat,
            last_tool_call_at,
            ended_at,
            terminated_at,
            actor_id,
            current_item_id,
        ),
    )
    conn.commit()


def _insert_item_claim(conn, session_id: str, item_id: int) -> None:
    target = make_item_target(item_id)
    conn.execute(
        "INSERT INTO work_claims (session_id, target_kind, scope, claimed_at, last_heartbeat, reason) VALUES (%s, %s, %s, %s, %s, %s)",
        (
            session_id,
            target.kind,
            target.scope_json(),
            _iso(),
            _iso(),
            "implementation",
        ),
    )
    conn.commit()


class TestClaimsAndAttribution:
    def test_active_item_claim_renders_display_target(self, test_db):
        from runtime.api.fixtures.backlog import insert_item

        insert_item(test_db, id=41, title="claimed work")
        test_db.commit()
        _insert_session(test_db, "s-holder", last_heartbeat=_iso())
        _insert_item_claim(test_db, "s-holder", 41)
        # A released claim must not appear as held.
        target = make_item_target(41)
        test_db.execute(
            "INSERT INTO work_claims ("
            "session_id, target_kind, scope, claimed_at, last_heartbeat, "
            "released_at, release_reason"
            ") VALUES (%s, %s, %s, %s, %s, %s, 'completed')",
            (
                "s-holder",
                target.kind,
                target.scope_json(),
                _iso(120),
                _iso(120),
                _iso(60),
            ),
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
        process_target = make_process_target(PROCESS_FEED, "yoke")
        test_db.execute(
            "INSERT INTO work_claims (session_id, target_kind, scope, claimed_at, last_heartbeat) VALUES (%s, %s, %s, %s, %s)",
            (
                "s-typed",
                process_target.kind,
                process_target.scope_json(),
                _iso(),
                _iso(),
            ),
        )
        task_target = make_epic_task_target(9, 3)
        test_db.execute(
            "INSERT INTO work_claims (session_id, target_kind, scope, claimed_at, last_heartbeat) VALUES (%s, %s, %s, %s, %s)",
            ("s-typed", task_target.kind, task_target.scope_json(), _iso(), _iso()),
        )
        test_db.commit()

        targets = {
            claim["target_kind"]: claim["target"]
            for claim in list_sessions()[0]["claims"]
        }
        # Every hold names itself in its target, because the card that
        # reads this adds no kind label of its own.
        assert targets["process"] == f"process {PROCESS_FEED}"
        assert targets["epic_task"] == "epic 9 task 3"

    def test_system_actor_attribution_is_honest(self, test_db):
        row = test_db.execute(
            "SELECT id FROM actors WHERE kind = 'system' LIMIT 1"
        ).fetchone()
        system_actor_id = int(dict(row)["id"])
        _insert_session(
            test_db, "s-system", last_heartbeat=_iso(), actor_id=system_actor_id
        )
        rows = list_sessions()
        assert rows[0]["actor_kind"] == "system"
        assert rows[0]["actor_id"] == system_actor_id
        assert rows[0]["actor_label"]

    def test_current_item_renders_display_form(self, test_db):
        _insert_session(
            test_db, "s-on-item", last_heartbeat=_iso(), current_item_id="17"
        )
        assert list_sessions()[0]["current_item"] == "YOK-17"

    def test_roster_renders_public_ref_not_internal_id(self, test_db):
        from runtime.api.fixtures.backlog import insert_item

        insert_item(test_db, id=5001, project_sequence=4200, title="divergent")
        _insert_session(test_db, "s-div", last_heartbeat=_iso(), current_item_id="5001")
        _insert_item_claim(test_db, "s-div", 5001)
        row = list_sessions()[0]
        assert row["claims"][0]["target"] == "YOK-4200"
        assert row["current_item"] == "YOK-4200"
        assert row["current_item_project_sequence"] == 4200
        assert row["current_item_project_id"] == 1

    def test_current_item_ownership_title_and_worktree_role(self, test_db):
        from runtime.api.fixtures.backlog import insert_item

        insert_item(test_db, id=40, title="Other lane")
        insert_item(test_db, id=41, title="Owned implementation")
        test_db.commit()
        _insert_session(test_db, "s-owner", last_heartbeat=_iso(), current_item_id="41")
        _insert_item_claim(test_db, "s-owner", 41)
        test_db.execute(
            "INSERT INTO item_worktrees ("
            "item_id, branch, path, lane_role, state, "
            "created_at, updated_at"
            ") VALUES (%s, %s, %s, 'implementation', 'active', %s, %s)",
            (40, "codex/other", "/tmp/other", _iso(), _iso()),
        )
        test_db.execute(
            "INSERT INTO item_worktrees (item_id, branch, path, lane_role, state, created_at, updated_at) VALUES (%s, %s, %s, 'worker', 'active', %s, %s)",
            (41, "codex/worker", "/tmp/worker", _iso(), _iso()),
        )
        test_db.commit()

        row = list_sessions()[0]
        assert row["current_item_title"] == "Owned implementation"
        assert row["current_item_workflow_id"] == "issue"
        assert int(row["current_item_workflow_version_id"]) > 0
        assert row["owns_current_item"] is True
        assert row["work_role"] == "worker"
        assert row["claim_started_at"]


class TestHandler:
    def test_handler_returns_fields_and_rows(self, test_db):
        create_session_control_tables(test_db)
        test_db.commit()
        _insert_session(test_db, "s-1", last_heartbeat=_iso())
        outcome = handle_sessions_list(_request())
        assert outcome.primary_success
        assert outcome.result_payload["fields"] == list(SESSION_CONTROL_ROSTER_FIELDS)
        rows = outcome.result_payload["rows"]
        assert [row["session_id"] for row in rows] == ["s-1"]

    def test_handler_project_filter_scopes_rows(self, test_db):
        create_session_control_tables(test_db)
        test_db.commit()
        test_db.execute(
            "INSERT INTO projects (id, slug, name, created_at) VALUES (%s, %s, %s, %s)",
            (77, "other", "Other", _iso()),
        )
        test_db.commit()
        _insert_session(test_db, "s-yoke", last_heartbeat=_iso())
        _insert_session(test_db, "s-other", last_heartbeat=_iso(), project_id=77)
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
            )
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_invalid"


class TestRegistration:
    def test_sessions_list_is_a_registered_claimless_read(self):
        from yoke_core.domain.handlers.__init_register__ import register_all_handlers
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
