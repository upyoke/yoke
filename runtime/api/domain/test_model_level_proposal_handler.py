"""Level proposals over the published catalog, and approval through levels set."""

from __future__ import annotations

import sqlite3
from dataclasses import replace

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.levels import default_levels, levels_payload
from yoke_contracts.model_reference_data import MODEL_RECORDS
from yoke_contracts.model_reference_records import ModelRecord
from yoke_core.domain import db_helpers, yoke_function_registry
from yoke_core.domain.handlers import __init_register__ as init_register
from yoke_core.domain.handlers import model_level_proposal as proposal
from yoke_core.domain.handlers import universe_levels as levels_handlers
from yoke_core.domain.model_reference_store import (
    create_model_reference_table,
    publish_catalog,
    revision_at,
    seed_initial_catalog,
)
from yoke_core.domain.universe_levels import create_universe_settings_table

SUCCESSOR = ModelRecord(
    model_id="claude-fable-6",
    provider="anthropic",
    reasoning_efforts=("low", "medium", "high", "xhigh", "max"),
    context_window_tokens=(1_000_000,),
    source_urls=("https://example.test/fable-6",),
    checked_at="2026-10-08",
)


class _Conn:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *_exc):
        return False


@pytest.fixture
def db(monkeypatch):
    conn = sqlite3.connect(":memory:")
    create_model_reference_table(conn)
    seed_initial_catalog(conn)
    create_universe_settings_table(conn)
    monkeypatch.setattr(db_helpers, "connect", lambda *_a, **_k: _Conn(conn))
    yield conn
    conn.close()


def _publish(conn, records) -> None:
    publish_catalog(
        conn,
        [record.to_dict() for record in records],
        effective_at=None,
        actor_id=1,
        source_note="test publication",
        expected_base_revision_id=revision_at(conn)["revision_id"],
    )


def _call(handler, function_id, payload):
    return handler(
        FunctionCallRequest(
            function=function_id,
            actor=ActorContext(session_id="s-test", actor_id="1"),
            target=TargetRef(kind="global"),
            payload=payload,
        )
    )


def _propose(payload=None):
    return _call(
        proposal.handle_models_level_proposal, proposal.FUNCTION_ID, payload or {}
    )


def _set(levels):
    return _call(
        levels_handlers.handle_universe_levels_set,
        levels_handlers.SET_FUNCTION_ID,
        {"levels": levels},
    )


def _superseded_fable(conn) -> None:
    records = [
        replace(r, replacement_model_id="claude-fable-6")
        if r.model_id == "claude-fable-5-1"
        else r
        for r in MODEL_RECORDS
    ]
    _publish(conn, [*records, SUCCESSOR])


def test_refresh_proposes_the_successor_and_approval_applies_it(db) -> None:
    _superseded_fable(db)
    outcome = _propose()
    assert outcome.primary_success is True, outcome.error
    result = outcome.result_payload
    assert result["generated"] is True
    assert result["base_source"] == "default"
    assert [c["kind"] for c in result["changes"]] == ["retire", "add"] * 3
    assert result["apply_command"] == "yoke universe levels set --stdin"
    principal = result["levels"][-1]["options"]
    assert principal[0]["model"] == "claude-fable-6"

    assert _set(result["levels"]).primary_success is True
    stored = _call(
        levels_handlers.handle_universe_levels_get,
        levels_handlers.GET_FUNCTION_ID,
        {},
    ).result_payload
    assert stored["source"] == "universe"
    assert stored["levels"] == result["levels"]
    assert _propose().result_payload["changes"] == []


def test_authored_changes_replace_the_generated_list(db) -> None:
    sonnet = {"model": "claude-sonnet-5-5", "min_effort": "high"}
    outcome = _propose(
        {"changes": [{"kind": "move", "option": sonnet, "to_level": "SENIOR"}]}
    )
    assert outcome.primary_success is True, outcome.error
    result = outcome.result_payload
    assert result["generated"] is False
    senior = [option["model"] for option in result["levels"][2]["options"]]
    assert "claude-sonnet-5-5" in senior
    assert result["unplaced_models"] == []
    assert [row["model_id"] for row in result["unplaceable_models"]] == ["composer-2.5"]
    assert result["equals_shipped_defaults"] is False
    assert result["apply_command"] == "yoke universe levels set --stdin"


def test_authored_option_with_an_unpublished_effort_is_refused(db):
    outcome = _propose(
        {
            "changes": [
                {
                    "kind": "add",
                    "level": "PRINCIPAL",
                    "option": {"model": "gpt-6.1-sol", "min_effort": "none"},
                }
            ]
        }
    )
    assert outcome.primary_success is False
    assert outcome.error.code == "level_min_effort_order_invalid"


def test_levels_set_refuses_an_effort_the_catalog_contradicts(db):
    records = [
        replace(r, reasoning_efforts=("low", "high"))
        if r.model_id == "claude-opus-5-5"
        else r
        for r in MODEL_RECORDS
    ]
    _publish(db, records)
    outcome = _set(levels_payload(default_levels()))
    assert outcome.primary_success is False
    assert outcome.error.code == "level_min_effort_unpublished"
    assert "yoke models publish" in outcome.error.message


def test_level_proposal_is_registered_as_a_read() -> None:
    init_register.register_all_handlers()
    entry = yoke_function_registry.lookup(proposal.FUNCTION_ID)
    assert entry is not None
    assert entry.target_kinds == ("global",)
    assert entry.adapter_status == "live"
    assert not entry.side_effects
