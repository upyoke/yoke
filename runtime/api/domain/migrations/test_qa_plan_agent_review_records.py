"""Governed migration coverage for batched QA plan agent review."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from psycopg.errors import UniqueViolation

from runtime.api.domain.migrations import (
    qa_plan_agent_review_records as source_wrapper,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.migration_source_digest import migration_source_digest
from yoke_core.domain.migrations.qa_plan_agent_review_records import (
    MIGRATION_NAME,
    apply,
    invariants,
)


_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name(
    "qa_plan_agent_review_records.migration.json"
)


def test_governed_manifest_is_valid_and_source_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    assert migration_source_digest(_ROOT / source["path"]) == source["sha256"]


def test_source_checkout_wrapper_exposes_packaged_migration() -> None:
    assert source_wrapper.MIGRATION_NAME == MIGRATION_NAME
    assert source_wrapper.apply is apply
    assert source_wrapper.invariants is invariants


def test_apply_is_idempotent_and_keeps_review_wait_live(test_db) -> None:
    apply(test_db)
    invariants(test_db)
    apply(test_db)
    invariants(test_db)

    insert_item(test_db, id=90741, title="Await agent inspection")
    test_db.execute(
        "INSERT INTO qa_plan_executions("
        "id,item_id,transition_id,actor_id,session_id,roster_digest,"
        "roster_json,cursor_ordinal,state,created_at,heartbeat_at"
        ") VALUES ("
        "'review-wait',90741,'implemented','operator','session','digest',"
        "'[]',0,'awaiting_agent_review','now','now'"
        ")"
    )
    with pytest.raises(UniqueViolation):
        test_db.execute(
            "INSERT INTO qa_plan_executions("
            "id,item_id,transition_id,session_id,roster_digest,roster_json,"
            "cursor_ordinal,state,created_at,heartbeat_at"
            ") VALUES ("
            "'duplicate',90741,'implemented','session-2','digest-2','[]',"
            "0,'active','now','now'"
            ")"
        )
    test_db.rollback()
