"""The run already owning a merged item's delivery, read from durable facts.

Custody answers for a run that names the item; the bound-source record
answers for another project's in-flight release that ships this project's
code. A carrier whose pinned commit lacks the merge blocks a competing run
and never claims the item.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_insert_support import ensure_project_id
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.carried_release_candidate import (
    insert_run,
    item_ref,
    release_repository,
    serve_repository,
)
from yoke_core.domain.deployment_item_delivery_owner import (
    CARRIER_IN_FLIGHT,
    delivery_owner,
)
from yoke_core.domain.item_merge_receipt_document import record_entry

FLOW = "delivery-owner-flow"
ITEM_ID = 9611


def _merged(conn: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    insert_item(
        conn,
        id=ITEM_ID,
        project_sequence=ITEM_ID,
        workflow_id="dash",
        status="release",
        deployment_flow=FLOW,
        merged_at="2026-09-14T00:10:00Z",
    )
    conn.commit()
    ref = item_ref(conn, ITEM_ID)
    repo, baseline, landing = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    record_entry(
        conn, item_id=ITEM_ID, branch=ref, target="main", merge_sha=landing
    )
    conn.commit()
    return ref, baseline, landing


def _carrier_run(conn: Any, run_id: str, pinned: str) -> None:
    carrier = ensure_project_id(conn, "carrier", ts=datetime.now(timezone.utc))
    bound = {"schema": 1, "projects": [{"project_id": 1, "commit_sha": pinned}]}
    insert_run(
        conn,
        run_id,
        lineage="e" * 40,
        status="executing",
        flow="carrier-release",
        project_id=carrier,
        bound_sources=json.dumps(bound),
    )


def _owner(conn: Any):
    slug = conn.execute("SELECT slug FROM projects WHERE id = 1").fetchone()[0]
    return delivery_owner(ITEM_ID, str(slug), "")


def test_nothing_owns_an_unheld_landing(test_db, tmp_path, monkeypatch):
    _merged(test_db, tmp_path, monkeypatch)

    assert _owner(test_db) is None


def test_a_member_run_holding_the_landing_is_returned(test_db, tmp_path, monkeypatch):
    ref, _baseline, landing = _merged(test_db, tmp_path, monkeypatch)
    insert_run(test_db, "run-holder", lineage=landing, status="created", flow=FLOW)
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES ('run-holder',%s,'2026-09-14T00:30:00Z')",
        (ITEM_ID,),
    )
    test_db.commit()

    owner = _owner(test_db)

    assert (owner.run_id, owner.carries) == ("run-holder", True)
    assert "no second run was created" in owner.message
    assert ref in owner.message


def test_a_bound_release_carrying_the_merge_is_the_carrier(
    test_db, tmp_path, monkeypatch
):
    _ref, _baseline, landing = _merged(test_db, tmp_path, monkeypatch)
    _carrier_run(test_db, "run-carrier", landing)

    owner = _owner(test_db)

    assert (owner.run_id, owner.carries, owner.project) == (
        "run-carrier",
        True,
        "carrier",
    )
    assert f"contains its merge {landing}" in owner.message


def test_a_bound_release_without_the_merge_blocks_and_claims_nothing(
    test_db, tmp_path, monkeypatch
):
    ref, baseline, landing = _merged(test_db, tmp_path, monkeypatch)
    _carrier_run(test_db, "run-carrier", baseline)

    owner = _owner(test_db)

    assert (owner.run_id, owner.carries, owner.code) == (
        "run-carrier",
        False,
        CARRIER_IN_FLIGHT,
    )
    assert f"its pinned commit {baseline} does not contain {ref}'s merge" in owner.message
    assert "Nothing was created" in owner.message
    assert f"yoke deployment-runs start-for-item {ref}" in owner.message
    assert "rides" not in owner.message


def test_a_holder_in_another_environment_does_not_answer(
    test_db, tmp_path, monkeypatch
):
    _ref, _baseline, landing = _merged(test_db, tmp_path, monkeypatch)
    insert_run(test_db, "run-stage", lineage=landing, status="succeeded", flow=FLOW)
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES ('run-stage',%s,'2026-09-14T00:30:00Z')",
        (ITEM_ID,),
    )
    test_db.commit()
    slug = test_db.execute("SELECT slug FROM projects WHERE id = 1").fetchone()[0]

    # The stage run delivered it; a production start still gets its own run.
    assert delivery_owner(ITEM_ID, str(slug), "prod") is None
    assert delivery_owner(ITEM_ID, str(slug), "").run_id == "run-stage"
