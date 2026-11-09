"""Shared replay contract for every packaged migration entry."""

from __future__ import annotations

import pytest

from runtime.api.domain.migration_boot_test_helpers import entry_database
from yoke_core.domain import migrations
from yoke_core.domain.migration_fleet_applied_invariants import (
    verify_applied_history_invariants,
)
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import (
    declared_minimum,
    removes_a_surface,
)


@pytest.mark.parametrize("surface", ["empty", "current"])
def test_packaged_entries_replay_and_keep_their_contract(tmp_path, surface):
    entries = tuple(
        entry
        for entry in ordered_entries(history_dir(migrations))
        if not entry.is_baseline
    )
    modules = {
        entry.name: load_migration_module(entry.path, entry.name) for entry in entries
    }
    with entry_database(tmp_path, surface) as conn:
        for entry in entries:
            module = modules[entry.name]
            try:
                if removes_a_surface(entry.path.read_text()):
                    assert declared_minimum(module), (
                        "destructive entry needs a serving floor"
                    )
                for _ in range(2):
                    module.apply(conn)
                    report = verify_applied_history_invariants(
                        conn,
                        (entry.name,),
                        history=tuple(modules),
                        load_module=modules.__getitem__,
                    )
                    assert report.failure is None, report.failure
                conn.commit()
            except Exception as exc:
                exc.add_note(f"Migration entry {entry.name}, schema surface {surface}")
                raise
