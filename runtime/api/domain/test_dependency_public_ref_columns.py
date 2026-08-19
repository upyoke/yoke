"""``item_dependencies`` stores integer item ids; API tokens stay PREFIX-N.

Every item here is seeded with ``project_sequence`` deliberately diverged
from ``items.id`` so a prefix-strip reading and a project-sequence reading
name different items — the shape that makes a wrong reading observable.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures.backlog import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import check_hard_blocks, db_backend
from yoke_core.domain.handlers.shepherd_dependency_writes import (
    handle_shepherd_dependency_add,
)
from yoke_core.domain.path_claims_dependency_resolver_coordination import (
    has_forward_serial_edge,
    items_are_coordination_only,
)
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.shepherd_dependency import cmd_dependency_add
from yoke_core.domain.shepherd_dependency_enrich import cmd_dependency_enrich
from yoke_core.domain.shepherd_dependency_read import dependency_rows

# Internal ids and the project sequences they render as. The gap between
# the two columns is the whole point of the fixture.
DEPENDENT_ID, DEPENDENT_SEQUENCE = 900, 880
BLOCKER_ID, BLOCKER_SEQUENCE = 901, 881
CROSS_PROJECT_ID, CROSS_PROJECT_SEQUENCE = 902, 12

DEPENDENT_REF = f"YOK-{DEPENDENT_SEQUENCE}"
BLOCKER_REF = f"YOK-{BLOCKER_SEQUENCE}"
CROSS_PROJECT_REF = f"EXT-{CROSS_PROJECT_SEQUENCE}"
BLOCKER_TITLE = "Blocker whose sequence diverges"


class _CountingConnection:
    def __init__(self, inner: Any) -> None:
        self._conn = inner
        self.statement_count = 0

    def execute(self, sql: str, params: tuple = ()) -> Any:
        self.statement_count += 1
        return self._conn.execute(sql, params)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def _seed_diverged_pair(conn: Any) -> None:
    insert_item(
        conn,
        id=DEPENDENT_ID,
        project_sequence=DEPENDENT_SEQUENCE,
        title="Dependent whose sequence diverges",
        status="idea",
    )
    insert_item(
        conn,
        id=BLOCKER_ID,
        project_sequence=BLOCKER_SEQUENCE,
        title=BLOCKER_TITLE,
        status="idea",
    )
    conn.commit()


def _stored_ids(conn: Any) -> list[tuple[int, int]]:
    rows = conn.execute(
        "SELECT dependent_item_id, blocking_item_id FROM item_dependencies "
        "ORDER BY id"
    ).fetchall()
    return [(int(row[0]), int(row[1])) for row in rows]


def test_domain_writer_stores_item_ids_not_public_refs(test_db):
    _seed_diverged_pair(test_db)

    cmd_dependency_add(test_db, DEPENDENT_REF, BLOCKER_REF, "operator")

    assert _stored_ids(test_db) == [(DEPENDENT_ID, BLOCKER_ID)]


def test_writer_resolves_a_bare_internal_id_to_the_same_row(test_db):
    _seed_diverged_pair(test_db)

    cmd_dependency_add(
        test_db, str(DEPENDENT_ID), str(BLOCKER_ID), "operator",
    )

    assert _stored_ids(test_db) == [(DEPENDENT_ID, BLOCKER_ID)]


def test_dispatcher_target_stores_the_internal_id(test_db):
    """``target.item_id`` is internal; storage keeps that id."""
    _seed_diverged_pair(test_db)

    outcome = handle_shepherd_dependency_add(
        FunctionCallRequest(
            function="shepherd.dependency_add.run",
            actor=ActorContext(actor_id="op", session_id="s-1"),
            target=TargetRef(kind="item", item_id=DEPENDENT_ID),
            payload={
                "blocking_item": BLOCKER_REF,
                "source": "operator",
                "rationale": "diverged-sequence coverage",
            },
        )
    )

    assert outcome.primary_success, outcome.error
    assert outcome.result_payload["dependent_item"] == DEPENDENT_REF
    assert _stored_ids(test_db) == [(DEPENDENT_ID, BLOCKER_ID)]


def test_cross_project_blocker_round_trips_as_ids(test_db):
    seed_project_identities(test_db)
    _seed_diverged_pair(test_db)
    insert_item(
        test_db,
        id=CROSS_PROJECT_ID,
        project="externalwebapp",
        project_sequence=CROSS_PROJECT_SEQUENCE,
        title="Blocker in another project",
        status="idea",
    )
    test_db.commit()

    cmd_dependency_add(
        test_db, DEPENDENT_REF, CROSS_PROJECT_REF, "operator",
    )

    stored = _stored_ids(test_db)
    assert stored == [(DEPENDENT_ID, CROSS_PROJECT_ID)]
    listed = dependency_rows(test_db, DEPENDENT_REF)
    assert listed[0]["other_item"] == CROSS_PROJECT_REF
    assert not listed[0]["other_item"].startswith("YOK-")


def test_enrichment_joins_the_id_to_the_item_it_names(test_db):
    _seed_diverged_pair(test_db)
    cmd_dependency_add(test_db, DEPENDENT_REF, BLOCKER_REF, "operator")

    cmd_dependency_enrich(test_db)

    rationale = test_db.execute(
        "SELECT rationale FROM item_dependencies"
    ).fetchone()[0]
    assert BLOCKER_TITLE in rationale
    assert BLOCKER_REF in rationale


def test_hard_block_gate_sees_the_edge_written_for_a_diverged_item(test_db):
    """The writer and the canonical gate agree on which item is blocked."""
    _seed_diverged_pair(test_db)
    cmd_dependency_add(test_db, DEPENDENT_REF, BLOCKER_REF, "operator")

    blocked = check_hard_blocks.evaluate_blockers(DEPENDENT_ID)

    assert len(blocked) == 1
    assert BLOCKER_REF in blocked[0]
    assert BLOCKER_TITLE in blocked[0]
    assert check_hard_blocks.evaluate_blockers(BLOCKER_SEQUENCE) == []


def test_listing_projects_the_public_ref_from_stored_ids(test_db):
    _seed_diverged_pair(test_db)
    cmd_dependency_add(test_db, DEPENDENT_REF, BLOCKER_REF, "operator")

    rows = dependency_rows(test_db, DEPENDENT_REF)

    assert [row["direction"] for row in rows] == ["depends-on"]
    assert rows[0]["other_item"] == BLOCKER_REF


def test_gate_point_lookup_query_count_does_not_grow_with_table(test_db):
    _seed_diverged_pair(test_db)
    p = "%s" if db_backend.connection_is_postgres(test_db) else "?"
    test_db.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id, blocking_item_id, gate_point, satisfaction, source, "
        "rationale, evidence_json, created_at) "
        f"VALUES ({p}, {p}, 'coordination_only', 'fact:merged', 'test', "
        f"'independent edits', '{{}}', '2026-01-01T00:00:00Z')",
        (DEPENDENT_ID, BLOCKER_ID),
    )
    test_db.commit()

    def lookup_counts() -> tuple[int, int]:
        direct = _CountingConnection(test_db)
        assert not has_forward_serial_edge(
            direct,
            dependent_item_id=DEPENDENT_ID,
            blocking_item_id=BLOCKER_ID,
        )
        inter_item = _CountingConnection(test_db)
        assert items_are_coordination_only(
            inter_item,
            item_a_id=DEPENDENT_ID,
            item_b_id=BLOCKER_ID,
        )
        return direct.statement_count, inter_item.statement_count

    baseline = lookup_counts()
    for offset in range(30):
        extra_dep = 10000 + offset
        extra_blk = 20000 + offset
        insert_item(
            test_db,
            id=extra_dep,
            project_sequence=extra_dep,
            title=f"padding dependent {offset}",
            status="idea",
        )
        insert_item(
            test_db,
            id=extra_blk,
            project_sequence=extra_blk,
            title=f"padding blocker {offset}",
            status="idea",
        )
        test_db.execute(
            "INSERT INTO item_dependencies "
            "(dependent_item_id, blocking_item_id, gate_point, satisfaction, source, "
            "rationale, evidence_json, created_at) "
            f"VALUES ({p}, {p}, 'activation', 'status:done', 'test', "
            f"'padding row', '{{}}', '2026-01-01T00:00:00Z')",
            (extra_dep, extra_blk),
        )
    test_db.commit()

    expanded = lookup_counts()
    assert expanded == baseline
    assert max(expanded) <= 5
    assert not has_forward_serial_edge(
        test_db,
        dependent_item_id=DEPENDENT_ID,
        blocking_item_id=BLOCKER_ID,
    )


def test_gate_point_lookup_uses_stored_item_ids(test_db):
    _seed_diverged_pair(test_db)
    p = "%s" if db_backend.connection_is_postgres(test_db) else "?"
    test_db.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id, blocking_item_id, gate_point, satisfaction, source, "
        "rationale, evidence_json, created_at) "
        f"VALUES ({p}, {p}, 'activation', 'status:done', 'test', "
        f"'numeric ids', '{{}}', '2026-01-01T00:00:00Z')",
        (DEPENDENT_ID, BLOCKER_ID),
    )
    test_db.commit()

    assert has_forward_serial_edge(
        test_db,
        dependent_item_id=DEPENDENT_ID,
        blocking_item_id=BLOCKER_ID,
    )
    assert not items_are_coordination_only(
        test_db,
        item_a_id=DEPENDENT_ID,
        item_b_id=BLOCKER_ID,
    )
