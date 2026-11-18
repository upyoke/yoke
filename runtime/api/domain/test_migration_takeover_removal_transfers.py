"""0116 names the taking run on takeover removals recorded before the field.

Before ``transferred_to_run_id`` existed a takeover's removal entry carried
only its reason text, so a successor read it as an operator park and left the
item out of every later release. After the backfill the entry is a transfer
and no longer excludes the item; every other entry is untouched.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

import pytest

from runtime.api.fixtures.backlog import insert_deployment_run, insert_item
from yoke_core.domain import deployment_run_membership_removals as removals
from yoke_core.domain import migrations
from yoke_core.domain.migration_history import load_migration_module

TAKER = "run-20261118-020"
LEGACY = {
    "item_id": 9801,
    "reason": f"taken over by run {TAKER}, whose candidate contains this run's; "
    "the member's QA continues there",
    "removed_at": "2026-11-17T10:00:00.000000Z",
    "session_id": None,
    "actor_id": 2,
}
PARK = {
    "item_id": 9802,
    "reason": "Operator parked this member",
    "removed_at": "2026-11-17T09:00:00.000000Z",
    "session_id": None,
    "actor_id": 2,
}
TRANSFERRED = {**LEGACY, "item_id": 9803, "transferred_to_run_id": "run-other"}


def _migration():
    path = Path(migrations.__file__).parent / "0116_takeover_removal_transfers.py"
    return load_migration_module(path, path.stem)


@pytest.mark.parametrize("backend", ["postgres", "sqlite"])
def test_backfill_names_the_taker_on_legacy_entries_only(test_db, backend):
    conn = test_db if backend == "postgres" else sqlite3.connect(":memory:")
    marker = "%s" if backend == "postgres" else "?"
    conn.execute(
        "CREATE TEMP TABLE deployment_runs(id TEXT, membership_removals TEXT)"
    )
    stored = json.dumps([LEGACY, PARK, TRANSFERRED])
    for run_id, value in (("absorbed", stored), ("unreadable", "{"), ("empty", None)):
        conn.execute(
            f"INSERT INTO deployment_runs VALUES ({marker},{marker})", (run_id, value)
        )
    migration = _migration()

    migration.apply(conn)
    migration.apply(conn)
    migration.invariants(conn)

    rows = dict(conn.execute("SELECT id, membership_removals FROM deployment_runs"))
    assert json.loads(rows["absorbed"]) == [
        {**LEGACY, "transferred_to_run_id": TAKER},
        PARK,
        TRANSFERRED,
    ]
    assert rows["unreadable"] == "{"
    assert rows["empty"] is None


def test_backfilled_takeover_entry_no_longer_excludes_the_item(test_db):
    for item_id in (LEGACY["item_id"], PARK["item_id"]):
        insert_item(
            test_db,
            id=item_id,
            workflow_id="dash",
            status="release",
            merged_at="2026-11-16T00:00:00Z",
        )
    insert_deployment_run(test_db, id=TAKER, flow="flow-backfill")
    insert_deployment_run(
        test_db,
        id="run-absorbed",
        flow="flow-backfill",
        superseded_by_run_id=TAKER,
        membership_removals=json.dumps([LEGACY, PARK]),
    )
    assert removals.enrollment_removed_item_ids(test_db, TAKER) == {
        LEGACY["item_id"],
        PARK["item_id"],
    }

    _migration().apply(test_db)

    # The operator's own park still holds; the takeover entry was a transfer.
    assert removals.enrollment_removed_item_ids(test_db, TAKER) == {PARK["item_id"]}
    assert [park.item_id for park in removals.inherited_exclusions(test_db, TAKER)] == [
        PARK["item_id"]
    ]
