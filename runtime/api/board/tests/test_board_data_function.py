"""``board.data.get`` — handler, dispatcher, and HTTP-boundary coverage.

Three layers over the same disposable Postgres fixture:

1. Handler-direct: ``handle_board_data_get`` returns the named snapshot.
2. Dispatcher: the registered function id routes in-process.
3. Real HTTP route: ``POST /v1/functions/call`` through the real FastAPI
   app with a real minted token — the same path an https-default
   machine uses (pattern: ``runtime.api.test_api_item_ref_relay``).
"""

from __future__ import annotations

import json
import os
from unittest import mock

import pytest
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.board.art import ArtConfig
from yoke_contracts.board.config import BoardConfig
from yoke_core.board.renderer import render_board_from_payload
from yoke_core.domain import events as events_module
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain.handlers import orchestration
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.yoke_function_registry import reset_registry_for_tests

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db


def _request(payload: dict, *, options: dict | None = None) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="board.data.get",
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="global"),
        payload=payload,
        options=options or {},
    )


def test_handler_returns_named_snapshot(populated_db):
    outcome = orchestration.handle_board_data_get(
        _request({"scope": "yoke", "config_values": {}})
    )
    assert outcome.primary_success
    result = outcome.result_payload
    assert result["scope"] == "yoke"
    assert any(result["items"].values())
    assert "entries" not in result
    # The payload renders client-side without any DB connection.
    config = BoardConfig()
    markdown = render_board_from_payload(
        result,
        scope="yoke",
        config=config,
        art_config=ArtConfig(),
        seed=11,
    )
    assert "First item" in markdown


def test_handler_records_only_generated_children_policy(populated_db):
    """Item rows omit the rest of each pinned workflow definition."""
    marker = "unused-definition-payload-" + ("x" * 100_000)
    conn = connect_test_db(populated_db)
    try:
        rows = conn.execute(
            "SELECT id, definition_json FROM workflow_versions ORDER BY id"
        ).fetchall()
        for version_id, raw_definition in rows:
            definition = json.loads(raw_definition)
            definition["unused_board_payload"] = marker
            conn.execute(
                "UPDATE workflow_versions SET definition_json = %s WHERE id = %s",
                (json.dumps(definition), version_id),
            )
        conn.execute(
            "UPDATE items SET workflow_version_id = "
            "CASE WHEN workflow_id = 'epic' THEN 2 ELSE 1 END"
        )
        conn.commit()
    finally:
        conn.close()

    outcome = orchestration.handle_board_data_get(
        _request({"scope": "yoke", "config_values": {}})
    )

    assert outcome.primary_success
    result = outcome.result_payload
    encoded = json.dumps(result)
    assert marker not in encoded

    items = {row["id"]: row for rows in result["items"].values() for row in rows}
    assert items["YOK-1"]["epic_id"] is None
    assert items["YOK-3"]["epic_id"] == 3

    markdown = render_board_from_payload(
        result,
        scope="yoke",
        config=BoardConfig(),
        art_config=ArtConfig(),
        seed=11,
    )
    assert "1/2 (50%)" in markdown


def test_handler_ignores_unknown_config_field(populated_db):
    outcome = orchestration.handle_board_data_get(
        _request({"scope": "yoke", "config_values": {"not_a_field": 1}})
    )
    # Unknown keys are dropped the same way the legacy board.json parser
    # dropped them; fixture callers may pass a partial mapping.
    assert outcome.primary_success
    assert outcome.result_payload["scope"] == "yoke"


def test_handler_vision_count_shapes_zen_plan(populated_db):
    """VISION count shapes the owning project's timeline width."""
    from yoke_contracts.board.config import config_from_values

    with connect_test_db(populated_db) as conn:
        conn.execute(
            "UPDATE items SET created_at=now() - interval '2 days', updated_at=now() WHERE status='done'"
        )

    config_values = {"timeline_widget": "always"}

    def entries_for(count: int):
        with (
            mock.patch(
                "yoke_core.domain.board_policy_read.resolve_board_config",
                return_value=config_from_values(config_values),
            ),
            mock.patch(
                "yoke_core.domain.board_policy_read.resolve_board_scope",
                return_value="all",
            ),
        ):
            outcome = orchestration.handle_board_data_get(
                _request(
                    {
                        "settings_project_id": 1,
                        "zen_vision_count": count,
                    }
                )
            )
        assert outcome.primary_success
        assert outcome.result_payload["vision_project"] == "yoke"
        return outcome.result_payload["timeline"]

    assert entries_for(0)[0]["past_width"] != entries_for(3)[0]["past_width"]


def test_handler_all_scope_filters_to_visible_project_ids(populated_db):
    conn = connect_test_db(populated_db)
    try:
        insert_item(
            conn,
            id=20,
            title="ExternalWebapp-only item",
            status="implementing",
            project="externalwebapp",
            project_sequence=20,
        )
    finally:
        conn.close()

    outcome = orchestration.handle_board_data_get(
        _request(
            {"scope": "all", "config_values": {}},
            options={"visible_project_ids": [1]},
        )
    )

    assert outcome.primary_success
    result = outcome.result_payload
    markdown = render_board_from_payload(
        result,
        scope="all",
        config=BoardConfig(),
        art_config=ArtConfig(),
        seed=11,
    )
    assert "First item" in markdown
    assert "ExternalWebapp-only item" not in markdown


def test_dispatcher_routes_board_data_get(populated_db):
    reset_registry_for_tests()
    register_all_handlers()
    try:
        with mock.patch.object(events_module, "emit_event"):
            response = dispatch_module.dispatch(
                {
                    "function": "board.data.get",
                    "version": "v1",
                    "actor": {"actor_id": None, "session_id": ""},
                    "target": {"kind": "global"},
                    "payload": {"scope": "yoke"},
                    "preconditions": {},
                    "options": {},
                }
            )
    finally:
        reset_registry_for_tests()
    assert response.success, response.error
    assert any(response.result["items"].values())


class TestBoardDataOverHttpBoundary:
    """Real FastAPI app + real minted token, board-shaped fixture DB."""

    @pytest.fixture(autouse=True)
    def _suite(self, populated_db):
        from fastapi.testclient import TestClient
        from yoke_core.api.main import app

        from runtime.api.auth_test_helpers import mint_api_auth_context
        from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

        with mock.patch.dict(os.environ, {"YOKE_DB": populated_db}, clear=False):
            reset_registry_for_tests()
            register_all_handlers()
            patches = [
                mock.patch.object(events_module, "emit_event"),
                mock.patch.object(
                    dispatch_module,
                    "_idempotency_lookup",
                    return_value=None,
                ),
            ]
            for p in patches:
                p.start()
            conn = connect_test_db(populated_db)
            try:
                # The roster section reads these columns whether or not any
                # session row exists, and a column it cannot read is now a
                # loud failure rather than an empty section.
                apply_fixture_ddl(
                    conn,
                    (
                        "CREATE TABLE IF NOT EXISTS harness_sessions ("
                        " session_id TEXT PRIMARY KEY, actor_id TEXT,"
                        " current_item_id TEXT, recent_item_id TEXT,"
                        " executor TEXT, executor_surface TEXT, model TEXT,"
                        " reasoning_effort TEXT, context_window_tokens INTEGER,"
                        " requested_model TEXT, requested_reasoning_effort TEXT,"
                        " requested_context_window_tokens INTEGER,"
                        " usage_totals TEXT,"
                        " mode TEXT, execution_level TEXT, workspace TEXT,"
                        " project_id INTEGER, offered_at TIMESTAMPTZ,"
                        " last_heartbeat TIMESTAMPTZ, last_tool_call_at TIMESTAMPTZ,"
                        " ended_at TIMESTAMPTZ, terminated_at TIMESTAMPTZ)"
                    ),
                )
                auth = mint_api_auth_context(conn)
            finally:
                conn.close()
            self.client = TestClient(app)
            self.client.headers.update(auth.headers)
            try:
                yield
            finally:
                for p in patches:
                    p.stop()
                reset_registry_for_tests()

    def test_board_data_get_over_https_route(self) -> None:
        resp = self.client.post(
            "/v1/functions/call",
            json={
                "function": "board.data.get",
                "version": "v1",
                "actor": {"actor_id": None, "session_id": ""},
                "target": {"kind": "global"},
                "payload": {"scope": "yoke", "config_values": {}},
                "preconditions": {},
                "options": {},
            },
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["success"], body.get("error")
        result = body["result"]
        assert any(result["items"].values())
        # The wire payload feeds a connection-free render client-side.
        markdown = render_board_from_payload(
            result,
            scope="yoke",
            config=BoardConfig(),
            art_config=ArtConfig(),
            seed=4,
        )
        assert "First item" in markdown
