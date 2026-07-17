"""Focused coverage for strategy/event/Ouroboros wrapper surfaces."""

from __future__ import annotations

from contextlib import nullcontext
from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import init_test_db
from yoke_cli import operation_inventory as ops
from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_backend, yoke_function_registry
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.handlers import (
    __init_register__ as init_register,
    events_emit,
    ouroboros_writes,
    strategy_operations,
)
from yoke_core.domain.events import EmitResult


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(session_id="sess-test-1"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def test_cli_registry_exposes_strategy_event_ouroboros_surfaces() -> None:
    expected = {
        ("events", "emit"): "events.emit",
        ("strategy", "carry", "mark"): "strategy.carry.mark",
        ("strategy", "checkpoint", "record"): "strategy.checkpoint.record",
        ("strategy", "master-plan-check"): "strategy.master_plan_check.run",
        ("ouroboros", "entry", "insert"): "ouroboros.entry.insert",
        ("ouroboros", "wrapup", "list"): "ouroboros.wrapup.list",
    }
    for tokens, function_id in expected.items():
        assert SUBCOMMAND_REGISTRY[tokens][0] == function_id
        assert ops.lookup("yoke " + " ".join(tokens)).status == ops.WRAPPED


def test_tool_shaped_classifications_cover_atlas_helpers() -> None:
    for shell_form in (
        "python3 -m yoke_core.tools.atlas_render_docs render",
        "python3 -m yoke_core.tools.atlas_render_docs check",
    ):
        entry = ops.lookup(shell_form)
        assert entry is not None
        assert entry.status == ops.PERMANENT
        assert entry.reason == ops.REASON_TOOL_SHAPED
    entry = ops.lookup("yoke sessions init")
    assert entry is not None
    assert entry.status == ops.WRAPPED
    assert SUBCOMMAND_REGISTRY[("sessions", "init")][0] == "sessions.init"

    assert ops.lookup("python3 -m yoke_core.tools.session_init") is None


def test_register_all_handlers_includes_new_function_ids() -> None:
    yoke_function_registry.reset_registry_for_tests()
    try:
        init_register.register_all_handlers()
        for function_id in (
            "events.emit",
            "strategy.carry.mark",
            "strategy.checkpoint.record",
            "strategy.master_plan_check.run",
            "ouroboros.entry.insert",
            "ouroboros.wrapup.list",
        ):
            assert yoke_function_registry.lookup(function_id) is not None
    finally:
        yoke_function_registry.reset_registry_for_tests()


def test_events_emit_handler_delegates_to_native_emitter(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_emit_event(name, **kwargs):
        calls.append({"name": name, **kwargs})
        return EmitResult(ok=True, event_id="evt-1", reason="")

    from yoke_core.domain import events

    monkeypatch.setattr(events, "emit_event", fake_emit_event)
    outcome = events_emit.handle_events_emit(
        _request(
            "events.emit",
            {
                "name": "FeedCompleted",
                "kind": "lifecycle",
                "type": "feed",
                "source_type": "skill",
                "severity": "STATUS",
                "project": "yoke",
                "context": {"detail": {"mode": "direct"}},
            },
        )
    )

    assert outcome.primary_success is True
    assert outcome.result_payload == {
        "emitted": True,
        "event_id": "evt-1",
        "reason": "",
    }
    assert calls[0]["name"] == "FeedCompleted"
    assert calls[0]["event_kind"] == "lifecycle"
    assert calls[0]["session_id"] == "sess-test-1"
    assert calls[0]["context"] == {"detail": {"mode": "direct"}}


def test_events_emit_schema_omits_platform_user_identity() -> None:
    properties = events_emit.EventsEmitRequest.model_json_schema()["properties"]
    assert "user_id" not in properties


def test_ouroboros_entry_insert_handler_writes_row(tmp_db: str) -> None:
    outcome = ouroboros_writes.handle_ouroboros_entry_insert(
        _request(
            "ouroboros.entry.insert",
            {
                "agent": "tester",
                "category": "observation",
                "context": "wrapper-test",
                "observation": "registered ouroboros insertion works",
                "timestamp": "2026-06-16T00:00:00Z",
            },
        )
    )

    assert outcome.primary_success is True
    entry_id = int(outcome.result_payload["entry_id"])
    with connect(tmp_db) as conn:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        row = conn.execute(
            "SELECT agent, context, category, body "
            f"FROM ouroboros_entries WHERE id = {p}",
            (entry_id,),
        ).fetchone()
    assert tuple(row) == (
        "tester",
        "wrapper-test",
        "observation",
        "registered ouroboros insertion works",
    )


def test_strategy_checkpoint_record_and_latest(tmp_db: str) -> None:
    with connect(tmp_db) as conn:
        p = "%s" if db_backend.connection_is_postgres(conn) else "?"
        conn.execute(
            "INSERT INTO projects (id, slug, name, created_at) "
            f"VALUES ({p}, {p}, {p}, {p}) "
            "ON CONFLICT(id) DO NOTHING",
            (1, "yoke", "Yoke", "2026-06-16T00:00:00Z"),
        )
        conn.commit()

    recorded = strategy_operations.handle_strategy_checkpoint_record(
        _request(
            "strategy.checkpoint.record",
            {"project": "yoke", "kind": "strategize"},
        )
    )
    assert recorded.primary_success is True

    latest = strategy_operations.handle_strategy_checkpoint_latest(
        _request(
            "strategy.checkpoint.latest",
            {"project": "yoke", "kind": "strategize"},
        )
    )
    assert latest.primary_success is True
    assert latest.result_payload["latest"]


def test_strategy_carry_summary_ignores_register_payload_and_stays_read_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from yoke_core.domain import db_helpers
    from yoke_core.domain import strategize_carry_state as state
    from yoke_core.domain import strategize_carry_summary as summary

    calls: list[dict] = []

    def fake_get_candidate_set(conn, **kwargs):
        calls.append(kwargs)
        return {
            "horizon_days": kwargs["horizon_days"],
            "carry_limit": kwargs["carry_limit"],
            "new": [],
            "carry_forward": [],
            "reflected": [],
            "dismissed": [],
        }

    def forbidden_register_new_landings(*_args, **_kwargs):
        raise AssertionError("summary must not register new landings")

    monkeypatch.setattr(db_helpers, "connect", lambda: nullcontext(object()))
    monkeypatch.setattr(state, "get_candidate_set", fake_get_candidate_set)
    monkeypatch.setattr(state, "register_new_landings", forbidden_register_new_landings)
    monkeypatch.setattr(summary, "format_summary", lambda *_a, **_k: "summary\n")

    outcome = strategy_operations.handle_strategy_carry_summary(
        _request(
            "strategy.carry.summary",
            {
                "project": "yoke",
                "new_ids": [17],
                "register": True,
                "display_limit": 5,
            },
        )
    )

    assert outcome.primary_success is True
    assert outcome.result_payload == {"summary": "summary\n"}
    assert calls == [
        {
            "project": "yoke",
            "horizon_days": strategy_operations.DEFAULT_HORIZON_DAYS,
            "carry_limit": strategy_operations.DEFAULT_CARRY_LIMIT,
            "now_iso": None,
            "new_ids": [17],
        }
    ]
