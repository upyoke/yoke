"""Errors inside a caller's open transaction never discard the caller's writes."""

from __future__ import annotations

import json

import psycopg
import pytest

from runtime.api.domain.test_qa_requirement_target_rebind import (
    _stamp_requirement,
    _yoke_development,
)
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import qa_replacement_scope_guard
from yoke_core.domain.db_savepoint import SavepointLostError, savepoint
from yoke_core.domain.qa_requirement_target_rebind import (
    QaRebindError,
    rebind_requirement,
)
from yoke_core.domain.settings_cas import (
    apply_key_path_assignments,
    parse_settings_object,
)
from yoke_core.domain.workflow_status_transition_preflight import (
    prepare_status_transition,
)


def _scratch(conn) -> None:
    conn.execute("CREATE TEMP TABLE borrowed_scratch (v int)")
    conn.commit()
    conn.execute("INSERT INTO borrowed_scratch VALUES (1)")


def _values(conn) -> list[int]:
    rows = conn.execute("SELECT v FROM borrowed_scratch ORDER BY v").fetchall()
    return [int(row[0]) for row in rows]


def test_borrowed_error_undoes_only_the_block(test_db) -> None:
    _scratch(test_db)
    with pytest.raises(ValueError):
        with savepoint(test_db, "borrowed_block", owns=False):
            test_db.execute("INSERT INTO borrowed_scratch VALUES (2)")
            raise ValueError("block failed")
    test_db.commit()
    assert _values(test_db) == [1]


def test_borrowed_statement_failure_keeps_the_caller_usable(test_db) -> None:
    _scratch(test_db)
    with pytest.raises(psycopg.errors.UndefinedColumn):
        with savepoint(test_db, "borrowed_block", owns=False):
            test_db.execute("SELECT no_such_column FROM borrowed_scratch")
    test_db.execute("INSERT INTO borrowed_scratch VALUES (3)")
    test_db.commit()
    assert _values(test_db) == [1, 3]


@pytest.mark.parametrize("inner_error", [True, False])
def test_ended_borrowed_transaction_raises_savepoint_lost(
    test_db, inner_error: bool
) -> None:
    _scratch(test_db)
    with pytest.raises(
        SavepointLostError, match="savepoint_lost: savepoint lost_block"
    ):
        with savepoint(test_db, "lost_block", owns=False):
            test_db.rollback()
            if inner_error:
                raise RuntimeError("inner write failed")
    test_db.rollback()
    assert _values(test_db) == []


def test_owned_error_rolls_back_the_whole_transaction(test_db) -> None:
    _scratch(test_db)
    with pytest.raises(ValueError):
        with savepoint(test_db, "owned_block", owns=True):
            test_db.execute("INSERT INTO borrowed_scratch VALUES (2)")
            raise ValueError("block failed")
    assert _values(test_db) == []


def test_borrowed_status_preflight_refusal_keeps_caller_writes(test_db) -> None:
    insert_item(test_db, id=9811, workflow_id="issue", status="idea")
    test_db.commit()
    test_db.execute("UPDATE items SET title='caller write' WHERE id=9811")

    preflight = prepare_status_transition(
        test_db,
        item_id=9811,
        target_status="implementing",
        originator_actor_id=None,
        session_id="",
        expected_status="planned",
        commit=False,
    )

    assert preflight.failure is not None
    title = test_db.execute("SELECT title FROM items WHERE id=9811").fetchone()[0]
    assert title == "caller write"


def test_borrowed_rebind_refusal_keeps_caller_writes(monkeypatch) -> None:
    with test_database() as conn:
        environment_id = _yoke_development(conn)
        requirement_id = _stamp_requirement(
            conn, item_id=9812, environment_id=environment_id
        )
        row = conn.execute(
            "SELECT settings FROM environments WHERE id=%s", (int(environment_id),)
        ).fetchone()
        merged = json.dumps(
            apply_key_path_assignments(
                parse_settings_object(str(row[0] or "{}"), what="settings"),
                {"hosts.app": "https://app.example.test"},
            )
        )
        conn.execute(
            "UPDATE environments SET settings=%s WHERE id=%s",
            (merged, int(environment_id)),
        )
        conn.commit()
        before = conn.execute(
            "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()[0]
        conn.execute("UPDATE items SET title='caller write' WHERE id=9812")
        monkeypatch.setattr(
            qa_replacement_scope_guard,
            "linked_scope_refusal",
            lambda *_args, **_kwargs: "linked scope refused",
        )

        with pytest.raises(QaRebindError, match="linked scope refused"):
            rebind_requirement(
                conn,
                requirement_id=requirement_id,
                rationale="hosts.app was declared on the same environment",
                actor_id=2,
                commit=False,
            )

        title = conn.execute("SELECT title FROM items WHERE id=9812").fetchone()[0]
        digest = conn.execute(
            "SELECT execution_target_digest FROM qa_requirements WHERE id=%s",
            (requirement_id,),
        ).fetchone()[0]
        assert title == "caller write"
        assert digest == before
