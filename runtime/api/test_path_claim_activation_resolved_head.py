"""In-process integration coverage for the client-git / server-DB split.

Exercises the server side of the transport-aware path-claim activation
against a seeded Postgres authority: ``run_activation_phase`` consuming a
client-resolved integration head, the ``claims.path.activation_run``
handler guards, and ``claims.path.survey_ensure`` validating selected-Dash
coverage without registering. Client-side relay routing is covered in
``test_worktree_preflight_steps`` and ``test_worktree_create_policy_lanes``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import advance_path_claim_activation as _activation
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.advance_path_claim_activation import (
    resolve_item_actor,
    run_activation_phase,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.claims_path_activation import (
    handle_activation_run,
    handle_survey_ensure,
)


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _project_id(conn, item_id: int) -> int:
    return int(
        conn.execute(
            "SELECT project_id FROM items WHERE id = %s", (item_id,)
        ).fetchone()[0]
    )


def _seed_target(conn, project_id: int, path: str = "runtime/api/domain") -> int:
    return int(
        conn.execute(
            "INSERT INTO path_targets "
            "(project_id, kind, path_string, generation, created_at) "
            "VALUES (%s, 'directory', %s, 1, %s) RETURNING id",
            (project_id, path, iso8601_now()),
        ).fetchone()[0]
    )


def _seed_planned_claim(conn, *, item_id: int, actor_id: int, target_id: int) -> int:
    claim_id = int(
        conn.execute(
            "INSERT INTO path_claims "
            "(state, mode, owner_kind, owner_item_id, registered_by_actor_id, "
            "integration_target, registered_at) "
            "VALUES ('planned', 'exclusive', 'item', %s, %s, 'main', %s) "
            "RETURNING id",
            (item_id, actor_id, iso8601_now()),
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, %s)",
        (claim_id, target_id, iso8601_now()),
    )
    conn.commit()
    return claim_id


def _envelope(function, *, item_id, session_id="s-1", payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id=session_id),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


class TestRunActivationPhaseResolvedHead:
    def test_supplied_head_activates_without_checkout_lookup(self, db, monkeypatch):
        # Activation must use supplied resolved_heads, not checkout/git lookups.
        from yoke_core.domain import advance_path_claim_activation_retry as _retry

        monkeypatch.setattr(
            _activation, "checkout_for_project_id",
            lambda *_a, **_k: pytest.fail("checkout must not be consulted"),
        )
        monkeypatch.setattr(
            _retry, "resolve_integration_head_with_divergence_check",
            lambda *_a, **_k: pytest.fail("git resolver must not run"),
        )
        conn = connect_test_db(db)
        try:
            actor = seed_human_actor(conn)
            insert_item(conn, id=7101, source=str(actor))
            target_id = _seed_target(conn, _project_id(conn, 7101))
            claim_id = _seed_planned_claim(
                conn, item_id=7101, actor_id=actor, target_id=target_id
            )
            provided = "a1b2c3d4e5f6" + "0" * 28
            result = run_activation_phase(
                conn, item_id=7101, actor_id=actor,
                resolved_heads={claim_id: provided},
            )
            assert result.is_blocked is False
            assert result.activated_claim_ids == [claim_id]
            conn.commit()
            row = conn.execute(
                "SELECT state, base_commit_sha FROM path_claims WHERE id = %s",
                (claim_id,),
            ).fetchone()
            assert (row[0], row[1]) == ("active", provided)
        finally:
            conn.close()

    def test_no_claims_is_a_noop(self, db):
        conn = connect_test_db(db)
        try:
            actor = seed_human_actor(conn)
            insert_item(conn, id=7102, source=str(actor))
            result = run_activation_phase(
                conn, item_id=7102, actor_id=actor, resolved_heads={},
            )
            assert result.is_blocked is False
            assert result.outcomes == []
            assert result.activated_claim_ids == []
        finally:
            conn.close()


class TestResolveItemActor:
    def test_resolves_coalesce_owner_source(self, db):
        conn = connect_test_db(db)
        try:
            actor = seed_human_actor(conn)
            insert_item(conn, id=7110, source=str(actor))
            resolved, error = resolve_item_actor(conn, 7110)
            assert error is None
            assert resolved == actor
        finally:
            conn.close()

    def test_missing_item_errors(self, db):
        conn = connect_test_db(db)
        try:
            resolved, error = resolve_item_actor(conn, 424242)
            assert resolved is None
            assert "not found" in error
        finally:
            conn.close()

    def test_blank_owner_source_errors(self, db):
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=7111)
            # ``items.source`` is NOT NULL with a default actor, so force
            # the blank owner+source shape the guard defends against.
            conn.execute(
                "UPDATE items SET owner = NULL, source = '' WHERE id = %s",
                (7111,),
            )
            conn.commit()
            resolved, error = resolve_item_actor(conn, 7111)
            assert resolved is None
            assert "no owner/source actor" in error
        finally:
            conn.close()


class TestActivationRunHandlerGuards:
    def test_resolves_item_actor_and_uses_supplied_head(self, db):
        conn = connect_test_db(db)
        try:
            actor = seed_human_actor(conn)
            insert_item(conn, id=7120, source=str(actor))
            target_id = _seed_target(conn, _project_id(conn, 7120))
            claim_id = _seed_planned_claim(
                conn, item_id=7120, actor_id=actor, target_id=target_id
            )
        finally:
            conn.close()
        provided = "f00dfeed" + "0" * 32
        # No actor_id in the payload -> the handler resolves the item's
        # COALESCE(owner, source) actor server-side.
        outcome = handle_activation_run(
            _envelope(
                "claims.path.activation_run", item_id=7120,
                payload={"resolved_heads": {claim_id: provided}},
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["actor_id"] == actor
        conn = connect_test_db(db)
        try:
            row = conn.execute(
                "SELECT state, base_commit_sha FROM path_claims WHERE id = %s",
                (claim_id,),
            ).fetchone()
            assert (row[0], row[1]) == ("active", provided)
        finally:
            conn.close()

    def test_refuses_when_another_session_holds_work_claim(self, db, monkeypatch):
        conn = connect_test_db(db)
        try:
            actor = seed_human_actor(conn)
            insert_item(conn, id=7121, source=str(actor))
        finally:
            conn.close()
        monkeypatch.setattr(
            _activation, "check_work_claim_ownership",
            lambda *_a, **_k: "other-session",
        )
        outcome = handle_activation_run(
            _envelope(
                "claims.path.activation_run", item_id=7121, session_id="mine",
                payload={"resolved_heads": {}},
            )
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "work_claim_conflict"
        assert "other-session" in outcome.error.message

    def test_blank_owner_source_actor_errors(self, db):
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=7122)
            conn.execute(
                "UPDATE items SET owner = NULL, source = '' WHERE id = %s",
                (7122,),
            )
            conn.commit()
        finally:
            conn.close()
        outcome = handle_activation_run(
            _envelope(
                "claims.path.activation_run", item_id=7122,
                payload={"resolved_heads": {}},
            )
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "actor_unavailable"


class TestSurveyEnsureHandler:
    def _insert_session(self, conn, session_id: str, actor: int) -> None:
        now = iso8601_now()
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id, executor, provider, model, workspace, project_id, "
            "offered_at, last_heartbeat, actor_id) "
            "VALUES (%s, 'codex', 'openai', 'gpt', '/tmp', 1, %s, %s, %s)",
            (session_id, now, now, actor),
        )
        conn.commit()

    def test_missing_coverage_fails_without_inserting(self, db):
        conn = connect_test_db(db)
        try:
            actor = seed_human_actor(conn)
            insert_item(
                conn, id=7130, workflow_id="dash", source=str(actor),
                workflow_posture=json.dumps({"path_claims": True}),
            )
            self._insert_session(conn, "dash-session", actor)
        finally:
            conn.close()
        outcome = handle_survey_ensure(
            _envelope(
                "claims.path.survey_ensure", item_id=7130,
                session_id="dash-session",
                payload={
                    "touch_paths": ["ui/workflows.js"],
                    "integration_target": "main",
                },
            )
        )
        assert outcome.primary_success is False
        assert outcome.error.code == "survey_ensure_failed"
        assert "yoke claims path register --item 7130" in outcome.error.message
        conn = connect_test_db(db)
        try:
            assert conn.execute(
                "SELECT COUNT(*) FROM path_claims WHERE owner_item_id = 7130"
            ).fetchone()[0] == 0
        finally:
            conn.close()

    def test_complete_coverage_returns_existing_claim(self, db):
        conn = connect_test_db(db)
        try:
            actor = seed_human_actor(conn)
            insert_item(
                conn, id=7132, workflow_id="dash", source=str(actor),
                workflow_posture=json.dumps({"path_claims": True}),
            )
            self._insert_session(conn, "dash-cover", actor)
            target_id = _seed_target(
                conn, _project_id(conn, 7132), "ui/workflows.js",
            )
            claim_id = _seed_planned_claim(
                conn, item_id=7132, actor_id=actor, target_id=target_id,
            )
        finally:
            conn.close()
        outcome = handle_survey_ensure(
            _envelope(
                "claims.path.survey_ensure", item_id=7132,
                session_id="dash-cover",
                payload={
                    "touch_paths": ["ui/workflows.js"],
                    "integration_target": "main",
                },
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["claim_id"] == claim_id

    def test_non_dash_item_is_a_noop(self, db):
        conn = connect_test_db(db)
        try:
            actor = seed_human_actor(conn)
            insert_item(conn, id=7131, source=str(actor))
            self._insert_session(conn, "issue-session", actor)
        finally:
            conn.close()
        outcome = handle_survey_ensure(
            _envelope(
                "claims.path.survey_ensure", item_id=7131,
                session_id="issue-session",
                payload={"touch_paths": ["x.py"], "integration_target": "main"},
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["claim_id"] is None
