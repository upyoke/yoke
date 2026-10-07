"""The evidence gate reads history membership from the item's own lane."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import db_mutation_gate_implementing
from yoke_core.domain.db_mutation_gate import (
    check_implementing_to_reviewing_implementation_gate,
)
from runtime.api.domain.db_mutation_gate_test_helpers import (
    _seed_capability,
    _seed_project,
    _write_module,
    gate_db_context,
    seed_audit_row,
)
from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.migration_model_test import (
    TEST_MIGRATION_MODULES_DIR,
    governed_postgres_test_seed,
)

_ENTRY = "0002_lane_only_entry"


@pytest.fixture
def staged(tmp_path: Path):
    with gate_db_context(tmp_path) as (conn, repo_path):
        _seed_project(conn, "yoke", repo_path)
        _seed_capability(conn, "yoke", governed_postgres_test_seed())
        # The project checkout holds only what already merged.
        _write_module(repo_path, TEST_MIGRATION_MODULES_DIR, "0001_merged_entry")
        profile = {
            "state": "declared",
            "model_name": "primary",
            "mutation_intent": "apply",
            "migration_modules": [_ENTRY],
            "compatibility_class": "pre_merge_breaking",
            "migration_strategy": "additive_only",
        }
        insert_item(
            conn,
            id=4545,
            project="yoke",
            status="implementing",
            db_mutation_profile=json.dumps(profile, sort_keys=True),
        )
        seed_audit_row(
            repo_path,
            columns="migration_name, state, project_id, model_name, started_at",
            placeholders="?, 'rehearsed', ?, 'primary', ?",
            values=(_ENTRY, 1, "2026-10-07T00:00:00Z"),
        )
        yield conn, tmp_path


def _lane(monkeypatch, lane: Path | None) -> None:
    monkeypatch.setattr(
        db_mutation_gate_implementing, "_item_lane_path", lambda _c, _i: lane
    )


def test_lane_only_entry_passes_when_the_lane_carries_it(staged, monkeypatch) -> None:
    conn, tmp_path = staged
    lane = tmp_path / "lane"
    _write_module(lane, TEST_MIGRATION_MODULES_DIR, _ENTRY)
    _lane(monkeypatch, lane)

    outcome = check_implementing_to_reviewing_implementation_gate(4545, conn=conn)

    assert outcome.passed, outcome.errors


def test_lane_missing_the_entry_is_refused_by_name(staged, monkeypatch) -> None:
    conn, tmp_path = staged
    lane = tmp_path / "lane"
    (lane / TEST_MIGRATION_MODULES_DIR).mkdir(parents=True)
    _lane(monkeypatch, lane)

    outcome = check_implementing_to_reviewing_implementation_gate(4545, conn=conn)

    assert not outcome.passed
    assert any(
        "not found in the ordered migration history" in e for e in outcome.errors
    )


def test_no_local_lane_relies_on_the_receipt(staged, monkeypatch) -> None:
    conn, _tmp_path = staged
    _lane(monkeypatch, None)

    outcome = check_implementing_to_reviewing_implementation_gate(4545, conn=conn)

    assert outcome.passed, outcome.errors
