"""A handoff row blocked on its snapshot clears once a snapshot has landed."""

from __future__ import annotations

from datetime import timedelta

from yoke_contracts.onboard_checklist import (
    BRANCH_CLONE_REMOTE,
    SETUP_HANDOFF_ROW_ID,
    STATUS_BLOCKED,
    STATUS_CONFIGURED,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.project_onboarding_runs import get_run, init_run, update_run


def _handoff(conn, run_id):
    rows = get_run(run_id, conn=conn)["rows"]
    return next(row for row in rows if row["row_id"] == SETUP_HANDOFF_ROW_ID)


def _blocked_run(conn, run_id):
    init_run(conn=conn, run_id=run_id, project_id=1, branch=BRANCH_CLONE_REMOTE)
    update_run(
        conn=conn,
        run_id=run_id,
        project_id=1,
        row_status={SETUP_HANDOFF_ROW_ID: STATUS_BLOCKED},
        blocker={SETUP_HANDOFF_ROW_ID: "Run `yoke project snapshot sync` first."},
    )
    stored = conn.execute(
        "SELECT updated_at FROM project_onboarding_checklist_rows "
        "WHERE run_id = %s AND row_id = %s",
        (run_id, SETUP_HANDOFF_ROW_ID),
    ).fetchone()
    return parse_instant(stored[0])


def _snapshot(conn, built_at):
    cur = conn.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        "VALUES (%s, %s, %s) RETURNING id",
        (1, "c" * 40, built_at),
    )
    return int(cur.fetchone()[0])


def test_blocked_row_stays_blocked_without_a_later_snapshot(test_db):
    blocked_at = _blocked_run(test_db, "handoff-unrepaired")
    _snapshot(test_db, blocked_at - timedelta(minutes=5))

    row = _handoff(test_db, "handoff-unrepaired")

    assert row["status"] == STATUS_BLOCKED
    assert "snapshot sync" in row["blocker"]


def test_snapshot_after_the_block_clears_the_row(test_db):
    blocked_at = _blocked_run(test_db, "handoff-repaired")
    snapshot_id = _snapshot(test_db, blocked_at + timedelta(minutes=5))

    row = _handoff(test_db, "handoff-repaired")

    assert row["status"] == STATUS_CONFIGURED
    assert row["blocker"] == ""
    assert row["evidence"]["snapshot_id"] == snapshot_id
    assert SETUP_HANDOFF_ROW_ID not in get_run(
        "handoff-repaired", conn=test_db
    )["summary"]["blocked_rows"]
