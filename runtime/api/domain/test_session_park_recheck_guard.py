"""A woken manual-wake QA holder parks only behind its own scheduled recheck."""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from unittest import mock

import pytest

from runtime.api.domain.deployment_qa_manual_wake_test_support import _requirement
from runtime.api.domain.deployment_qa_stage_dispatch_wake_test_support import (
    _WAITING,
    _member,
    _run,
)
from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    _claim,
    _project,
    seed_session,
)
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.session_mode import set_session_mode
from yoke_core.domain.session_scheduled_wake import (
    enqueue_due_session_wakes,
    schedule_session_wake,
)
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.work_claim_targets import make_item_target

RUN = "run-park-recheck-1"
MEMBER = 9811
REQUIREMENT = 98111


def _seed(conn: Any, *, wake_path: str = "manual", drive: bool = True) -> None:
    _project(conn)
    _run(conn, RUN)
    _member(conn, RUN, MEMBER)
    seed_session(conn, HOLDER_A)
    _claim(
        conn,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(MEMBER).scope_json(),
    )
    _requirement(
        conn, requirement_id=REQUIREMENT, run_id=RUN, member=MEMBER, wake_path=wake_path
    )
    conn.execute("UPDATE deployment_runs SET current_stage='item-qa' WHERE id=%s", (RUN,))
    conn.commit()
    if drive:
        with mock.patch(
            "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status",
            return_value=_WAITING,
        ):
            materialize_and_gate_deployment_qa_stage(
                conn, {"name": "item-qa", "scope": "item"}, run_id=RUN
            )


def _park(conn: Any) -> dict[str, Any]:
    return set_session_mode(conn, HOLDER_A, "parked", reason="waiting on evidence")


def _schedule(conn: Any, *, hours: int = 6) -> None:
    actor = conn.execute(
        "SELECT actor_id FROM harness_sessions WHERE session_id=%s", (HOLDER_A,)
    ).fetchone()[0]
    sent = schedule_session_wake(
        conn,
        session_id=HOLDER_A,
        actor_id=int(actor),
        at=utc_now() + timedelta(hours=hours),
        reason="check the required evidence",
    )
    assert sent["deduplicated"] is False
    conn.commit()


def test_woken_holder_without_a_future_recheck_cannot_park(test_db: Any) -> None:
    _seed(test_db)
    with pytest.raises(SessionError) as refused:
        _park(test_db)
    assert refused.value.code == "PARK_RECHECK_REQUIRED"
    message = refused.value.message
    assert f"requirement #{REQUIREMENT}" in message
    assert f"run {RUN} stage 'item-qa'" in message
    assert "yoke sessions wake schedule --at UTC_INSTANT --reason" in message
    mode = test_db.execute(
        "SELECT mode FROM harness_sessions WHERE session_id=%s", (HOLDER_A,)
    ).fetchone()[0]
    assert mode != "parked"


def test_future_recheck_lets_the_holder_park(test_db: Any) -> None:
    _seed(test_db)
    _schedule(test_db)
    assert _park(test_db)["mode"] == "parked"


def test_consumed_recheck_does_not_cover_the_next_park(test_db: Any) -> None:
    _seed(test_db)
    _schedule(test_db, hours=1)
    assert enqueue_due_session_wakes(test_db, now=utc_now() + timedelta(hours=2)) == 1
    test_db.commit()
    with pytest.raises(SessionError, match="no future scheduled recheck"):
        _park(test_db)


def test_deploy_wait_park_is_unaffected(test_db: Any) -> None:
    """The requirement's run is not executing its stage (a takeover successor)."""
    _seed(test_db)
    test_db.execute("UPDATE deployment_runs SET current_stage='deploy' WHERE id=%s", (RUN,))
    test_db.commit()
    assert _park(test_db)["mode"] == "parked"


def test_unopened_stage_and_merge_time_park_are_unaffected(test_db: Any) -> None:
    """No manual-wake notice was sent yet: the stage driver never reached it."""
    _seed(test_db, drive=False)
    assert _park(test_db)["mode"] == "parked"


def test_settled_requirement_releases_the_obligation(test_db: Any) -> None:
    _seed(test_db)
    test_db.execute(
        "UPDATE qa_requirements SET waived_at=%s WHERE id=%s",
        (utc_now(), REQUIREMENT),
    )
    test_db.commit()
    assert _park(test_db)["mode"] == "parked"


def test_released_claim_releases_the_obligation(test_db: Any) -> None:
    _seed(test_db)
    test_db.execute(
        "UPDATE work_claims SET released_at=%s WHERE session_id=%s",
        (utc_now(), HOLDER_A),
    )
    test_db.commit()
    assert _park(test_db)["mode"] == "parked"
