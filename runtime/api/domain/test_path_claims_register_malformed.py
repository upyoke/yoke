"""``claims.path.register`` refuses malformed path arguments atomically.

Every malformed form must come back as a named refusal carrying a recovery
step, never a raised exception, and must leave no claim or planned path
target behind — including when it arrives beside a well-formed path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.path_claim_task_test_support import (
    seed_item_claim,
    seed_target,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers.claims_path import handle_register

ITEM_ID = 7301
SESSION_ID = "sess-malformed"

MALFORMED = [
    pytest.param("/etc/passwd", "path_not_project_relative", id="absolute"),
    pytest.param("docs/*.py", "path_malformed", id="glob-star"),
]


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        with connect_test_db(db_path) as conn:
            actor = seed_human_actor(conn)
            insert_item(conn, id=ITEM_ID, source=str(actor))
            conn.execute(
                "INSERT INTO harness_sessions (session_id, executor, provider, "
                "model, project_id, execution_level, workspace, mode, offered_at, "
                "last_heartbeat) VALUES (%s, 'claude-code', 'test', 'test', 1, "
                "'primary', '/tmp', 'wait', '2026-05-01T00:00:00Z', "
                "'2026-05-01T00:00:00Z')",
                (SESSION_ID,),
            )
            conn.commit()
        yield db_path, actor


def _register(db, paths, *, allow_planned):
    _, actor = db
    return handle_register(
        FunctionCallRequest(
            function="claims.path.register",
            actor=ActorContext(actor_id=None, session_id=SESSION_ID),
            target=TargetRef(kind="item", item_id=ITEM_ID),
            payload={
                "paths": paths,
                "allow_planned": allow_planned,
                "integration_target": "main",
                "actor_id": actor,
            },
        )
    )


def _stored(db):
    with connect_test_db(db[0]) as conn:
        claims = conn.execute(
            "SELECT COUNT(*) FROM path_claims WHERE owner_item_id = %s", (ITEM_ID,)
        ).fetchone()[0]
        targets = conn.execute("SELECT COUNT(*) FROM path_targets").fetchone()[0]
    return int(claims), int(targets)


@pytest.mark.parametrize("allow_planned", [True, False], ids=["planned", "observed"])
@pytest.mark.parametrize("path,code", MALFORMED)
def test_malformed_path_refuses_and_stores_nothing(db, path, code, allow_planned):
    before = _stored(db)
    outcome = _register(db, ["docs/fine.py", path], allow_planned=allow_planned)
    assert outcome.primary_success is False
    assert outcome.error.code == code
    assert repr(path)[1:-1] in outcome.error.message or path in outcome.error.message
    assert "Re-run" in outcome.error.message
    assert outcome.error.jsonpath == "$.payload.paths"
    assert _stored(db) == before


@pytest.mark.parametrize("paths", [[]], ids=["none"])
def test_empty_path_set_refuses_and_stores_nothing(db, paths):
    before = _stored(db)
    outcome = _register(db, paths, allow_planned=True)
    assert outcome.primary_success is False
    assert outcome.error.code == "path_set_empty"
    assert "--paths" in outcome.error.message
    assert _stored(db) == before


def test_unknown_path_without_allow_planned_refuses(db):
    outcome = _register(db, ["docs/never-committed.py"], allow_planned=False)
    assert outcome.primary_success is False
    assert outcome.error.code == "path_target_unknown"
    assert "--allow-planned" in outcome.error.message
    assert _stored(db) == (0, 0)


@pytest.mark.parametrize("path", ["docs/fine.py", "app/[slug]/page.tsx"])
def test_well_formed_planned_path_still_registers(db, path):
    outcome = _register(db, [path], allow_planned=True)
    assert outcome.primary_success is True, outcome.error
    claims, targets = _stored(db)
    assert claims == 1 and targets >= 1


def test_refusal_after_planning_rolls_back_planned_targets(db):
    """An overlap refusal raised after planning leaves no planned target."""
    with connect_test_db(db[0]) as conn:
        insert_item(conn, id=ITEM_ID + 1, workflow_id="issue")
        held = seed_target(conn, item_id=ITEM_ID + 1, path="docs/held.py")
        seed_item_claim(conn, item_id=ITEM_ID + 1, target_ids=(held,))
        conn.commit()
    before = _stored(db)
    outcome = _register(db, ["docs/new-planned.py", "docs/held.py"], allow_planned=True)
    assert outcome.primary_success is False
    assert outcome.error.code == "register_failed"
    assert _stored(db) == before
    with connect_test_db(db[0]) as conn:
        planned = conn.execute(
            "SELECT COUNT(*) FROM path_targets WHERE path_string = %s",
            ("docs/new-planned.py",),
        ).fetchone()[0]
    assert planned == 0
