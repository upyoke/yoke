"""dispatch_deployment_qa_stage wakes an item's claim holder while waiting."""

from __future__ import annotations

from typing import Any
from unittest import mock

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_qa_stage_dispatch as dispatch_mod
from yoke_core.domain.deployment_qa_stage_dispatch import dispatch_deployment_qa_stage


def _run(conn: Any, run_id: str) -> None:
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,status,created_at) "
        "VALUES (%s,1,'flow-x','executing',%s)",
        (run_id, "2026-09-14T00:00:00Z"),
    )
    conn.commit()


def _member(conn: Any, run_id: str, item_id: int) -> None:
    insert_item(conn, id=item_id, project_sequence=item_id, workflow_id="issue")
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) VALUES (%s,%s,%s)",
        (run_id, item_id, "2026-09-14T00:00:00Z"),
    )
    conn.commit()


_WAITING = {"accepted": False, "reasons": ["awaiting agent verdict"], "request_id": None}
_ACCEPTED = {"accepted": True, "reasons": [], "request_id": None}


def _patched(*, status, materialize_ok: bool = True):
    patches = [
        mock.patch.object(dispatch_mod, "deployment_qa_stage_status", return_value=status),
    ]
    if materialize_ok:
        patches.append(
            mock.patch.object(dispatch_mod, "materialize_deployment_qa_stage")
        )
    return patches


def test_wakes_the_waiting_members_claim_holder(test_db: Any) -> None:
    _run(test_db, "run-wake-1")
    _member(test_db, "run-wake-1", 9601)
    stage = {"name": "item-qa", "scope": "item"}

    with (
        mock.patch.object(
            dispatch_mod, "deployment_qa_stage_status", return_value=_WAITING
        ),
        mock.patch.object(dispatch_mod, "materialize_deployment_qa_stage"),
        mock.patch.object(
            dispatch_mod, "notify_item_scoped_qa_wait", return_value="delivered"
        ) as notify,
    ):
        rc, diag = dispatch_deployment_qa_stage(stage, run_id="run-wake-1")

    assert rc == -4
    assert "awaiting agent verdict" in diag
    notify.assert_called_once()
    assert notify.call_args.kwargs["run_id"] == "run-wake-1"
    assert notify.call_args.kwargs["stage_name"] == "item-qa"
    assert notify.call_args.kwargs["item_id"] == 9601
    assert notify.call_args.kwargs["project_id"] == 1
    assert "awaiting agent verdict" in notify.call_args.kwargs["reasons"]


def test_accepted_member_is_never_woken(test_db: Any) -> None:
    _run(test_db, "run-wake-2")
    _member(test_db, "run-wake-2", 9602)
    stage = {"name": "item-qa", "scope": "item"}

    with (
        mock.patch.object(
            dispatch_mod, "deployment_qa_stage_status", return_value=_ACCEPTED
        ),
        mock.patch.object(dispatch_mod, "materialize_deployment_qa_stage"),
        mock.patch.object(dispatch_mod, "notify_item_scoped_qa_wait") as notify,
    ):
        rc, _diag = dispatch_deployment_qa_stage(stage, run_id="run-wake-2")

    assert rc == 0
    notify.assert_not_called()


def test_run_scoped_waiting_stage_is_never_woken(test_db: Any) -> None:
    """Run scope has no single item to wake; that is a separate, ungrounded
    mechanism (waking steering's assigned combined-review agent) out of
    scope here."""
    _run(test_db, "run-wake-3")
    stage = {"name": "run-qa", "scope": "run"}

    with (
        mock.patch.object(
            dispatch_mod, "deployment_qa_stage_status", return_value=_WAITING
        ),
        mock.patch.object(dispatch_mod, "materialize_deployment_qa_stage"),
        mock.patch.object(dispatch_mod, "notify_item_scoped_qa_wait") as notify,
    ):
        rc, diag = dispatch_deployment_qa_stage(stage, run_id="run-wake-3")

    assert rc == -4
    assert "run: awaiting agent verdict" in diag
    notify.assert_not_called()


def test_a_wake_failure_degrades_without_losing_the_wait_result(
    test_db: Any, capsys
) -> None:
    _run(test_db, "run-wake-4")
    _member(test_db, "run-wake-4", 9604)
    stage = {"name": "item-qa", "scope": "item"}

    with (
        mock.patch.object(
            dispatch_mod, "deployment_qa_stage_status", return_value=_WAITING
        ),
        mock.patch.object(dispatch_mod, "materialize_deployment_qa_stage"),
        mock.patch.object(
            dispatch_mod,
            "notify_item_scoped_qa_wait",
            side_effect=RuntimeError("message service unavailable"),
        ),
    ):
        rc, diag = dispatch_deployment_qa_stage(stage, run_id="run-wake-4")

    assert rc == -4
    assert "awaiting agent verdict" in diag
    assert "could not wake item 9604" in capsys.readouterr().out
