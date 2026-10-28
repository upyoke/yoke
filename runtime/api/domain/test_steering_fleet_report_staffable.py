"""The available section offers only steps a new worker could advance.

A landed item waiting on its release or close-out, conduct past the WIP cap,
and an epic whose task a live session holds all used to read as "runnable and
unclaimed, staff these". Staffing them wasted a worker or reopened finished
work, while the landed and run sections kept naming the same items.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from runtime.api.domain.test_steering_fleet_report_deployment_run_facts import (
    _record_verdict,
    _seed_requirement,
    _seed_run,
)
from runtime.api.fixtures.backlog import insert_item
from runtime.api.steering_fleet_seed_rows import seed_session
from runtime.api.steering_fleet_test_helpers import (
    BEFORE_THAT,
    LONG_AGO,
    compose,
    seed_steering_scope,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import scheduler
from yoke_core.domain.work_claim_targets import make_epic_task_target

RUN_ID = "run-20260826-077"
TASK_WORKER = "task-worker"


def _item(conn, item_id: int, status: str, workflow_id: str = "dash", **columns):
    conn.execute("DELETE FROM items WHERE id=%s", (item_id,))
    insert_item(
        conn,
        id=item_id,
        title=f"Item {item_id}",
        workflow_id=workflow_id,
        status=status,
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
        spec=f"# Item {item_id}\n\nA real spec body.",
        **columns,
    )


def _returned_after_landing(conn, item_id: int, status: str) -> None:
    conn.execute(
        "INSERT INTO item_status_transitions "
        "(item_id, task_num, from_status, to_status, source, created_at) "
        "VALUES (%s, NULL, 'release', %s, 'test', %s)",
        (item_id, status, parse_instant(LONG_AGO)),
    )


def _live_task_claim(conn, epic_id: int) -> None:
    now = datetime.now(timezone.utc)
    seed_session(conn, TASK_WORKER, last_tool_call_at=now.isoformat())
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id, target_kind, scope, claimed_at, last_heartbeat, reason) "
        "VALUES (%s, 'epic_task', %s, %s, %s, 'task')",
        (TASK_WORKER, make_epic_task_target(epic_id, 1).scope_json(), now, now),
    )


@pytest.fixture
def seeded(test_db, monkeypatch):
    conn = seed_steering_scope(test_db)
    monkeypatch.setattr(scheduler, "resolve_default_wip_cap", lambda scope: 0)
    landed = {"merged_at": parse_instant(BEFORE_THAT)}
    _item(conn, 2, "release", **landed)  # waits only on its release
    _item(conn, 3, "reviewing-implementation", **landed)  # close-out only
    _item(conn, 4, "implementing", **landed)  # rework sent it back
    _returned_after_landing(conn, 4, "implementing")
    _item(conn, 5, "release", **landed)  # red in a live run, no holder
    _seed_run(conn, run_id=RUN_ID)
    _seed_requirement(conn, run_id=RUN_ID, requirement_id=951, member_item_id=5)
    _record_verdict(conn, requirement_id=951, verdict="fail")
    _item(conn, 6, "implementing")  # a live session works its task
    _live_task_claim(conn, 6)
    _item(conn, 7, "planned", workflow_id="epic")  # conduct past the WIP cap
    conn.commit()
    return conn


def test_available_lists_only_steps_a_new_worker_can_advance(seeded) -> None:
    report = compose(seeded)

    assert sorted(entry.public_ref for entry in report.available) == [
        "YOK-1",
        "YOK-4",
        "YOK-5",
    ]


def test_landed_and_run_sections_keep_their_rows(seeded) -> None:
    report = compose(seeded)

    assert sorted(entry.public_ref for entry in report.landed_open) == [
        "YOK-2",
        "YOK-3",
        "YOK-4",
        "YOK-5",
    ]
    assert [run.run_id for run in report.deployment_runs] == [RUN_ID]
    assert [red.requirement_id for red in report.deployment_runs[0].red] == [951]
