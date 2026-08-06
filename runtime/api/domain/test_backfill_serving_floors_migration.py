"""The ordered repair restores floors on legacy membership-ledger rows."""

from __future__ import annotations

import sqlite3

from yoke_core.domain import migrations
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_yoke_ledger import ensure_yoke_migration_ledger


def test_ordered_repair_backfills_the_destructive_history_entry() -> None:
    history = ordered_entries(history_dir(migrations))
    retirement = next(
        entry for entry in history
        if entry.name.endswith("retire_superseded_surfaces")
    )
    repair = next(
        entry for entry in history
        if entry.name.endswith("backfill_serving_floors")
    )
    module = load_migration_module(repair.path, repair.name)
    conn = sqlite3.connect(":memory:")
    ensure_yoke_migration_ledger(conn)
    conn.execute(
        "INSERT INTO applied_migrations "
        "(migration_name, applied_at, applied_by, minimum_serving_version) "
        "VALUES (?, 'now', 'legacy-stamp', NULL)",
        (retirement.name,),
    )

    module.apply(conn)
    module.invariants(conn)

    floor = conn.execute(
        "SELECT minimum_serving_version FROM applied_migrations "
        "WHERE migration_name = ?",
        (retirement.name,),
    ).fetchone()[0]
    assert floor
