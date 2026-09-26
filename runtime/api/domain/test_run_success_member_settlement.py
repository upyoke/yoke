"""A run reads succeeded only after every cleared member has closed.

Settlement is durable and non-terminal: a real close-out refusal or an
interrupted process leaves the run executing and settling, the members that
closed done, and the rest at their release wait with their claims. The next
re-drive replays settlement from there.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.test_deployment_delivery_close_out_notice import (
    COMPLETION_FLOW,
    _member_at_release_wait,
    _parked_owner,
    _project,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    HOLDER_B,
)
from runtime.api.domain.test_no_obligation_member_close_out import (
    _landing_evidence,
    _no_obligation,
    _ready_member,
)
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from yoke_core.domain import no_obligation_member_close_out as close_out
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.work_claim_target_sql import scope_int_sql

FIRST_ITEM = 9841
SECOND_ITEM = 9842
REASON = "nothing observable once deployed"


def _executing_run(conn: Any, run_id: str, members: tuple[int, ...]) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO deployment_runs (id,project_id,flow,status,created_at) "
        "VALUES (%s,1,%s,'executing',%s)",
        (run_id, COMPLETION_FLOW, now),
    )
    for item_id in members:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
            "VALUES (%s,%s,%s)",
            (run_id, item_id, now),
        )
    conn.commit()


def _run(conn: Any, run_id: str) -> tuple[str, bool]:
    row = conn.execute(
        "SELECT status,settling_at FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    return str(row["status"]), bool(row["settling_at"])


def _status(conn: Any, item_id: int) -> str:
    return conn.execute(
        "SELECT status FROM items WHERE id=%s", (item_id,)
    ).fetchone()["status"]


def _claim_held(conn: Any, item_id: int) -> bool:
    item_scope = scope_int_sql(conn, "scope", "item_id")
    return (
        conn.execute(
            "SELECT id FROM work_claims WHERE target_kind='item' "
            f"AND released_at IS NULL AND {item_scope}=%s",
            (item_id,),
        ).fetchone()
        is not None
    )


def _two_ready_members(conn: Any) -> str:
    _project(conn)
    for item_id, holder in ((FIRST_ITEM, HOLDER_A), (SECOND_ITEM, HOLDER_B)):
        _ready_member(conn, item_id, holder)
        _no_obligation(conn, item_id, reason=REASON)
    return _status(conn, FIRST_ITEM)


def test_a_refused_close_out_keeps_the_run_settling_until_re_driven(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    _no_obligation(test_db, FIRST_ITEM, reason=REASON)
    # Answered, but landed no evidence: its real close-out refuses.
    _member_at_release_wait(test_db, SECOND_ITEM)
    _parked_owner(test_db, HOLDER_B, SECOND_ITEM)
    _no_obligation(test_db, SECOND_ITEM, reason=REASON)
    release = _status(test_db, SECOND_ITEM)
    _executing_run(test_db, "run-settling", (FIRST_ITEM, SECOND_ITEM))

    refusal = cmd_update("run-settling", "status", "succeeded")

    assert refusal is not None and "is settling" in refusal
    assert render_item_ref(test_db, SECOND_ITEM) in refusal
    assert "yoke deployment-runs update run-settling status succeeded" in refusal
    assert _run(test_db, "run-settling") == ("executing", True)
    assert _status(test_db, FIRST_ITEM) == "done"
    assert _status(test_db, SECOND_ITEM) == release
    assert _claim_held(test_db, SECOND_ITEM)

    _landing_evidence(test_db, SECOND_ITEM)
    assert cmd_update("run-settling", "status", "succeeded") is None

    assert _run(test_db, "run-settling") == ("succeeded", True)
    assert _status(test_db, SECOND_ITEM) == "done"
    assert not _claim_held(test_db, SECOND_ITEM)


def test_an_interrupted_settlement_replays_on_the_next_re_drive(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    release = _two_ready_members(test_db)
    _executing_run(test_db, "run-interrupted", (FIRST_ITEM, SECOND_ITEM))
    real = close_out.close_out_satisfied_delivery_member
    closed: list[int] = []

    def _crash_after_first(conn, **kwargs):
        if closed:
            raise RuntimeError("settling process died")
        outcome = real(conn, **kwargs)
        closed.append(int(kwargs["item_id"]))
        return outcome

    monkeypatch.setattr(
        close_out, "close_out_satisfied_delivery_member", _crash_after_first
    )
    with pytest.raises(RuntimeError, match="settling process died"):
        cmd_update("run-interrupted", "status", "succeeded")

    [first] = closed
    second = SECOND_ITEM if first == FIRST_ITEM else FIRST_ITEM
    assert _run(test_db, "run-interrupted") == ("executing", True)
    assert _status(test_db, first) == "done"
    assert _status(test_db, second) == release
    assert _claim_held(test_db, second)

    monkeypatch.setattr(close_out, "close_out_satisfied_delivery_member", real)
    assert cmd_update("run-interrupted", "status", "succeeded") is None

    assert _run(test_db, "run-interrupted") == ("succeeded", True)
    assert _status(test_db, second) == "done"


def test_run_success_closes_every_ready_member_with_it(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _two_ready_members(test_db)
    _executing_run(test_db, "run-settled", (FIRST_ITEM, SECOND_ITEM))

    assert cmd_update("run-settled", "status", "succeeded") is None

    assert _run(test_db, "run-settled") == ("succeeded", True)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        assert _status(test_db, item_id) == "done"
        assert not _claim_held(test_db, item_id)


def test_an_uncleared_member_holds_the_run_until_answered(
    test_db: Any, monkeypatch
) -> None:
    """A final member with no post-deploy answer is never cleared, so no
    close-out even runs for it; success still waits for it by name."""
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    release = _status(test_db, FIRST_ITEM)
    _executing_run(test_db, "run-unanswered", (FIRST_ITEM,))

    refusal = cmd_update("run-unanswered", "status", "succeeded")

    assert refusal is not None
    assert render_item_ref(test_db, FIRST_ITEM) in refusal
    assert "post-deploy obligations on this run are not all answered" in refusal
    assert _run(test_db, "run-unanswered") == ("executing", True)
    assert _status(test_db, FIRST_ITEM) == release
    assert _claim_held(test_db, FIRST_ITEM)

    _no_obligation(test_db, FIRST_ITEM, reason=REASON)
    assert cmd_update("run-unanswered", "status", "succeeded") is None
    assert _run(test_db, "run-unanswered") == ("succeeded", True)
    assert _status(test_db, FIRST_ITEM) == "done"


def test_a_cancelled_duplicate_does_not_block_re_driving_the_settling_run(
    test_db: Any, monkeypatch
) -> None:
    """A duplicate enrolled the member and was cancelled before it executed;
    the settling run that actually delivered still closes the member."""
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    _no_obligation(test_db, FIRST_ITEM, reason=REASON)
    _executing_run(test_db, "run-delivering", (FIRST_ITEM,))
    test_db.execute(
        "UPDATE deployment_runs SET settling_at=%s, created_at=%s WHERE id=%s",
        ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "run-delivering"),
    )
    test_db.execute(
        "INSERT INTO deployment_runs (id,project_id,flow,status,created_at) "
        "VALUES ('run-duplicate',1,%s,'cancelled','2026-01-01T00:00:27Z')",
        (COMPLETION_FLOW,),
    )
    test_db.execute(
        "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
        "VALUES ('run-duplicate',%s,'2026-01-01T00:00:27Z')",
        (FIRST_ITEM,),
    )
    test_db.commit()

    assert cmd_update("run-delivering", "status", "succeeded") is None

    assert _run(test_db, "run-delivering") == ("succeeded", True)
    assert _status(test_db, FIRST_ITEM) == "done"
