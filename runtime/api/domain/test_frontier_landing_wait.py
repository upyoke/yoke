"""Committed work waiting only for its blockers to land waits everywhere.

One rule (:mod:`yoke_core.domain.frontier_landing_wait`) and one sentence on
the Frontier computation, ``frontier.list`` (the web Frontier and
``yoke frontier``), and the steering report.
"""

from __future__ import annotations

from runtime.api.fixtures.backlog import insert_item, insert_item_worktree
from yoke_core.domain.frontier_landing_wait import landing_wait_reason
from yoke_core.domain.frontier_list_read import list_frontier

SENTENCE = "Waiting on YOK-31, YOK-35 to merge"
COMMIT = "ebc7c423df0c81fcebb1330da401740d302a6db7"


def _edge(conn, dependent: int, blocker: int, gate: str, satisfaction: str) -> None:
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item_id, blocking_item_id, "
        "gate_point, satisfaction, source, rationale, created_at) "
        "VALUES (%s, %s, %s, %s, 'test', '', now())",
        (dependent, blocker, gate, satisfaction),
    )
    conn.commit()


def _lane(conn, item_id: int, commit_sha: str | None) -> None:
    insert_item_worktree(conn, item_id=item_id, branch=f"YOK-{item_id}")
    conn.execute(
        "UPDATE item_worktrees SET commit_sha = %s WHERE item_id = %s",
        (commit_sha, item_id),
    )
    conn.commit()


def _seed(conn) -> None:
    """YOK-33 is committed behind two merges; YOK-34 has the same edges, no commit."""
    for item_id, status in ((31, "implementing"), (35, "implementing")):
        insert_item(conn, id=item_id, title=f"blocker {item_id}", status=status)
    for item_id in (33, 34):
        insert_item(conn, id=item_id, title=f"built {item_id}", status="implementing")
        for blocker in (31, 35):
            _edge(conn, item_id, blocker, "integration", "fact:merged")
    _lane(conn, 33, COMMIT)
    _lane(conn, 34, None)


def test_the_sentence_names_each_blocker_once_per_condition():
    assert (
        landing_wait_reason([("YOK-31", "fact:merged")]) == "Waiting on YOK-31 to merge"
    )
    assert landing_wait_reason(
        [
            ("YOK-31", "fact:merged"),
            ("YOK-35", "fact:merged"),
            ("YOK-31", "fact:merged"),
            ("PLAT-2", "status:done"),
            ("YOK-9", "fact:deployed:prod"),
        ]
    ) == (
        "Waiting on YOK-31, YOK-35 to merge and PLAT-2 to be done "
        "and YOK-9 to be live on prod"
    )


def test_committed_work_waits_and_uncommitted_work_stays_ready(test_db):
    _seed(test_db)

    result = list_frontier()

    ready = {row["item_id"] for row in result["ready_rows"]}
    assert "YOK-33" not in ready
    assert "YOK-34" in ready
    rows = [row for row in result["blocked_rows"] if row["item_id"] == "YOK-33"]
    # One row per edge, never repeated by the later-gate pass.
    assert sorted(row["blocking_item"] for row in rows) == ["YOK-31", "YOK-35"]
    assert all(row["holds_pickup"] is True for row in rows)
    assert {row["why"] for row in rows} == {SENTENCE}
    free = [row for row in result["blocked_rows"] if row["item_id"] == "YOK-34"]
    assert len(free) == 2
    assert all(row["holds_pickup"] is False for row in free)


def test_a_start_gate_still_names_its_own_wait(test_db):
    _seed(test_db)
    insert_item(test_db, id=36, title="start blocker", status="implementing")
    _edge(test_db, 33, 36, "activation", "status:done")

    rows = [r for r in list_frontier()["blocked_rows"] if r["item_id"] == "YOK-33"]

    held = [row for row in rows if row["holds_pickup"]]
    assert [row["blocking_item"] for row in held] == ["YOK-36"]
    assert all(row["why"] != SENTENCE for row in rows)


def test_the_fleet_report_lists_it_as_waiting_to_land_not_available(test_db):
    from runtime.api.steering_fleet_test_helpers import compose, seed_steering_scope
    from yoke_core.domain.steering_fleet_report_projection import report_dict
    from yoke_core.domain.steering_fleet_report_render import report_body
    from yoke_core.domain.steering_fleet_report_render_available import (
        LANDING_WAIT_HEADING,
    )

    conn = seed_steering_scope(test_db)
    _seed(conn)

    report = compose(conn)

    assert "YOK-33" not in {entry.public_ref for entry in report.available}
    assert "YOK-34" in {entry.public_ref for entry in report.available}
    [wait] = report.landing_waits
    assert (wait.public_ref, wait.reason) == ("YOK-33", SENTENCE)
    body = report_body(report)
    assert f"{LANDING_WAIT_HEADING}:" in body
    assert f"  YOK-33  {SENTENCE}  built 33" in body
    assert report_dict(report)["landing_waits"][0]["reason"] == SENTENCE
