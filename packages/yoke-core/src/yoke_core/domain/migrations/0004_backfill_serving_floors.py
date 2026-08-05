"""Restore rollback floors on ledger rows created before floors were stored."""

from __future__ import annotations


def _history():
    from yoke_core.domain import migrations
    from yoke_core.domain.migration_history import history_dir, ordered_entries

    return ordered_entries(history_dir(migrations))


def apply(conn) -> None:
    from yoke_core.domain.migration_serving_floor_ledger import (
        backfill_serving_floors,
    )

    backfill_serving_floors(conn, _history())


def invariants(conn) -> None:
    from yoke_core.domain.migration_serving_floor_ledger import (
        missing_declared_serving_floors,
    )

    missing = missing_declared_serving_floors(conn, _history())
    if missing:
        raise AssertionError(
            "applied migration rows still lack declared serving floors: "
            + ", ".join(missing)
        )
