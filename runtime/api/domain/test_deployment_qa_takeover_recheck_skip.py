"""A takeover leaves a manual-only holder with a scheduled recheck asleep."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from runtime.api.domain.coordination_claim_test_support import PROJECT_YOKE
from runtime.api.domain.deployment_qa_manual_wake_test_support import _requirement
from runtime.api.domain.deployment_qa_stage_dispatch_wake_test_support import (
    _member,
    _run,
)
from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.deployment_qa_manual_wake import MANUAL_WAKE_RECHECK_INSTRUCTION
from yoke_core.domain.deployment_qa_takeover_notice import notify_moved_member_qa
from yoke_core.domain.session_scheduled_wake import schedule_session_wake
from yoke_core.domain.work_claim_targets import make_item_target, make_steering_target

OLD = "run-takeover-recheck-old"
NEW = "run-takeover-recheck-new"
SOAKING = 9911
OTHER = 9912
_STAGE = [{"name": "item-qa", "step_runner": "qa", "scope": "item"}]


def _seed(conn: Any) -> None:
    _project(conn)
    _run(conn, OLD)
    _run(conn, NEW)
    for session_id, item_id in ((HOLDER_A, SOAKING), (HOLDER_B, OTHER)):
        _member(conn, NEW, item_id)
        seed_session(conn, session_id)
        _claim(
            conn,
            session_id=session_id,
            target_kind="item",
            scope_json=make_item_target(item_id).scope_json(),
        )


def _schedule(conn: Any, session_id: str) -> None:
    actor = conn.execute(
        "SELECT actor_id FROM harness_sessions WHERE session_id=%s", (session_id,)
    ).fetchone()[0]
    schedule_session_wake(
        conn,
        session_id=session_id,
        actor_id=int(actor),
        at=utc_now() + timedelta(days=1),
        reason="check the required evidence",
    )
    conn.commit()


def _notify(conn: Any) -> None:
    notify_moved_member_qa(
        conn, old_id=OLD, new_id=NEW, item_ids=(SOAKING, OTHER), stages=_STAGE
    )
    conn.commit()


def _moved(conn: Any, item_id: int) -> list[str]:
    return _bodies(conn, f"deployment-qa-moved:{NEW}:{item_id}")


def test_manual_only_holder_with_a_future_recheck_is_not_woken(test_db: Any) -> None:
    _seed(test_db)
    _requirement(test_db, requirement_id=99111, run_id=NEW, member=SOAKING, wake_path="manual")
    _requirement(test_db, requirement_id=99121, run_id=NEW, member=OTHER, wake_path="manual")
    _schedule(test_db, HOLDER_A)
    _notify(test_db)
    assert _moved(test_db, SOAKING) == []
    [body] = _moved(test_db, OTHER)
    assert f"to run {NEW}" in body, "a holder without a recheck still hears"
    assert MANUAL_WAKE_RECHECK_INSTRUCTION in body


def test_holder_without_a_future_recheck_is_notified(test_db: Any) -> None:
    _seed(test_db)
    _requirement(test_db, requirement_id=99211, run_id=NEW, member=SOAKING, wake_path="manual")
    _notify(test_db)
    [body] = _moved(test_db, SOAKING)
    assert _recipients(test_db, f"deployment-qa-moved:{NEW}:{SOAKING}") == [HOLDER_A]
    assert "manual-wake QA moved" in body
    assert "No dispatch will wake you for it: check the evidence" in body
    assert MANUAL_WAKE_RECHECK_INSTRUCTION in body
    assert "dispatch will wake you;" not in body


def test_manual_only_holderless_member_gets_staffing_notice(test_db: Any) -> None:
    _seed(test_db)
    test_db.execute("UPDATE work_claims SET released_at=%s", (utc_now(),))
    _claim(
        test_db,
        session_id=HOLDER_B,
        target_kind="steering",
        scope_json=make_steering_target(PROJECT_YOKE).scope_json(),
    )
    _requirement(test_db, requirement_id=99221, run_id=NEW, member=SOAKING, wake_path="manual")
    _notify(test_db)
    [body] = _moved(test_db, SOAKING)
    assert _recipients(test_db, f"deployment-qa-moved:{NEW}:{SOAKING}") == [HOLDER_B]
    assert "Reaching the project's steering seat" in body
    assert "No dispatch will wake the claim holder" in body
    assert "staff this item so its holder can check the evidence" in body
    assert MANUAL_WAKE_RECHECK_INSTRUCTION in body
    assert "dispatch will wake you;" not in body


@pytest.mark.parametrize("mixed", [False, True])
def test_recheck_holder_with_an_automatic_requirement_is_notified(
    test_db: Any, mixed: bool
) -> None:
    _seed(test_db)
    if mixed:
        _requirement(test_db, requirement_id=99311, run_id=NEW, member=SOAKING, wake_path="manual")
    _requirement(test_db, requirement_id=99312, run_id=NEW, member=SOAKING, wake_path=None)
    _schedule(test_db, HOLDER_A)
    _notify(test_db)
    [body] = _moved(test_db, SOAKING)
    assert body == (
        f"YOK-{SOAKING}'s QA moved from run {OLD} to run {NEW}. "
        f"It opens when {NEW} reaches item QA stage 'item-qa'. "
        "The successor's QA dispatch will wake you; do not act on the "
        "predecessor's wake."
    )
