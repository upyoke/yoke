"""Coverage for the entry that strips retired migration-apply stages."""

from __future__ import annotations

import json
import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)

_ENTRY_SLUG = "drop_migration_apply_stages"
_HISTORY = ordered_entries(history_dir(migration_history_package))
_entry = next(entry for entry in _HISTORY if entry.name.endswith(_ENTRY_SLUG))
migration = load_migration_module(_entry.path, _entry.name)

_RETIRED = {
    "kind": "migration_apply",
    "model_name": "primary",
    "lifecycle_phase": "implementing",
}
_MERGED = {"name": "merged", "step_runner": "auto"}
_COMPLETE = {"name": "complete", "step_runner": "auto"}


def _connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE deployment_flows (id TEXT PRIMARY KEY, stages TEXT NOT NULL)"
    )
    return conn


def _insert(conn: sqlite3.Connection, flow_id: str, stages: list) -> None:
    conn.execute(
        "INSERT INTO deployment_flows VALUES (?, ?)", (flow_id, json.dumps(stages))
    )


def _stages(conn: sqlite3.Connection, flow_id: str) -> list:
    return json.loads(
        conn.execute(
            "SELECT stages FROM deployment_flows WHERE id=?", (flow_id,)
        ).fetchone()[0]
    )


def test_retired_stage_is_removed_and_the_rest_kept_in_order() -> None:
    conn = _connection()
    _insert(conn, "release", [_RETIRED, _MERGED, _COMPLETE])

    migration.apply(conn)
    migration.invariants(conn)

    assert _stages(conn, "release") == [_MERGED, _COMPLETE]


def test_entry_runs_before_the_vocabulary_entry() -> None:
    # The vocabulary entry revalidates every stage array and validation
    # rejects the retired kind, so stripping has to come first. Ordering is
    # the whole reason this entry exists separately.
    names = [entry.name for entry in _HISTORY]
    strip = next(i for i, n in enumerate(names) if n.endswith(_ENTRY_SLUG))
    vocabulary = next(
        i for i, n in enumerate(names) if n.endswith("stage_vocabulary")
    )
    assert strip < vocabulary


def test_flows_without_the_retired_kind_are_untouched() -> None:
    conn = _connection()
    _insert(conn, "clean", [_MERGED, _COMPLETE])
    before = _stages(conn, "clean")

    migration.apply(conn)

    assert _stages(conn, "clean") == before


def test_rerun_is_a_no_op() -> None:
    conn = _connection()
    _insert(conn, "release", [_RETIRED, _MERGED])
    migration.apply(conn)
    first = _stages(conn, "release")

    migration.apply(conn)
    migration.invariants(conn)

    assert _stages(conn, "release") == first


def test_a_flow_left_with_no_stages_is_refused() -> None:
    # Silently storing an empty definition would leave a flow that cannot
    # deploy and says nothing about why. That needs an operator, not a guess.
    conn = _connection()
    _insert(conn, "only-migration", [_RETIRED])

    with pytest.raises(AssertionError, match="no stages"):
        migration.apply(conn)


def test_invariants_reject_a_surviving_retired_stage() -> None:
    conn = _connection()
    _insert(conn, "release", [_RETIRED, _MERGED])

    with pytest.raises(AssertionError, match="retains a migration_apply stage"):
        migration.invariants(conn)
