"""``item_dependencies`` ref columns hold true public refs, both directions.

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
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.shepherd_dependency import cmd_dependency_add
from yoke_core.domain.shepherd_dependency_enrich import cmd_dependency_enrich
from yoke_core.domain.shepherd_dependency_read import (
    UNRESOLVED_DIRECTION,
    dependency_rows,
)

# Internal ids and the project sequences they render as. The gap between
# the two columns is the whole point of the fixture.
DEPENDENT_ID, DEPENDENT_SEQUENCE = 900, 880
BLOCKER_ID, BLOCKER_SEQUENCE = 901, 881
CROSS_PROJECT_ID, CROSS_PROJECT_SEQUENCE = 902, 12

DEPENDENT_REF = f"YOK-{DEPENDENT_SEQUENCE}"
BLOCKER_REF = f"YOK-{BLOCKER_SEQUENCE}"
CROSS_PROJECT_REF = f"EXT-{CROSS_PROJECT_SEQUENCE}"
BLOCKER_TITLE = "Blocker whose sequence diverges"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


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


def _stored_refs(conn: Any) -> list[tuple[str, str]]:
    rows = conn.execute(
        "SELECT dependent_item, blocking_item FROM item_dependencies "
        "ORDER BY id"
    ).fetchall()
    return [(str(row[0]), str(row[1])) for row in rows]


def test_domain_writer_stores_public_refs_not_internal_ids(test_db):
    _seed_diverged_pair(test_db)

    cmd_dependency_add(test_db, DEPENDENT_REF, BLOCKER_REF, "operator")

    assert _stored_refs(test_db) == [(DEPENDENT_REF, BLOCKER_REF)]


def test_writer_renders_the_public_ref_when_handed_an_internal_id(test_db):
    """A bare internal id canonicalizes to the item's public ref."""
    _seed_diverged_pair(test_db)

    cmd_dependency_add(
        test_db, str(DEPENDENT_ID), str(BLOCKER_ID), "operator",
    )

    assert _stored_refs(test_db) == [(DEPENDENT_REF, BLOCKER_REF)]


def test_dispatcher_target_stores_the_public_ref(test_db):
    """``target.item_id`` is internal; the stored dependent is the ref."""
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
    assert _stored_refs(test_db) == [(DEPENDENT_REF, BLOCKER_REF)]


def test_cross_project_blocker_keeps_its_own_project_prefix(test_db):
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

    stored = _stored_refs(test_db)
    assert stored == [(DEPENDENT_REF, CROSS_PROJECT_REF)]
    assert not stored[0][1].startswith("YOK-")


def test_enrichment_joins_the_ref_to_the_item_it_names(test_db):
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
    # The internal ids are not the gated pair under the public-ref reading.
    assert check_hard_blocks.evaluate_blockers(BLOCKER_SEQUENCE) == []


def test_listing_reports_a_counterpart_that_names_no_item(test_db):
    """A dangling ref stays visible instead of dropping out of the graph."""
    _seed_diverged_pair(test_db)
    p = _p(test_db)
    test_db.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, gate_point, satisfaction, source, "
        "rationale, evidence_json, created_at) "
        f"VALUES ({p}, {p}, 'activation', 'status:done', 'operator', "
        f"'dangling', '{{}}', '2026-01-01T00:00:00Z')",
        (DEPENDENT_REF, "YOK-999999"),
    )
    test_db.commit()

    rows = dependency_rows(test_db, DEPENDENT_REF)

    assert [row["direction"] for row in rows] == [UNRESOLVED_DIRECTION]
    assert rows[0]["other_item"] == "YOK-999999"
