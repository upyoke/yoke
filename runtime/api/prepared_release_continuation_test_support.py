# ruff: noqa: E402, F401, F811
"""Shared setup for tests in this directory."""

from __future__ import annotations

import pytest

from yoke_core.domain import deployment_runs as dr

from yoke_core.domain import deployment_runs_crud_mutate as mutate

from yoke_core.domain.deployment_run_lineage_rebind import (
    lineage_of,
    refuse_lineage_write,
)

from yoke_core.domain.deployment_run_pair_obligations import (
    prepared_runs_awaiting_item,
    split_pending_pair_merges,
    split_runs_by_target_environment,
)

from yoke_core.domain.deployment_runs_validation import cmd_validate_composition

from runtime.api.deployment_runs_full_helpers_test_support import (
    _conn,
    _insert_delivery_ready_item,
    db_path,
)

PRODUCER_ITEM = 9101

CONSUMER_ITEM = 9102

MERGE_COMMIT = "a" * 40

OTHER_COMMIT = "b" * 40


def _pair_edge(db_path: str, dependent: int, blocker: int) -> None:
    """Record the delivery-waits-for-that-merge edge the runtime reads."""
    conn = _conn(db_path)
    try:
        conn.execute(
            "INSERT INTO item_dependencies ("
            "dependent_item_id, blocking_item_id, gate_point, satisfaction, "
            "source, rationale, created_at"
            ") VALUES (%s, %s, 'integration', 'fact:merged', 'operator', "
            "'breaking contract pair', '2026-07-28T00:00:00Z')",
            (dependent, blocker),
        )
        conn.commit()
    finally:
        conn.close()


def _mark_merged(db_path: str, item_id: int) -> None:
    conn = _conn(db_path)
    try:
        conn.execute(
            "UPDATE items SET merged_at='2026-07-28T01:00:00Z' WHERE id=%s",
            (item_id,),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def prepared_run(db_path):
    """A run prepared for the producer while the consumer has not merged."""
    _insert_delivery_ready_item(db_path, PRODUCER_ITEM)
    _insert_delivery_ready_item(db_path, CONSUMER_ITEM)
    _pair_edge(db_path, PRODUCER_ITEM, CONSUMER_ITEM)
    run_id = dr.cmd_create_run("yoke", "yoke-internal", db_path=db_path)
    mutate.cmd_add_item(run_id, PRODUCER_ITEM, db_path=db_path)
    return run_id
