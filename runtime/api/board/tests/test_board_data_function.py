"""``board.data.get`` — handler, dispatcher, and HTTP-boundary coverage.

Three layers over the same disposable Postgres fixture:

1. Handler-direct: ``handle_board_data_get`` returns the recorded plan.
2. Dispatcher: the registered function id routes in-process.
3. Real HTTP route: ``POST /v1/functions/call`` through the real FastAPI
   app with a real minted token — the same path an https-default
   machine uses (pattern: ``runtime.api.test_api_item_ref_relay``).
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from yoke_contracts.board.art import ArtConfig
from yoke_contracts.board.config import BoardConfig
from yoke_core.board.renderer import render_board_from_payload
from yoke_core.domain import events as events_module
from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain.handlers import orchestration
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
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


def test_handler_returns_recorded_plan(populated_db):
    outcome = orchestration.handle_board_data_get(
        _request({"scope": "yoke", "config_values": {}})
    )
    assert outcome.primary_success
    result = outcome.result_payload
    assert result["scope"] == "yoke"
    assert result["entry_count"] == len(result["entries"]) > 0
    kinds = {entry["kind"] for entry in result["entries"]}
    assert "query" in kinds  # classify_items
    assert "scalar" in kinds  # max-id width, weather count
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


def test_handler_rejects_unknown_config_field(populated_db):
    outcome = orchestration.handle_board_data_get(
        _request({"scope": "yoke", "config_values": {"not_a_field": 1}})
    )
    # Unknown keys are dropped by the board.json parser client-side; a
    # raw unknown kwarg here signals client/server contract divergence.
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"


def test_handler_vision_count_shapes_zen_plan(populated_db):
    """The vision count feeds zen zone width, which is a SQL parameter —
    payloads recorded with different counts carry different plans."""
    config_values = {"timeline_widget": "always"}

    def entries_for(count: int):
        outcome = orchestration.handle_board_data_get(_request({
            "scope": "all",
            "config_values": config_values,
            "zen_vision_count": count,
        }))
        assert outcome.primary_success
        return outcome.result_payload["entries"]

    def zen_position_params(entries):
        return [
            tuple(e["params"] or [])
            for e in entries
            if e["kind"] == "query" and "pos_raw" in e["sql"]
        ]

    assert zen_position_params(entries_for(0)) != zen_position_params(
        entries_for(3)
    )


def test_handler_all_scope_filters_to_visible_project_ids(populated_db):
    conn = connect_test_db(populated_db)
    try:
        insert_item(
            conn,
            id=20,
            title="Buzz-only item",
            status="implementing",
            project="buzz",
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
    assert result["visible_project_ids"] == [1]
    markdown = render_board_from_payload(
        result,
        scope="all",
        config=BoardConfig(),
        art_config=ArtConfig(),
        seed=11,
    )
    assert "First item" in markdown
    assert "Buzz-only item" not in markdown


def test_dispatcher_routes_board_data_get(populated_db):
    reset_registry_for_tests()
    register_all_handlers()
    try:
        with mock.patch.object(events_module, "emit_event"):
            response = dispatch_module.dispatch({
                "function": "board.data.get",
                "version": "v1",
                "actor": {"actor_id": None, "session_id": ""},
                "target": {"kind": "global"},
                "payload": {"scope": "yoke"},
                "preconditions": {},
                "options": {},
            })
    finally:
        reset_registry_for_tests()
    assert response.success, response.error
    assert response.result["entry_count"] > 0


class TestBoardDataOverHttpBoundary:
    """Real FastAPI app + real minted token, board-shaped fixture DB."""

    @pytest.fixture(autouse=True)
    def _suite(self, populated_db):
        from fastapi.testclient import TestClient

        from runtime.api.auth_test_helpers import mint_api_auth_context
        from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
        from yoke_core.api.main import app

        with mock.patch.dict(
            os.environ, {"YOKE_DB": populated_db}, clear=False
        ):
            reset_registry_for_tests()
            register_all_handlers()
            patches = [
                mock.patch.object(events_module, "emit_event"),
                mock.patch.object(
                    dispatch_module, "_idempotency_lookup", return_value=None,
                ),
            ]
            for p in patches:
                p.start()
            conn = connect_test_db(populated_db)
            try:
                apply_fixture_ddl(conn, (
                    "CREATE TABLE IF NOT EXISTS harness_sessions ("
                    " session_id TEXT PRIMARY KEY, actor_id TEXT,"
                    " current_item_id TEXT, recent_item_id TEXT)"
                ))
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
        assert result["entry_count"] > 0
        # The wire payload feeds a connection-free render client-side.
        markdown = render_board_from_payload(
            result,
            scope="yoke",
            config=BoardConfig(),
            art_config=ArtConfig(),
            seed=4,
        )
        assert "First item" in markdown
