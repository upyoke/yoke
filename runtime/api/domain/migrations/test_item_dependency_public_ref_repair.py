"""Regression coverage for the dependency public-ref repair.

Every fixture deliberately gives an item a ``project_sequence`` that differs
from its ``items.id`` so a passing assertion cannot come from the two numbers
coinciding.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.migrations.item_dependency_public_ref_repair import (
    MAX_REWRITES,
    apply,
    classify,
    invariants,
)


# Fixture schema seeds project 1 as 'yoke'/'YOK' and project 2 as
# 'externalwebapp'/'EXT'.
YOKE_PROJECT_ID = 1
OTHER_PROJECT_ID = 2
OTHER_PREFIX = "EXT"


def _item(conn, *, item_id: int, sequence: int, project_id: int = YOKE_PROJECT_ID):
    insert_item(
        conn,
        id=item_id,
        project_id=project_id,
        project_sequence=sequence,
        status="planned",
    )


def _edge(conn, *, dependency_id: int, dependent: str, blocking: str, gate="activation"):
    conn.execute(
        "INSERT INTO item_dependencies "
        "(id, dependent_item, blocking_item, gate_point, source, created_at) "
        "VALUES (%s, %s, %s, %s, 'operator', '2026-01-01T00:00:00Z')",
        (dependency_id, dependent, blocking, gate),
    )
    conn.commit()


def _refs(conn):
    rows = conn.execute(
        "SELECT id, dependent_item, blocking_item FROM item_dependencies ORDER BY id"
    ).fetchall()
    return [(r["id"], r["dependent_item"], r["blocking_item"]) for r in rows]


def test_cross_project_ref_gains_its_own_project_prefix(test_db):
    _item(test_db, item_id=4101, sequence=71)
    _item(test_db, item_id=4102, sequence=88, project_id=OTHER_PROJECT_ID)
    _edge(test_db, dependency_id=1, dependent="YOK-4102", blocking="YOK-71")

    apply(test_db)
    test_db.commit()
    invariants(test_db)

    assert _refs(test_db) == [(1, f"{OTHER_PREFIX}-88", "YOK-71")]


def test_divergent_sequence_ref_is_rewritten_to_the_true_public_ref(test_db):
    _item(test_db, item_id=4201, sequence=4199)
    _item(test_db, item_id=4202, sequence=4198)
    _edge(test_db, dependency_id=1, dependent="YOK-4201", blocking="YOK-4198")

    apply(test_db)
    test_db.commit()
    invariants(test_db)

    assert _refs(test_db) == [(1, "YOK-4199", "YOK-4198")]


def test_already_correct_ref_is_untouched(test_db):
    _item(test_db, item_id=4301, sequence=61)
    _item(test_db, item_id=4302, sequence=62)
    _edge(test_db, dependency_id=1, dependent="YOK-61", blocking="YOK-62")

    rewrites, unresolvable, ambiguous = classify(test_db)
    assert (rewrites, unresolvable, ambiguous) == ([], [], [])

    apply(test_db)
    test_db.commit()
    invariants(test_db)

    assert _refs(test_db) == [(1, "YOK-61", "YOK-62")]


def test_ref_resolvable_under_neither_reading_is_left_alone_and_reported(
    test_db, capsys
):
    _item(test_db, item_id=4401, sequence=41)
    _edge(test_db, dependency_id=1, dependent="YOK-41", blocking="YOK-99999")

    _rewrites, unresolvable, _ambiguous = classify(test_db)
    assert unresolvable == [(1, "blocking_item", "YOK-99999")]

    apply(test_db)
    test_db.commit()
    invariants(test_db)

    assert _refs(test_db) == [(1, "YOK-41", "YOK-99999")]
    assert "UNRESOLVABLE 1 / blocking_item / YOK-99999" in capsys.readouterr().out


def test_repeated_apply_is_a_no_op(test_db):
    _item(test_db, item_id=4501, sequence=4499)
    _item(test_db, item_id=4502, sequence=52, project_id=OTHER_PROJECT_ID)
    _edge(test_db, dependency_id=1, dependent="YOK-4501", blocking="YOK-4502")

    apply(test_db)
    test_db.commit()
    first = _refs(test_db)
    assert first == [(1, "YOK-4499", f"{OTHER_PREFIX}-52")]

    rewrites, _unresolvable, _ambiguous = classify(test_db)
    assert rewrites == []

    apply(test_db)
    test_db.commit()
    invariants(test_db)

    assert _refs(test_db) == first


def test_rewrite_volume_above_the_bound_aborts_without_writing(test_db):
    for offset in range(MAX_REWRITES + 1):
        item_id = 4600 + offset
        _item(test_db, item_id=item_id, sequence=item_id - 500)
        _edge(
            test_db,
            dependency_id=offset + 1,
            dependent=f"YOK-{item_id}",
            blocking="YOK-4599",
            gate=f"activation-{offset}",
        )
    _item(test_db, item_id=4599, sequence=4599)

    before = _refs(test_db)
    with pytest.raises(RuntimeError, match="above the"):
        apply(test_db)

    assert _refs(test_db) == before
