"""The item's merge receipt outlives cleanup, crashes, and missing telemetry.

Every fact these tests assert is read after the branch ref and the lane
directory are gone, which is exactly when a merge has nothing left to
re-derive from. Nothing here writes or reads an event row: the storage
boundary is the point, so a test that leaned on telemetry would not prove it.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import item_merge_receipt_document as document
from yoke_core.domain.item_json_sections import read_json_section

from runtime.api.fixtures.backlog import insert_item

BRANCH = "ITEM-1"
TARGET = "main"
LANDING_SHA = "a" * 40
MERGE_SHA = "b" * 40


def _item(conn: Any, item_id: int = 10) -> int:
    insert_item(conn, id=item_id, status="implementing")
    return item_id


def test_a_pre_merge_write_and_a_completed_write_fold_into_one_entry(test_db):
    """The merge writes twice; neither half may erase the other's facts."""
    item_id = _item(test_db)
    document.record_entry(
        test_db,
        item_id=item_id,
        branch=BRANCH,
        target=TARGET,
        commit_sha=LANDING_SHA,
        touched_files=["feature.py"],
    )
    document.record_entry(
        test_db,
        item_id=item_id,
        branch=BRANCH,
        target=TARGET,
        merge_sha=MERGE_SHA,
        check_runs=[{"name": "ci", "conclusion": "success"}],
    )

    entry = document.find_entry(test_db, item_id, branch=BRANCH, target=TARGET)

    assert entry is not None
    assert entry["commit_sha"] == LANDING_SHA
    assert entry["merge_sha"] == MERGE_SHA
    assert entry["touched_files"] == ["feature.py"]
    assert entry["check_runs"][0]["name"] == "ci"


def test_the_receipt_survives_with_no_event_rows_at_all(test_db):
    """The document is the storage boundary; telemetry is not consulted."""
    item_id = _item(test_db)
    document.record_entry(
        test_db,
        item_id=item_id,
        branch=BRANCH,
        target=TARGET,
        commit_sha=LANDING_SHA,
        merge_sha=MERGE_SHA,
    )
    test_db.execute("DELETE FROM events")

    assert document.landing_shas(test_db, item_id) == [LANDING_SHA, MERGE_SHA]


def test_a_lane_query_matches_on_branch_when_the_target_is_unknown(test_db):
    """Lane retirement knows the branch its row recorded, not the target."""
    item_id = _item(test_db)
    document.record_entry(
        test_db,
        item_id=item_id,
        branch=BRANCH,
        target=TARGET,
        commit_sha=LANDING_SHA,
        merge_sha=MERGE_SHA,
    )

    entry = document.find_entry(test_db, item_id, branch=BRANCH)

    assert entry is not None and entry["merge_sha"] == MERGE_SHA
    assert document.find_entry(test_db, item_id, branch="other-lane") is None


def test_a_failure_is_recorded_and_a_landed_merge_settles_it(test_db):
    """Current state, not chronology: the landing drops the failure."""
    item_id = _item(test_db)
    document.record_entry(
        test_db,
        item_id=item_id,
        branch=BRANCH,
        target=TARGET,
        failure=document.build_failure(
            label="CI checks failed", phase="pr-checks-poll", reason="1 failing",
        ),
    )

    assert document.current_failures(test_db, [item_id]) == {
        item_id: "CI checks failed"
    }

    document.record_entry(
        test_db,
        item_id=item_id,
        branch=BRANCH,
        target=TARGET,
        merge_sha=MERGE_SHA,
    )

    assert document.current_failures(test_db, [item_id]) == {}


def test_an_explicit_settlement_clears_a_failure_with_no_merge_commit(test_db):
    """A lane merge settles through its success, not through a merge sha."""
    item_id = _item(test_db)
    document.record_entry(
        test_db,
        item_id=item_id,
        branch=BRANCH,
        target=TARGET,
        failure=document.build_failure(label="merge failed", reason="exit 1"),
    )
    document.record_entry(
        test_db, item_id=item_id, branch=BRANCH, target=TARGET, settled=True,
    )

    assert document.current_failures(test_db, [item_id]) == {}


def test_two_merge_identities_on_one_item_stay_separate(test_db):
    """A second branch's failure never settles the first one's."""
    item_id = _item(test_db)
    document.record_entry(
        test_db,
        item_id=item_id,
        branch=BRANCH,
        target=TARGET,
        merge_sha=MERGE_SHA,
    )
    document.record_entry(
        test_db,
        item_id=item_id,
        branch="second-lane",
        target=TARGET,
        failure=document.build_failure(label="merge failed"),
    )

    assert document.current_failures(test_db, [item_id]) == {
        item_id: "merge failed"
    }
    first = document.find_entry(test_db, item_id, branch=BRANCH, target=TARGET)
    assert first is not None and first["merge_sha"] == MERGE_SHA


def test_release_attribution_reads_both_commits_the_receipt_names(test_db):
    """A range may contain either the merge or the implementation commit."""
    item_id = _item(test_db)
    document.record_entry(
        test_db,
        item_id=item_id,
        branch=BRANCH,
        target=TARGET,
        commit_sha=LANDING_SHA,
        merge_sha=MERGE_SHA,
    )

    pairs = set(document.merge_identities(test_db, 1))

    assert pairs == {(item_id, LANDING_SHA), (item_id, MERGE_SHA)}


def test_an_unparseable_document_reads_as_no_receipt(test_db):
    """Corruption is absence, never a partially believed receipt."""
    item_id = _item(test_db)
    document.record_entry(
        test_db, item_id=item_id, branch=BRANCH, target=TARGET,
        commit_sha=LANDING_SHA,
    )
    test_db.execute(
        "UPDATE item_sections SET content = %s "
        "WHERE item_id = %s AND section_name = %s",
        ("not json", item_id, document.MERGE_RECEIPTS_SECTION),
    )

    assert document.read_entries(test_db, item_id) == {}
    assert document.landing_shas(test_db, item_id) == ["", ""]


def test_the_document_is_stored_under_its_own_item_section(test_db):
    """The durable owner is the item, which outlives every merge artifact."""
    item_id = _item(test_db)
    document.record_entry(
        test_db, item_id=item_id, branch=BRANCH, target=TARGET,
        commit_sha=LANDING_SHA,
    )

    stored = read_json_section(
        test_db, item_id=item_id, section=document.MERGE_RECEIPTS_SECTION,
    )

    assert stored is not None
    assert document.entry_key(BRANCH, TARGET) in stored["receipts"]
