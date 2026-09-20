"""Permanent coverage for reconstructing landings from git history."""

from __future__ import annotations

import importlib

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.item_landings import ItemLanding, append_landing, landings_for_item
from yoke_core.domain.item_landings_reconstruct import LandingFact
from yoke_core.domain.item_landings_schema import (
    ORIGIN_RECONSTRUCTED,
    ORIGIN_RECORDED,
    ROUTE_MERGE_QUEUE,
)
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import removes_a_surface
from yoke_core.domain import migrations as migration_history_package

ENTRY_NAME = "0046_reconstruct_item_landings"
FIRST_MERGE = "b" * 40
FIRST_CANDIDATE = "c" * 40
SECOND_MERGE = "d" * 40
SECOND_CANDIDATE = "e" * 40
LANDED = "2026-09-19T22:15:00Z"


def _entry():
    directory = history_dir(migration_history_package)
    match = next(
        record for record in ordered_entries(directory)
        if record.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{match.name}.py", match.name)


entry = _entry()
# Import after load so tests share the same module object the applier uses
# when they pass facts in; the filename stem is the entry's identity.
MIGRATION = importlib.import_module(
    f"yoke_core.domain.migrations.{ENTRY_NAME}"
)


def _fact(sequence: int, merge: str, candidate: str, pr_number: str = "1379") -> LandingFact:
    return LandingFact(
        merge_sha=merge,
        candidate_sha=candidate,
        pr_number=pr_number,
        target_branch="main",
        landed_at=LANDED,
        project_sequence=sequence,
    )


def test_the_entry_is_additive_and_declares_no_serving_floor() -> None:
    directory = history_dir(migration_history_package)
    source = (directory / f"{ENTRY_NAME}.py").read_text()
    assert not removes_a_surface(source)
    assert not hasattr(entry, "MINIMUM_SERVING_VERSION")


def test_a_resolved_merge_is_inserted_as_reconstructed(test_db) -> None:
    insert_item(test_db, id=3307, title="Landed item", project_sequence=3307)
    counts = MIGRATION.apply_facts(test_db, [_fact(3307, FIRST_MERGE, FIRST_CANDIDATE)])
    test_db.commit()

    rows = landings_for_item(test_db, 3307)
    assert counts == {
        "written": 1,
        "skipped_unresolved": 0,
        "skipped_existing": 0,
    }
    assert len(rows) == 1
    assert rows[0].merge_sha == FIRST_MERGE
    assert rows[0].origin == ORIGIN_RECONSTRUCTED
    assert rows[0].route == ROUTE_MERGE_QUEUE
    assert rows[0].pr_number == "1379"


def test_a_merge_whose_item_does_not_exist_is_skipped(test_db) -> None:
    insert_item(test_db, id=1, title="Unrelated", project_sequence=1)
    counts = MIGRATION.apply_facts(test_db, [_fact(3307, FIRST_MERGE, FIRST_CANDIDATE)])
    test_db.commit()

    assert counts["skipped_unresolved"] == 1
    assert counts["written"] == 0
    assert landings_for_item(test_db, 1) == ()


def test_a_live_row_for_the_same_merge_is_left_recorded(test_db) -> None:
    insert_item(test_db, id=3307, title="Landed item", project_sequence=3307)
    append_landing(
        test_db,
        ItemLanding(
            item_id=3307,
            merge_sha=FIRST_MERGE,
            candidate_sha=FIRST_CANDIDATE,
            pr_number="1379",
            target_branch="main",
            route=ROUTE_MERGE_QUEUE,
            landed_at="2026-09-19T22:20:00Z",
            origin=ORIGIN_RECORDED,
        ),
    )
    counts = MIGRATION.apply_facts(test_db, [_fact(3307, FIRST_MERGE, FIRST_CANDIDATE)])
    test_db.commit()

    rows = landings_for_item(test_db, 3307)
    assert counts["skipped_existing"] == 1
    assert counts["written"] == 0
    assert len(rows) == 1
    assert rows[0].origin == ORIGIN_RECORDED
    assert rows[0].landed_at == "2026-09-19T22:20:00Z"


def test_a_second_apply_writes_nothing(test_db) -> None:
    insert_item(test_db, id=3307, title="Landed item", project_sequence=3307)
    facts = [_fact(3307, FIRST_MERGE, FIRST_CANDIDATE)]
    first = MIGRATION.apply_facts(test_db, facts)
    second = MIGRATION.apply_facts(test_db, facts)
    test_db.commit()

    assert first["written"] == 1
    assert second["written"] == 0
    assert second["skipped_existing"] == 1
    assert len(landings_for_item(test_db, 3307)) == 1


def test_two_merges_for_one_item_are_two_rows(test_db) -> None:
    insert_item(test_db, id=2363, title="Relanded item", project_sequence=2363)
    counts = MIGRATION.apply_facts(
        test_db,
        [
            _fact(2363, FIRST_MERGE, FIRST_CANDIDATE, pr_number="1"),
            _fact(2363, SECOND_MERGE, SECOND_CANDIDATE, pr_number="2"),
        ],
    )
    test_db.commit()

    rows = landings_for_item(test_db, 2363)
    assert counts["written"] == 2
    assert [row.merge_sha for row in rows] == [FIRST_MERGE, SECOND_MERGE]
    assert {row.origin for row in rows} == {ORIGIN_RECONSTRUCTED}


def test_packaged_facts_are_unique_on_sequence_and_merge() -> None:
    facts = MIGRATION.load_packaged_facts()
    keys = [(fact.project_sequence, fact.merge_sha) for fact in facts]
    assert facts, "the frozen git walk must ship with the entry"
    assert len(keys) == len(set(keys))
