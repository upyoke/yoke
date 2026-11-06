# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item

from runtime.api.fixtures.pg_testdb import test_database

from yoke_core.domain import release_delivery_summary as summary_module

from yoke_core.domain.deployment_run_candidate_containment import (
    NOT_CONTAINED,
    CandidateContainment,
    ContainmentVerdict,
)

from yoke_core.domain.item_merge_receipt_document import record_entry

from yoke_core.domain.release_delivery_summary import (
    ReleaseCandidates,
    recorded_merge_shas_for_items,
)

FLOW = "yoke-hosted-production"


def _version_id(conn, item_id: int) -> int:
    row = conn.execute(
        "SELECT workflow_version_id FROM items WHERE id = %s", (item_id,)
    ).fetchone()
    return int(row["workflow_version_id"] if hasattr(row, "keys") else row[0])
