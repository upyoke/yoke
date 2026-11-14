"""Control-plane upkeep wakes item-QA members a run's exited driver never woke.

The measured miss: after ``yoke watch deploy`` exits at its QA wait, the
fleet report said "not woken: driver gone or stale; re-drive ... to send
it", and nothing sent it until someone re-drove the run.
"""

from __future__ import annotations

from runtime.api.fixtures.actor_roles import seed_project_role
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE,
    item_qa_stage_definitions,
    seed_run_standing_on_qa_stage,
)
from runtime.api.steering_fleet_test_helpers import (
    JUST_NOW,
    WORKER_SESSION,
    seed_message,
    seed_steering_scope,
)
from yoke_core.domain import control_plane_upkeep
from yoke_core.domain.deployment_qa_driverless_wake import wake_driverless_qa_waits
from yoke_core.domain.deployment_qa_stage_wake import (
    DEPLOYMENT_QA_STAGE_WAIT_PREFIX,
    stage_wait_idempotency_key,
)


RUN_ID = "run-20261113-021"
MEMBERS = (3459, 3461)
LINEAGE = "c" * 40


def _seed(conn, *, driver_released: bool = True):
    seed_run_standing_on_qa_stage(
        conn,
        run_id=RUN_ID,
        project="yoke",
        stages=item_qa_stage_definitions(None),
        members=MEMBERS,
        lineage=LINEAGE,
    )
    # Waiting members are still open; a closed one is no longer woken.
    conn.execute(
        "UPDATE items SET status='release' WHERE id = ANY(%s)", (list(MEMBERS),)
    )
    # The notice is sent as the recipient's actor, who works on the project.
    seed_project_role(
        conn, actor_id=1, project_id=1, role_name="operator", commit=False
    )
    # Give every seeded session a real hook route so a send can reach it.
    conn.execute(
        "UPDATE harness_sessions SET executor='claude-code', provider='anthropic', "
        "executor_surface='claude-cli', executor_version='2.1.238'"
    )
    if driver_released:
        release_seeded_driver(conn, RUN_ID)
    conn.commit()
    return conn


def _wait_keys(conn) -> list[str]:
    rows = conn.execute(
        "SELECT idempotency_key FROM session_messages "
        "WHERE idempotency_key LIKE %s ORDER BY idempotency_key",
        (f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}%",),
    ).fetchall()
    return [str(row[0]) for row in rows]


def _held_key(member: int) -> str:
    # A member with no pinned cases: the driver's held wake carries no digest.
    return stage_wait_idempotency_key(RUN_ID, ITEM_QA_STAGE, member, "")


def test_a_driverless_run_wakes_each_unsent_member_once(test_db) -> None:
    conn = _seed(seed_steering_scope(test_db))

    first = wake_driverless_qa_waits(conn)

    assert first["errors"] == []
    assert _wait_keys(conn) == sorted(_held_key(member) for member in MEMBERS)
    body = conn.execute(
        "SELECT body FROM session_messages WHERE idempotency_key=%s",
        (_held_key(MEMBERS[0]),),
    ).fetchone()[0]
    assert f"Deployment run {RUN_ID}" in body
    assert "re-drive" not in body

    second = wake_driverless_qa_waits(conn)

    assert second == {"sent": [], "errors": []}
    assert _wait_keys(conn) == sorted(_held_key(member) for member in MEMBERS)


def test_a_driver_sent_notice_is_not_sent_again(test_db) -> None:
    conn = _seed(seed_steering_scope(test_db))
    seed_message(
        conn,
        "driver-wake",
        sender=None,
        to=WORKER_SESSION,
        at=JUST_NOW,
        state="injected",
        idempotency_key=_held_key(MEMBERS[0]),
    )
    conn.commit()

    result = wake_driverless_qa_waits(conn)

    assert result["errors"] == []
    assert result["sent"] == [f"{RUN_ID}:{ITEM_QA_STAGE}:{MEMBERS[1]}"]
    assert _wait_keys(conn) == sorted(_held_key(member) for member in MEMBERS)


def test_a_closed_member_is_not_woken(test_db) -> None:
    conn = _seed(seed_steering_scope(test_db))
    conn.execute("UPDATE items SET status='done' WHERE id=%s", (MEMBERS[0],))
    conn.commit()

    assert wake_driverless_qa_waits(conn)["sent"] == [
        f"{RUN_ID}:{ITEM_QA_STAGE}:{MEMBERS[1]}"
    ]
    assert _wait_keys(conn) == [_held_key(MEMBERS[1])]


def test_a_live_driver_keeps_its_own_wakes(test_db) -> None:
    conn = _seed(seed_steering_scope(test_db), driver_released=False)

    assert wake_driverless_qa_waits(conn) == {"sent": [], "errors": []}
    assert _wait_keys(conn) == []


def test_upkeep_runs_the_wake_and_survives_its_failure(monkeypatch, caplog) -> None:
    ran: list[str] = []

    class _Conn:
        def rollback(self):
            ran.append("rollback")

        def close(self):
            ran.append("close")

    def boom(_conn):
        ran.append("wake")
        raise RuntimeError("wake read failed")

    from yoke_core.domain import db_helpers

    monkeypatch.setattr(db_helpers, "connect", lambda: _Conn())
    monkeypatch.setattr(control_plane_upkeep, "observe_pending_github_work", lambda c: None)
    monkeypatch.setattr(control_plane_upkeep, "replay_settlement_followups", lambda c: None)
    monkeypatch.setattr(control_plane_upkeep, "wake_driverless_qa_waits", boom)

    control_plane_upkeep.run_control_plane_upkeep()

    assert ran == ["wake", "rollback", "close"]
    assert "driverless item-QA wake failed" in caplog.text



def test_a_member_with_cases_uses_the_stage_status_digest(test_db) -> None:
    from yoke_core.domain.db_helpers import iso8601_now
    from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status

    conn = _seed(seed_steering_scope(test_db))
    conn.execute(
        "INSERT INTO qa_requirements(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,qa_kind,qa_phase,blocking_mode,"
        "requirement_source,method_id,created_at) VALUES (9201,%s,%s,%s,"
        "'browser','post_deploy','blocking','flow_derived','command',%s)",
        (RUN_ID, ITEM_QA_STAGE, MEMBERS[0], iso8601_now()),
    )
    conn.commit()

    assert wake_driverless_qa_waits(conn)["errors"] == []

    digest = deployment_qa_stage_status(
        conn,
        run_id=RUN_ID,
        stage_name=ITEM_QA_STAGE,
        member_item_id=MEMBERS[0],
        notify_acceptance=False,
    )["target_digest"]
    assert digest
    assert stage_wait_idempotency_key(RUN_ID, ITEM_QA_STAGE, MEMBERS[0], digest) in (
        _wait_keys(conn)
    )
