"""Boot pin moves preserve stored stages, claims, and refused items."""

from copy import deepcopy

import pytest

from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.builtin_workflow_definitions import builtin_workflow_definition
from yoke_core.domain.workflow_registry import publish_workflow_version
from yoke_core.domain import workflow_retired_gate_pin_moves as moves
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.work_claim_targets import make_item_target

ITEM_ID = 948


def _seed(conn, *, edited=False, status="implementing", old_current=False):
    source_def = deepcopy(canon_generations("dash")[-2].definition)
    if edited:
        source_def["stages"][0]["label"] = "Custom idea"
    source = publish_workflow_version(conn, workflow_id="dash", definition=source_def)
    insert_item(conn, id=ITEM_ID, workflow_id="dash", status=status)
    conn.execute("UPDATE items SET workflow_version_id = %s WHERE id = %s", (source["version_id"], ITEM_ID))
    target = source if old_current else publish_workflow_version(
        conn, workflow_id="dash", definition=builtin_workflow_definition("dash")["definition"],
    )
    conn.commit()
    return source, target


def _pin(conn):
    row = conn.execute("SELECT workflow_version_id, status FROM items WHERE id = %s", (ITEM_ID,)).fetchone()
    return int(row[0]), row[1]


@pytest.mark.parametrize("claim", [False, True])
def test_boot_moves_open_pin_preserves_stage_and_is_idempotent(test_db, claim):
    source, target = _seed(test_db)
    if claim:
        now = iso8601_now()
        project_id = test_db.execute("SELECT project_id FROM items WHERE id = %s", (ITEM_ID,)).fetchone()[0]
        test_db.execute(
            "INSERT INTO harness_sessions (session_id, executor, provider, model, execution_level, workspace, project_id, offered_at, last_heartbeat) "
            "VALUES (%s, 'codex', 'openai', 'test-model', 'SENIOR', '/tmp/test', %s, %s, %s)",
            ("pin-move-session", project_id, now, now),
        )
        test_db.execute(
            "INSERT INTO work_claims (session_id, target_kind, scope, claimed_at, last_heartbeat, reason) VALUES (%s, 'item', %s, %s, %s, 'test')",
            ("pin-move-session", make_item_target(ITEM_ID).scope_json(), now, now),
        )
        test_db.commit()
    moves.move_open_items_off_retired_gate_versions(test_db)
    assert _pin(test_db) == (target["version_id"], "implementing")
    moves.move_open_items_off_retired_gate_versions(test_db)
    assert _pin(test_db) == (target["version_id"], "implementing")
    assert source["version_id"] != target["version_id"]


@pytest.mark.parametrize("options", [{"edited": True}, {"status": "done"}, {"status": "cancelled"}, {"old_current": True}])
def test_boot_leaves_ineligible_pin_unchanged(test_db, options):
    source, _ = _seed(test_db, **options)
    moves.move_open_items_off_retired_gate_versions(test_db)
    assert _pin(test_db) == (source["version_id"], options.get("status", "implementing"))


def test_boot_keeps_refused_pin_and_continues(test_db, monkeypatch, caplog):
    source, target = _seed(test_db)
    insert_item(test_db, id=ITEM_ID + 1, workflow_id="dash", status="implementing")
    test_db.execute("UPDATE items SET workflow_version_id = %s WHERE id = %s", (source["version_id"], ITEM_ID + 1))
    test_db.commit()
    original = moves.migrate_item_workflow_pin
    def migrate(conn, *, item_id, target_version):
        if item_id == ITEM_ID:
            raise ValueError("incompatible live claim")
        return original(conn, item_id=item_id, target_version=target_version)
    monkeypatch.setattr(moves, "migrate_item_workflow_pin", migrate)
    moves.move_open_items_off_retired_gate_versions(test_db)
    assert _pin(test_db) == (source["version_id"], "implementing")
    row = test_db.execute("SELECT workflow_version_id, status FROM items WHERE id = %s", (ITEM_ID + 1,)).fetchone()
    assert tuple(row) == (target["version_id"], "implementing")
    assert "retired_gate_pin_move_refused" in caplog.text
