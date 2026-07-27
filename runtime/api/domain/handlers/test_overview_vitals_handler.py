"""Overview state and momentum projection contracts.

The parity tests at the end pin the properties that make these numbers
comparable with the terminal board's: epics count as their tasks, the
issues meter measures delivery rather than intake, and task-only work
still registers as activity.
"""

from datetime import datetime, timezone
from unittest.mock import patch

from runtime.api.frontier_test_helpers import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.overview_vitals import handle_overview_vitals


def _request(payload=None):
    return FunctionCallRequest(
        function="overview.vitals.get",
        actor=ActorContext(actor_id="2", session_id=""),
        target=TargetRef(kind="global"),
        payload=payload or {},
    )


def test_vitals_returns_closed_state_buckets_and_dense_days():
    class _Connection:
        def close(self):
            pass

    with (
        patch(
            "yoke_core.domain.db_helpers.connect",
            return_value=_Connection(),
        ),
        patch(
            "yoke_core.domain.handlers.overview_vitals._selected_project_ids",
            return_value=[1],
        ),
        patch(
            "yoke_core.domain.handlers.overview_vitals._state_counts",
            return_value={
                "active": 2,
                "pipeline": 3,
                "backlog": 4,
                "blocked": 1,
                "frozen": 0,
                "done": 8,
                "unknown": 0,
            },
        ),
        patch(
            "yoke_core.domain.handlers.overview_vitals._day_counts",
            return_value={},
        ),
        patch(
            "yoke_core.domain.handlers.overview_vitals._strategy_timelines",
            return_value=[
                {
                    "project_id": 1,
                    "project": "yoke",
                    "emoji": "🐄",
                    "done_positions": [10, 80],
                    "labels": [{"position": 10, "label": "registry"}],
                    "queued_count": 2,
                    "vision_zones": [{"key": "1mo", "label": "web steering"}],
                }
            ],
        ),
    ):
        outcome = handle_overview_vitals(_request({"days": 3}))

    assert outcome.primary_success
    assert outcome.result_payload["state_counts"]["active"] == 2
    assert len(outcome.result_payload["momentum"]) == 3
    assert all(
        set(row) == {"day", "activity", "code", "issues", "strategy"}
        for row in outcome.result_payload["momentum"]
    )
    assert outcome.result_payload["strategy_timeline"][0]["queued_count"] == 2


def test_vitals_rejects_unbounded_window():
    outcome = handle_overview_vitals(_request({"days": 366}))
    assert not outcome.primary_success
    assert outcome.error.code == "payload_invalid"


def test_vitals_uses_the_authenticated_actors_visible_projects():
    from yoke_core.domain.handlers.overview_vitals import _visible_project_ids

    request = _request()
    conn = object()
    with patch(
        "yoke_core.domain.actor_project_visibility.actor_visible_project_ids",
        return_value={9, 3},
    ) as visible:
        result = _visible_project_ids(request, conn)

    assert result == [3, 9]
    visible.assert_called_once_with(conn, 2)


def test_vitals_executes_against_initialized_authority(test_db):
    outcome = handle_overview_vitals(_request({"days": 2}))
    assert outcome.primary_success
    assert len(outcome.result_payload["momentum"]) == 2
    assert {
        "active",
        "pipeline",
        "backlog",
        "blocked",
        "frozen",
        "done",
    }.issubset(outcome.result_payload["state_counts"])
    assert isinstance(outcome.result_payload["strategy_timeline"], list)


def _today():
    return datetime.now(timezone.utc).date().isoformat()


def _reset(test_db):
    """Empty the tables these facts derive from, creating them if absent."""
    from yoke_core.domain.item_status_transitions import ensure_schema

    ensure_schema(test_db)
    test_db.execute("DELETE FROM items")
    test_db.execute("DELETE FROM item_status_transitions")
    test_db.commit()


def _transition(test_db, item_id, to_status, *, task_num=None, day=None):
    test_db.execute(
        "INSERT INTO item_status_transitions "
        "(item_id, task_num, to_status, project_id, created_at) "
        "VALUES (%s, %s, %s, 1, %s)",
        (item_id, task_num, to_status, f"{day or _today()}T12:00:00Z"),
    )
    test_db.commit()


def _vitals(days=2):
    # Name the visible project explicitly: resolving it from the actor
    # would yield an empty set here, and every count would read zero for
    # a reason that has nothing to do with what is being asserted.
    outcome = handle_overview_vitals(FunctionCallRequest(
        function="overview.vitals.get",
        actor=ActorContext(actor_id="2", session_id=""),
        target=TargetRef(kind="global"),
        payload={"days": days},
        options={"visible_project_ids": [1]},
    ))
    assert outcome.primary_success, outcome.error
    return outcome.result_payload


def _today_momentum(payload):
    for row in payload["momentum"]:
        if row["day"] == _today():
            return row
    raise AssertionError("today missing from a dense momentum window")


def test_an_epic_counts_as_its_tasks_the_way_the_board_counts_it(test_db):
    # The board's stats box expands an epic into the work it contains. A
    # per-row count would show 1 here and disagree with every board render.
    _reset(test_db)
    insert_item(test_db, 8801, status="implementing", workflow="epic")
    for task_num in (1, 2, 3):
        test_db.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, title) "
            "VALUES (%s, %s, %s)",
            (8801, task_num, f"task {task_num}"),
        )
    test_db.commit()

    assert _vitals()["state_counts"]["active"] == 3


def test_an_epic_with_no_tasks_still_counts_as_one(test_db):
    _reset(test_db)
    insert_item(test_db, 8802, status="implementing", workflow="epic")
    test_db.commit()

    assert _vitals()["state_counts"]["active"] == 1


def test_the_issues_meter_counts_delivery_not_intake(test_db):
    # Two items filed today, one finished. The board's issues meter is a
    # delivery signal, so today reads 1 — filing work is not shipping it.
    _reset(test_db)
    insert_item(test_db, 8811, status="idea", created_at=f"{_today()}T09:00:00Z")
    insert_item(test_db, 8812, status="done", created_at=f"{_today()}T09:00:00Z")
    test_db.commit()
    _transition(test_db, 8812, "done")

    assert _today_momentum(_vitals())["issues"] == 1


def test_work_inside_an_epic_registers_as_activity(test_db):
    # Moving a task leaves the epic row untouched, so an item-level
    # activity read alone would call a busy day idle.
    _reset(test_db)
    insert_item(test_db, 8821, status="implementing", workflow="epic")
    test_db.commit()
    _transition(test_db, 8821, "implementing", task_num=1)
    _transition(test_db, 8821, "done", task_num=2)

    assert _today_momentum(_vitals())["activity"] >= 2


def test_one_task_touched_twice_in_a_day_counts_once(test_db):
    _reset(test_db)
    insert_item(test_db, 8831, status="implementing", workflow="epic")
    test_db.commit()
    _transition(test_db, 8831, "implementing", task_num=1)
    _transition(test_db, 8831, "done", task_num=1)

    assert _today_momentum(_vitals())["activity"] == 1
