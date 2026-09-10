"""Overview Shipping window: live runs plus terminals completed in the last 24h."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from runtime.api.conftest import insert_deployment_run
from yoke_core.domain.deployment_run_list_read import list_deployment_runs
from yoke_core.domain.deployment_runs_crud_query import DEFAULT_RUN_LIST_LIMIT


def _iso(hours_ago: int) -> str:
    stamp = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_overview_keeps_live_and_recent_terminals_before_limit(test_db):
    old = _iso(48)
    recent = _iso(2)
    # Newer old terminals would occupy a latest-N page and crowd the live run.
    for index in range(DEFAULT_RUN_LIST_LIMIT + 2):
        insert_deployment_run(
            test_db,
            id=f"run-old-{index:02d}",
            status="succeeded",
            created_at=_iso(index),
            completed_at=old,
        )
    insert_deployment_run(
        test_db,
        id="run-live",
        status="executing",
        created_at=old,
        current_stage="deploy",
    )
    insert_deployment_run(
        test_db,
        id="run-failed-recent",
        status="failed",
        created_at=old,
        completed_at=recent,
    )
    insert_deployment_run(
        test_db,
        id="run-cancelled-old",
        status="cancelled",
        created_at=old,
        completed_at=old,
    )
    test_db.commit()

    crowded = {
        row["id"] for row in list_deployment_runs(project=None, status=None, limit=20)
    }
    assert "run-live" not in crowded
    windowed = list_deployment_runs(
        project=None,
        status=None,
        limit=20,
        relevance="overview",
    )
    ids = {row["id"] for row in windowed}
    assert windowed[0]["id"] == "run-live"
    assert windowed[0]["overview_priority"] == 1
    assert "run-live" in ids
    assert "run-failed-recent" in ids
    assert "run-cancelled-old" not in ids
    assert not any(run_id.startswith("run-old-") for run_id in ids)
