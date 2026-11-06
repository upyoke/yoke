"""A member its owner closed during automatic close-out counts as closed."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    COMPLETION_FLOW,
    _project,
    _run,
)
from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    _recipients,
)
from runtime.api.domain.no_obligation_member_close_out_test_support import _ready_member
from runtime.api.domain.run_success_member_settlement_test_support import _executing_run
from runtime.api.domain.satisfied_delivery_member_close_out_test_support import (
    _settled_member_requirement,
    _waived_item_requirement,
)
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from yoke_core.domain import workflow_status_transition_preflight as preflight_mod
from yoke_core.domain.deployment_delivery_close_out_notice import (
    delivery_cleared_idempotency_key,
    notify_delivery_cleared,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain import backlog_status_write_precondition as write_precondition
from yoke_core.domain import deployment_qa_member_acceptance_notice as acceptance_notice
from yoke_core.domain.deployment_qa_member_acceptance_notice import (
    item_qa_accepted_idempotency_key,
    notify_item_qa_accepted,
)


OWNER_CLOSED_ITEM = 9831


def _owner_closes_before_preflight(monkeypatch, conn: Any, item_id: int) -> None:
    """The owner's done write lands between close-out's status read and preflight."""
    real = preflight_mod.prepare_status_transition

    def racing(db: Any, **kwargs: Any):
        if kwargs.get("item_id") == item_id:
            conn.execute("UPDATE items SET status='done' WHERE id=%s", (item_id,))
            conn.commit()
        return real(db, **kwargs)

    monkeypatch.setattr(preflight_mod, "prepare_status_transition", racing)


def _status(conn: Any, table: str, row_id: Any) -> str:
    return conn.execute(
        f"SELECT status FROM {table} WHERE id=%s", (row_id,)
    ).fetchone()["status"]


def test_owner_closed_member_sends_no_failed_close_out_notice(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, OWNER_CLOSED_ITEM, HOLDER_A)
    run_id = "run-owner-closed-notice"
    _run(test_db, run_id, flow=COMPLETION_FLOW, members=(OWNER_CLOSED_ITEM,))
    _settled_member_requirement(
        test_db, item_id=OWNER_CLOSED_ITEM, run_id=run_id, resolution="pass"
    )
    _owner_closes_before_preflight(monkeypatch, test_db, OWNER_CLOSED_ITEM)

    [report] = notify_delivery_cleared(test_db, run_id=run_id)

    assert report["delivery"] == "closed"
    key = delivery_cleared_idempotency_key(OWNER_CLOSED_ITEM, run_id)
    assert _recipients(test_db, key) == []
    assert _status(test_db, "items", OWNER_CLOSED_ITEM) == "done"


def test_collective_finalization_succeeds_for_an_owner_closed_member(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, OWNER_CLOSED_ITEM, HOLDER_A)
    _waived_item_requirement(test_db, OWNER_CLOSED_ITEM)
    run_id = "run-owner-closed-collective"
    _executing_run(test_db, run_id, (OWNER_CLOSED_ITEM,))
    _owner_closes_before_preflight(monkeypatch, test_db, OWNER_CLOSED_ITEM)

    assert cmd_update(run_id, "status", "succeeded") is None

    assert _status(test_db, "items", OWNER_CLOSED_ITEM) == "done"
    assert _status(test_db, "deployment_runs", run_id) == "succeeded"


def _move_before_status_lock(monkeypatch, item_id: int, target: str) -> None:
    """Model the competing write observed after the lock wait, without I/O."""
    real = write_precondition.lock_item_workflow_bindings

    def racing(conn: Any, item_ids: Any):
        if item_id in item_ids:
            conn.execute("UPDATE items SET status=%s WHERE id=%s", (target, item_id))
        return real(conn, item_ids)

    monkeypatch.setattr(write_precondition, "lock_item_workflow_bindings", racing)


@pytest.mark.parametrize("target", ["done", "implementing"])
def test_status_write_race_only_suppresses_notice_for_done(
    test_db: Any, monkeypatch, target: str
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, OWNER_CLOSED_ITEM, HOLDER_A)
    run_id = "run-status-lock-notice"
    _run(test_db, run_id, flow=COMPLETION_FLOW, members=(OWNER_CLOSED_ITEM,))
    _settled_member_requirement(
        test_db, item_id=OWNER_CLOSED_ITEM, run_id=run_id, resolution="pass"
    )
    # This completed delivery qualifies for close-out; exercise the acceptance
    # notice's delivered-member route independently of its executing-run filter.
    monkeypatch.setattr(
        acceptance_notice, "independent_member_delivery_ready", lambda *a, **kw: True
    )
    _move_before_status_lock(monkeypatch, OWNER_CLOSED_ITEM, target)

    result = notify_item_qa_accepted(test_db, run_id=run_id, item_id=OWNER_CLOSED_ITEM)

    key = item_qa_accepted_idempotency_key(OWNER_CLOSED_ITEM, run_id)
    notices = test_db.execute(
        "SELECT body FROM session_messages WHERE idempotency_key LIKE %s",
        (key + "%",),
    ).fetchall()
    if target == "done":
        assert result == "closed"
        assert notices == []
        assert _status(test_db, "items", OWNER_CLOSED_ITEM) == "done"
    else:
        assert result in {"delivered", "undelivered"}
        [row] = notices
        body = row["body"]
        assert "Automatic close-out failed" in body
        assert "expected 'release', found 'implementing'" in body


def test_collective_finalization_preserves_savepoint_after_status_lock_race(
    test_db: Any, monkeypatch
) -> None:
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, OWNER_CLOSED_ITEM, HOLDER_A)
    _waived_item_requirement(test_db, OWNER_CLOSED_ITEM)
    run_id = "run-status-lock-collective"
    _executing_run(test_db, run_id, (OWNER_CLOSED_ITEM,))
    _move_before_status_lock(monkeypatch, OWNER_CLOSED_ITEM, "done")

    assert cmd_update(run_id, "status", "succeeded") is None

    assert _status(test_db, "items", OWNER_CLOSED_ITEM) == "done"
    assert _status(test_db, "deployment_runs", run_id) == "succeeded"


@pytest.mark.parametrize("commit", [False, True])
def test_status_precondition_rollback_respects_transaction_owner(
    test_db: Any, monkeypatch, commit: bool
) -> None:
    _project(test_db)
    _ready_member(test_db, OWNER_CLOSED_ITEM, HOLDER_A)
    version = test_db.execute(
        "SELECT workflow_version_id FROM items WHERE id=%s", (OWNER_CLOSED_ITEM,)
    ).fetchone()["workflow_version_id"]
    test_db.execute("SAVEPOINT caller_work")
    _move_before_status_lock(monkeypatch, OWNER_CLOSED_ITEM, "implementing")

    refusal = write_precondition.lock_status_write_precondition(
        test_db,
        item_id=OWNER_CLOSED_ITEM,
        observed_status="release",
        observed_workflow_version_id=version,
        expected_status="release",
        expected_workflow_version_id=version,
        commit=commit,
    )

    assert refusal["error_code"] == "WORKFLOW_STATUS_PRECONDITION_FAILED"
    if not commit:
        test_db.execute("ROLLBACK TO SAVEPOINT caller_work")
        test_db.execute("RELEASE SAVEPOINT caller_work")
    assert _status(test_db, "items", OWNER_CLOSED_ITEM) == "release"
