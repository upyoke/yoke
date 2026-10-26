"""A member its owner closed during automatic close-out counts as closed."""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_delivery_close_out_notice import (
    COMPLETION_FLOW,
    _project,
    _run,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    _recipients,
)
from runtime.api.domain.test_no_obligation_member_close_out import _ready_member
from runtime.api.domain.test_run_success_member_settlement import _executing_run
from runtime.api.domain.test_satisfied_delivery_member_close_out import (
    _settled_member_requirement,
    _waived_item_requirement,
)
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from yoke_core.domain import workflow_status_transition_preflight as preflight_mod
from yoke_core.domain.deployment_delivery_close_out_notice import (
    delivery_cleared_idempotency_key,
    notify_delivery_cleared,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update


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
